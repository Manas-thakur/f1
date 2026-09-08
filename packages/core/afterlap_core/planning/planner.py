"""The runtime planning algorithm.

``planning/TECHNICAL_SPEC.md`` fixes the order and this module follows it:

1. verify required inputs, freshness, rule coverage and the execution window;
2. build weighted opponent scenarios from the belief state;
3. add baseline and learned budget proposals, then enumerate feasible intentions;
4. optimise inside the fixed deadline with bounded candidate and scenario counts;
5. re-simulate and **independently recheck** every candidate through
   ``afterlap_core.rules.check_plan``, rejecting unknown critical constraints;
6. compare expected benefit, downside, future energy and current-plan hysteresis;
7. produce an immutable evidence record and structured recommendation fields.

Two rules are load-bearing.

**The checker's verdict is final.** A mathematically converged solve that the
independent checker rejects is a rejected candidate. Nothing here inspects
``ConstraintResult`` and decides it was close enough, and ``unknown`` is not
acceptance.

**A late answer is not an answer.** The deadline is checked before every solve
and after every stage. When it expires the planner returns
``PlanningStatus.DEADLINE_EXCEEDED`` and tactical advice is withdrawn, unless a
current or baseline plan revalidates — in which case the caller keeps the
instruction it already has (:func:`build_recommendation` returns ``None``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CandidatePlan,
    CheckStatus,
    ConstraintCheck,
    ConstraintResult,
    DeploymentProfile,
    ObjectiveTerms,
    PlanningResult,
    PlanningStatus,
    ProfileSegment,
    ReasonCode,
    Recommendation,
    RecommendationStatus,
    RuleContext,
    RuleManifest,
    StateEstimate,
    Trigger,
)

from ..rules import (
    CHECKER_VERSION,
    THERMAL_TEMPERATURE_UNKNOWN,
    SpeedProfile,
    check_plan,
    load_rule_pack,
)
from .config import PlannerConfig, load_planner_config
from .enumerator import EnumerationResult, enumerate_intentions
from .objective import ObjectiveManifest, load_objective
from .optimiser import (
    AllocationSolution,
    SolverDeadlineExpired,
    SolverUnavailable,
    solve_allocation,
    solver_identity,
)
from .rollout import PlanningWorld, RolloutEvidence, rollout_candidate
from .scenarios import PlanScenario, ScenarioSample, scenarios_from_estimate
from .scoring import (
    ActivePlan,
    ContinuationModel,
    InvalidationCause,
    LearnedOutcome,
    ScoredCandidate,
    apply_learned_reranking,
    build_objective_terms,
    select_instruction,
    switch_count_for,
)
from .segments import PlanFrame, checker_state_for, to_profile_segments
from .surrogate import build_weights

__all__ = [
    "DEFAULT_DEADLINE_S",
    "BudgetProposal",
    "DeadlineClock",
    "active_plan_from",
    "build_recommendation",
    "plan",
]

DEFAULT_DEADLINE_S = 0.2
"""The declared decision budget. ``planning/TECHNICAL_SPEC.md`` sets p95 <= 200 ms."""

_DEFAULT_RULE_PACK = "synthetic-pack-v1"


@dataclass(frozen=True, slots=True)
class DeadlineClock:
    """Monotonic decision budget."""

    budget_s: float
    started_at: float

    @classmethod
    def start(cls, budget_s: float) -> DeadlineClock:
        if budget_s <= 0.0:
            raise ValueError("a planning deadline must be positive")
        return cls(budget_s=budget_s, started_at=time.perf_counter())

    @property
    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started_at

    @property
    def remaining_s(self) -> float:
        return self.budget_s - self.elapsed_s

    @property
    def expired(self) -> bool:
        return self.remaining_s <= 0.0

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_s * 1000.0


class BudgetProposal:
    """A warm-start budget proposal.

    A frozen learned actor may propose an allocation to start the solve from.
    It can only move the *starting point*: the feasible set, the checker and the
    baseline candidates are untouched, so a proposal cannot buy an illegal plan
    and cannot remove the validated reference.
    """

    __slots__ = ("deploy_j", "harvest_j", "source")

    def __init__(self, deploy_j: tuple[float, ...], harvest_j: tuple[float, ...], source: str) -> None:
        self.deploy_j = deploy_j
        self.harvest_j = harvest_j
        self.source = source


@dataclass(frozen=True, slots=True)
class _SolvedCandidate:
    """One converged solve, before the independent recheck decides its fate."""

    candidate_id: str
    action_code: ActionCode
    frame: PlanFrame
    segments: tuple[ProfileSegment, ...]
    solution: AllocationSolution
    terms: ObjectiveTerms

    @property
    def generation_score(self) -> float:
        score = self.terms.generation_score
        return self.terms.final_score if score is None else score


@lru_cache(maxsize=4)
def _default_manifest(pack_id: str) -> RuleManifest:
    return load_rule_pack(pack_id).manifest


@lru_cache(maxsize=4)
def _default_world(scenario_id: str, seed: int) -> PlanningWorld:
    return PlanningWorld.from_scenario(scenario_id, seed=seed)


def _failure(
    estimate: StateEstimate,
    clock: DeadlineClock,
    status: PlanningStatus,
    reasons: tuple[ReasonCode, ...],
    detail: str,
    *,
    scenario_count: int = 0,
    candidate_count: int = 0,
    learned_enabled: bool = False,
    rejected: tuple[CandidatePlan, ...] = (),
) -> PlanningResult:
    """An unsuccessful result that still carries the alternatives considered.

    ``rejected`` is retained even on failure: an inspector needs to see what was
    optimised and why the checker refused it, not just that nothing survived.
    """
    return PlanningResult(
        schema_version=SCHEMA_VERSION,
        session_id=estimate.session_id,
        state_revision=estimate.revision,
        status=status,
        created_at_s=estimate.created_at_s,
        deadline_s=clock.budget_s,
        duration_ms=clock.elapsed_ms,
        rejected=rejected,
        reason_codes=reasons,
        scenario_count=scenario_count,
        candidate_count=candidate_count,
        learned_contribution_enabled=learned_enabled,
        detail=detail,
    )


def _verify_inputs(
    estimate: StateEstimate,
    rule_context: RuleContext,
    config: PlannerConfig,
    now_s: float,
) -> tuple[PlanningStatus, tuple[ReasonCode, ...], str] | None:
    """Gate on inputs, freshness and rule coverage. ``None`` means proceed."""
    own = estimate.own_car
    if not estimate.quality.own_energy_capability or not own.has_energy_capability:
        return (
            PlanningStatus.INPUT_UNAVAILABLE,
            (ReasonCode.OWN_ENERGY_UNAVAILABLE,),
            "the estimate carries no usable battery energy, so no precise energy advice is supportable",
        )
    speed = own.speed_mps.value
    if speed is None or speed <= 0.0:
        return (
            PlanningStatus.INPUT_UNAVAILABLE,
            (ReasonCode.STALE_OBSERVATIONS,),
            "the estimate carries no usable speed",
        )
    age_s = now_s - estimate.cutoff_s
    if age_s > float(config.budgets.estimate_max_age_s.value):
        return (
            PlanningStatus.INPUT_UNAVAILABLE,
            (ReasonCode.STALE_OBSERVATIONS,),
            (
                f"the estimate is {age_s:.3f} s old against a "
                f"{float(config.budgets.estimate_max_age_s.value):.3f} s limit"
            ),
        )
    if rule_context.unknown_conditions:
        reason = (
            ReasonCode.THERMAL_DERATE
            if THERMAL_TEMPERATURE_UNKNOWN in rule_context.unknown_conditions
            else ReasonCode.ELIGIBILITY_UNKNOWN
        )
        return (
            PlanningStatus.RULES_UNKNOWN,
            (reason,),
            "unresolved applicable conditions: " + ", ".join(rule_context.unknown_conditions),
        )
    if not rule_context.admissible_profiles:
        return (
            PlanningStatus.RULES_UNKNOWN,
            (ReasonCode.ELIGIBILITY_UNKNOWN,),
            "the resolved rule context admits no deployment profile",
        )
    return None


def _invalidation_for(
    rule_context: RuleContext,
    current: ActivePlan | None,
    now_s: float,
) -> InvalidationCause | None:
    """Reasons that override hysteresis outright."""
    if current is None:
        return None
    if current.ruleset_hash != rule_context.ruleset_hash:
        return InvalidationCause.RULESET_CHANGED
    if now_s >= current.expires_at_s:
        return InvalidationCause.EXPIRED
    if rule_context.unknown_conditions:
        return InvalidationCause.UNKNOWN_CONDITION
    return None


def _candidate_plan(
    candidate_id: str,
    action_code: ActionCode,
    estimate: StateEstimate,
    segments: tuple[ProfileSegment, ...],
    solution: AllocationSolution,
    evidence: RolloutEvidence | None,
    constraint_result: ConstraintResult,
    objective_terms: ObjectiveTerms,
    reasons: tuple[ReasonCode, ...],
    learned: LearnedOutcome,
    terminal_target_energy_j: float | None,
) -> CandidatePlan:
    return CandidatePlan(
        schema_version=SCHEMA_VERSION,
        id=candidate_id,
        state_revision=estimate.revision,
        intention=action_code,
        profile_segments=segments,
        scenario_outcomes=() if evidence is None else evidence.outcomes,
        terminal_target_energy_j=terminal_target_energy_j,
        objective=objective_terms,
        constraint_result=constraint_result,
        model_version=learned.bundle_id if learned.enabled else None,
        objective_version=objective_terms.objective_version,
        solver_status=f"{solution.solver_status} ({solver_identity()})",
        solve_duration_ms=solution.duration_ms,
        reason_codes=reasons,
        probabilities=() if evidence is None else evidence.probabilities,
    )


def plan(
    estimate: StateEstimate,
    rule_context: RuleContext,
    model_bundle: ContinuationModel | None = None,
    deadline: float = DEFAULT_DEADLINE_S,
    *,
    manifest: RuleManifest | None = None,
    world: PlanningWorld | None = None,
    config: PlannerConfig | None = None,
    objective: ObjectiveManifest | None = None,
    scenarios: ScenarioSample | None = None,
    current_plan: ActivePlan | None = None,
    proposal: BudgetProposal | None = None,
    speed_profile: SpeedProfile | None = None,
    terminal_target_energy_j: float | None = None,
    admissible: tuple[DeploymentProfile, ...] | None = None,
    now_s: float | None = None,
    seed: int = 0,
    rollout_enabled: bool = True,
) -> PlanningResult:
    """Plan one decision.

    ``estimate``, ``rule_context``, ``model_bundle`` and ``deadline`` are the
    specified public arguments. Everything else is keyword-only with a default
    that resolves from the shipped synthetic configuration, so the four-argument
    call in the specification works unchanged while an integrator can supply the
    real rule pack, simulator bundle and scenario ensemble.

    ``model_bundle`` is the learned continuation ensemble. With ``None`` — or one
    that reports itself out of support — learned scoring is disabled and the
    result is exactly the baseline.
    """
    clock = DeadlineClock.start(deadline)
    settings = config or load_planner_config()
    manifest_ = manifest or _default_manifest(_DEFAULT_RULE_PACK)
    objective_ = objective or load_objective()
    moment_s = estimate.created_at_s if now_s is None else now_s

    failure = _verify_inputs(estimate, rule_context, settings, moment_s)
    if failure is not None:
        status, gate_reasons, detail = failure
        return _failure(estimate, clock, status, gate_reasons, detail)

    try:
        sample = scenarios or scenarios_from_estimate(
            estimate,
            settings,
            battery_max_j=manifest_.battery_energy_max_j,
            seed=seed,
        )
    except ValueError as exc:
        return _failure(
            estimate,
            clock,
            PlanningStatus.INPUT_UNAVAILABLE,
            (ReasonCode.RIVAL_ENERGY_UNKNOWN,),
            f"no usable opponent scenario could be built: {exc}",
        )

    enumeration: EnumerationResult = enumerate_intentions(
        estimate,
        rule_context,
        manifest_,
        settings,
        admissible=admissible if admissible is not None else rule_context.admissible_profiles,
        terminal_target_energy_j=terminal_target_energy_j,
    )
    if not enumeration.candidates:
        return _failure(
            estimate,
            clock,
            PlanningStatus.NO_FEASIBLE_CANDIDATE,
            enumeration.reason_codes,
            "; ".join(f"{s.action_code.value}: {s.detail}" for s in enumeration.suppressed)
            or "no tactical intention survived enumeration",
            scenario_count=sample.count,
        )

    checker_state = checker_state_for(
        estimate,
        settings,
        track_length_m=estimate.race_context.track_length_m,
        speed_profile=speed_profile,
    )
    active_profile = _active_profile(estimate)

    solved: list[_SolvedCandidate] = []
    for candidate in enumeration.candidates:
        if clock.expired:
            return _deadline_result(estimate, clock, sample, len(enumeration.candidates))
        weights = build_weights(candidate.frame, estimate, objective_, settings)
        warm = None
        if proposal is not None and len(proposal.deploy_j) == len(candidate.frame.segments):
            warm = (proposal.deploy_j, proposal.harvest_j)
        try:
            solution = solve_allocation(
                candidate.frame,
                sample.scenarios,
                weights,
                objective_,
                settings,
                remaining_deadline_s=clock.remaining_s,
                warm_start=warm,
            )
        except SolverDeadlineExpired:
            return _deadline_result(estimate, clock, sample, len(enumeration.candidates))
        except SolverUnavailable as exc:
            return _failure(
                estimate,
                clock,
                PlanningStatus.SOLVER_UNAVAILABLE,
                (ReasonCode.SOLVER_TIMEOUT,),
                f"the continuous solver is unavailable: {exc}",
                scenario_count=sample.count,
                candidate_count=len(enumeration.candidates),
            )
        if solution.deadline_exceeded:
            return _deadline_result(estimate, clock, sample, len(enumeration.candidates))
        if not solution.converged:
            continue
        segments = to_profile_segments(candidate.frame, solution.deploy_j, solution.harvest_j)
        switches = switch_count_for(segments, active_profile)
        solved.append(
            _SolvedCandidate(
                candidate_id=candidate.candidate_id,
                action_code=candidate.template.action_code,
                frame=candidate.frame,
                segments=segments,
                solution=solution,
                terms=build_objective_terms(solution, objective_, switch_count=switches),
            )
        )

    if not solved:
        return _failure(
            estimate,
            clock,
            PlanningStatus.NO_FEASIBLE_CANDIDATE,
            (ReasonCode.SOLVER_TIMEOUT,),
            "no enumerated intention produced a converged continuous solution",
            scenario_count=sample.count,
            candidate_count=len(enumeration.candidates),
        )

    scored: list[ScoredCandidate] = []
    rejected: list[CandidatePlan] = []

    graded = sorted(solved, key=lambda entry: (entry.generation_score, entry.candidate_id))

    finalist_limit = settings.budgets.rollout_finalists
    rollout_world = world or _default_world("two-straight-counterattack", 20260908)
    rollout_scenarios = _renormalise(sample.scenarios[: settings.budgets.rollout_scenarios])
    records: dict[str, CandidatePlan] = {}

    for position, entry in enumerate(graded):
        candidate_id = entry.candidate_id
        action_code = entry.action_code
        segments = entry.segments
        solution = entry.solution
        terms = entry.terms
        constraint_result = check_plan(
            _probe_plan(candidate_id, action_code, estimate, segments, terms),
            checker_state,
            rule_context,
            manifest=manifest_,
        )
        weights = build_weights(entry.frame, estimate, objective_, settings)
        reasons: list[ReasonCode] = list(sample.reason_codes)
        evidence: RolloutEvidence | None = None
        learned = LearnedOutcome(
            enabled=False,
            bundle_id=None,
            reason_codes=(ReasonCode.LEARNED_MODEL_DISABLED, ReasonCode.BASELINE_FALLBACK),
            disagreement=0.0,
        )
        final_terms = terms

        eligible = constraint_result.status is CheckStatus.PASS and position < finalist_limit
        if eligible and rollout_enabled and not clock.expired:
            evidence = rollout_candidate(
                segments,
                entry.frame,
                rollout_scenarios,
                rollout_world,
                estimate,
                settings,
                weights,
                candidate_id=candidate_id,
            )
            final_terms, outcomes, learned = apply_learned_reranking(
                terms,
                evidence.outcomes,
                entry.frame,
                weights,
                objective_,
                model_bundle,
                disagreement_weight=objective_.disagreement_penalty_weight,
            )
            evidence = RolloutEvidence(
                outcomes=outcomes,
                probabilities=evidence.probabilities,
                expected_utility=evidence.expected_utility,
                sample_count=evidence.sample_count,
                step_s=evidence.step_s,
                horizon_s=evidence.horizon_s,
                incomplete_count=evidence.incomplete_count,
            )
            reasons.extend(learned.reason_codes)
        elif eligible and not rollout_enabled:
            final_terms, _, learned = apply_learned_reranking(
                terms,
                (),
                entry.frame,
                weights,
                objective_,
                model_bundle,
                disagreement_weight=objective_.disagreement_penalty_weight,
            )
            reasons.extend(learned.reason_codes)
        else:
            reasons.extend(learned.reason_codes)
            if constraint_result.status is CheckStatus.PASS:
                reasons.append(ReasonCode.SMALL_EXPECTED_IMPROVEMENT)

        plan_record = _candidate_plan(
            candidate_id,
            action_code,
            estimate,
            segments,
            solution,
            evidence,
            constraint_result,
            final_terms,
            tuple(dict.fromkeys(reasons)),
            learned,
            terminal_target_energy_j,
        )
        if eligible:
            records[candidate_id] = plan_record
            scored.append(
                ScoredCandidate(
                    candidate_id=candidate_id,
                    action_code=action_code,
                    frame=entry.frame,
                    segments=segments,
                    solution=solution,
                    scenario_outcomes=plan_record.scenario_outcomes,
                    probabilities=plan_record.probabilities,
                    constraint_result=constraint_result,
                    objective=final_terms,
                    reason_codes=plan_record.reason_codes,
                    learned=learned,
                )
            )
        else:
            rejected.append(plan_record)

    if clock.expired:
        return _deadline_result(estimate, clock, sample, len(enumeration.candidates))

    selection = select_instruction(
        scored,
        objective_,
        current=current_plan,
        now_s=moment_s,
        invalidation=_invalidation_for(rule_context, current_plan, moment_s),
    )
    accepted = tuple(
        records[candidate.candidate_id].model_copy(
            update={
                "reason_codes": tuple(
                    dict.fromkeys(list(candidate.reason_codes) + list(selection.reason_codes))
                )
            }
        )
        if candidate is selection.chosen
        else records[candidate.candidate_id]
        for candidate in scored
    )
    if not accepted:
        return _failure(
            estimate,
            clock,
            PlanningStatus.NO_FEASIBLE_CANDIDATE,
            tuple(dict.fromkeys(list(enumeration.reason_codes) + list(sample.reason_codes))),
            "every converged candidate was rejected by the independent checker",
            scenario_count=sample.count,
            candidate_count=len(enumeration.candidates),
            rejected=tuple(rejected),
        )

    learned_enabled = any(candidate.learned.enabled for candidate in scored)
    return PlanningResult(
        schema_version=SCHEMA_VERSION,
        session_id=estimate.session_id,
        state_revision=estimate.revision,
        status=PlanningStatus.OK,
        created_at_s=estimate.created_at_s,
        deadline_s=clock.budget_s,
        duration_ms=clock.elapsed_ms,
        accepted=accepted,
        rejected=tuple(rejected),
        selected_plan_id=None if selection.chosen is None else selection.chosen.candidate_id,
        reason_codes=tuple(
            dict.fromkeys(
                list(selection.reason_codes) + list(sample.reason_codes) + list(enumeration.reason_codes)
            )
        ),
        scenario_count=sample.count,
        candidate_count=len(enumeration.candidates),
        learned_contribution_enabled=learned_enabled,
        baseline_identity="mpc_baseline",
        detail=f"{selection.detail}; rival energy support: {sample.energy_support}",
    )


def _renormalise(scenarios: tuple[PlanScenario, ...]) -> tuple[PlanScenario, ...]:
    """Rescale a truncated ensemble so its weights are a probability distribution again."""
    total = sum(scenario.weight for scenario in scenarios)
    if total <= 0.0:
        raise ValueError("a rollout ensemble needs positive total weight")
    return tuple(
        PlanScenario(
            scenario_id=scenario.scenario_id,
            weight=scenario.weight / total,
            rival_reserve_j=scenario.rival_reserve_j,
            rival_pace_gain_s=scenario.rival_pace_gain_s,
            intention=scenario.intention,
            energy_known=scenario.energy_known,
            source=scenario.source,
        )
        for scenario in scenarios
    )


def _active_profile(estimate: StateEstimate) -> DeploymentProfile | None:
    raw = estimate.own_car.active_profile_id
    if raw is None:
        return None
    try:
        return DeploymentProfile(raw)
    except ValueError:
        return None


def _probe_plan(
    candidate_id: str,
    action_code: ActionCode,
    estimate: StateEstimate,
    segments: tuple[ProfileSegment, ...],
    terms: ObjectiveTerms,
) -> CandidatePlan:
    """A minimal plan record handed to the checker.

    The checker reads only the segments and never the planner's own solver
    status or self-assessment, so this record deliberately carries an
    ``unknown`` constraint result: the verdict is the checker's to produce.
    """
    return CandidatePlan(
        schema_version=SCHEMA_VERSION,
        id=candidate_id,
        state_revision=estimate.revision,
        intention=action_code,
        profile_segments=segments,
        objective=terms,
        constraint_result=ConstraintResult(
            schema_version=SCHEMA_VERSION,
            status=CheckStatus.UNKNOWN,
            checks=(
                ConstraintCheck(
                    check_id="not_yet_checked",
                    status=CheckStatus.UNKNOWN,
                    detail="this candidate has not been through the independent checker",
                ),
            ),
            ruleset_hash="pending",
            checked_at_s=estimate.cutoff_s,
            checker_version=CHECKER_VERSION,
        ),
        objective_version=terms.objective_version,
    )


def _deadline_result(
    estimate: StateEstimate,
    clock: DeadlineClock,
    sample: ScenarioSample,
    candidate_count: int,
) -> PlanningResult:
    return _failure(
        estimate,
        clock,
        PlanningStatus.DEADLINE_EXCEEDED,
        (ReasonCode.SOLVER_TIMEOUT,),
        (
            f"the {clock.budget_s * 1000.0:.0f} ms decision budget expired after "
            f"{clock.elapsed_ms:.1f} ms; a late plan is not published"
        ),
        scenario_count=sample.count,
        candidate_count=candidate_count,
    )


def _withdraw(
    estimate: StateEstimate,
    rule_context: RuleContext,
    objective: ObjectiveManifest,
    config: PlannerConfig,
    result: PlanningResult,
    revision: int,
) -> Recommendation:
    validity_s = float(config.execution.recommendation_validity_s.value)
    return Recommendation(
        schema_version=SCHEMA_VERSION,
        id=f"rec-{estimate.session_id}-{estimate.revision}",
        revision=revision,
        session_id=estimate.session_id,
        state_revision=estimate.revision,
        plan_id=None,
        status=RecommendationStatus.PROPOSED,
        action_code=ActionCode.WITHDRAW_ADVICE,
        display_text="No tactical advice - see reason codes",
        trigger=Trigger(kind="immediate", description="Advice withdrawn now"),
        end_condition="next planner update",
        created_at_s=estimate.created_at_s,
        valid_from_s=estimate.created_at_s,
        expires_at_s=estimate.created_at_s + validity_s,
        observation_cutoff_s=estimate.cutoff_s,
        ruleset_hash=rule_context.ruleset_hash,
        objective_version=objective.objective_id,
        reason_codes=result.reason_codes,
        constraint_result=ConstraintResult(
            schema_version=SCHEMA_VERSION,
            status=CheckStatus.UNKNOWN,
            checks=(
                ConstraintCheck(
                    check_id="planning_precondition",
                    status=CheckStatus.UNKNOWN,
                    detail=result.detail or "the planner produced no acceptable candidate",
                ),
            ),
            ruleset_hash=rule_context.ruleset_hash,
            checked_at_s=estimate.cutoff_s,
            checker_version=CHECKER_VERSION,
        ),
        learned_contribution_enabled=False,
        baseline_identity=result.baseline_identity,
    )


def build_recommendation(
    result: PlanningResult,
    estimate: StateEstimate,
    rule_context: RuleContext,
    *,
    config: PlannerConfig | None = None,
    objective: ObjectiveManifest | None = None,
    current_plan: ActivePlan | None = None,
    revision: int = 1,
    now_s: float | None = None,
) -> Recommendation | None:
    """Turn a planning result into the published instruction.

    Returns ``None`` when the deadline expired and the instruction already in
    force still revalidates: the correct action is then to keep it, not to
    publish a late replacement. In every other unsuccessful case tactical advice
    is **withdrawn**, which is a published state, not silence.
    """
    settings = config or load_planner_config()
    objective_ = objective or load_objective()
    moment_s = estimate.created_at_s if now_s is None else now_s

    if result.status is not PlanningStatus.OK or result.selected_plan_id is None:
        if (
            result.status is PlanningStatus.DEADLINE_EXCEEDED
            and current_plan is not None
            and current_plan.ruleset_hash == rule_context.ruleset_hash
            and moment_s < current_plan.expires_at_s
        ):
            return None
        return _withdraw(estimate, rule_context, objective_, settings, result, revision)

    chosen = next(candidate for candidate in result.accepted if candidate.id == result.selected_plan_id)
    head = chosen.profile_segments[0]
    validity_s = float(settings.execution.recommendation_validity_s.value)
    verb = {
        ActionCode.MAINTAIN: "Hold",
        ActionCode.RECOVER: "Harvest",
        ActionCode.PREPARE_ATTACK: "Conserve then push",
        ActionCode.ATTACK: "Attack",
        ActionCode.DEFEND: "Defend",
        ActionCode.WITHDRAW_ADVICE: "Withdraw",
    }[chosen.intention]
    return Recommendation(
        schema_version=SCHEMA_VERSION,
        id=f"rec-{estimate.session_id}-{estimate.revision}",
        revision=revision,
        session_id=estimate.session_id,
        state_revision=estimate.revision,
        plan_id=chosen.id,
        status=RecommendationStatus.PROPOSED,
        action_code=chosen.intention,
        display_text=(
            f"{verb}: {head.profile_id.value} to {head.end_progress_m:.0f} m "
            f"({head.requested_budget_j / 1000.0:.0f} kJ out)"
        ),
        trigger=Trigger(
            kind="checkpoint",
            progress_m=head.start_progress_m,
            description=f"At {head.start_progress_m:.0f} m",
        ),
        end_condition=f"{chosen.profile_segments[-1].end_progress_m:.0f} m",
        created_at_s=estimate.created_at_s,
        valid_from_s=estimate.created_at_s,
        expires_at_s=estimate.created_at_s + validity_s,
        observation_cutoff_s=estimate.cutoff_s,
        ruleset_hash=rule_context.ruleset_hash,
        model_hash=chosen.model_version,
        objective_version=chosen.objective_version,
        reason_codes=chosen.reason_codes,
        outcomes=tuple(outcome for scenario in chosen.scenario_outcomes for outcome in scenario.checkpoints)[
            :8
        ],
        probabilities=chosen.probabilities,
        constraint_result=chosen.constraint_result,
        learned_contribution_enabled=result.learned_contribution_enabled,
        baseline_identity=result.baseline_identity,
    )


def active_plan_from(
    result: PlanningResult,
    rule_context: RuleContext,
    *,
    selected_at_s: float,
    validity_s: float,
) -> ActivePlan | None:
    """Record the instruction now in force, for the next invocation's hysteresis."""
    if result.selected_plan_id is None:
        return None
    chosen = next(candidate for candidate in result.accepted if candidate.id == result.selected_plan_id)
    return ActivePlan(
        plan_id=chosen.id,
        action_code=chosen.intention,
        selected_at_s=selected_at_s,
        expires_at_s=selected_at_s + validity_s,
        ruleset_hash=rule_context.ruleset_hash,
        final_score=chosen.objective.final_score,
        head_profile=chosen.profile_segments[0].profile_id,
    )
