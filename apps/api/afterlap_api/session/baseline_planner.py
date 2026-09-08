"""A legal fixed-schedule baseline planner, so the loop closes without A06.

This is deliberately *not* an MPC. It enumerates the admissible profiles the
rule context permits, builds one contiguous two-segment schedule for each, sizes
the energy budgets from the resolved limits, and ranks them with a declared
heuristic. Its purpose is to make the session runtime executable and testable on
its own; the real tactical planner is A06's and the runtime prefers it when it is
available (see :func:`afterlap_api.session.runtime.default_planner`).

What it guarantees:

* every emitted plan uses only profiles in ``RuleContext.admissible_profiles``;
* ``harvest_target_j`` is **battery energy gain** (coordinator decision D-01),
  and ``requested_budget_j`` is energy leaving the battery, both as the contract
  fields say;
* budgets are sized against the resolved ceiling, the battery window, the
  remaining per-lap recharge allowance and the driver's reaction time, so the
  independent checker normally agrees.

What it does *not* claim: the ranking below is a heuristic, not a validated
objective, and the plans it produces are not optimal in any measured sense.
The independent checker in :mod:`afterlap_core.rules.checker` remains the
authority — this planner never reads its own ``constraint_result`` back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CandidatePlan,
    CheckStatus,
    ConstraintResult,
    DeploymentProfile,
    ObjectiveTerms,
    PlanningResult,
    PlanningStatus,
    ProfileSegment,
    ReasonCode,
    RuleContext,
    RuleManifest,
    StateEstimate,
)
from afterlap_core.rules import CheckerState, SpeedProfile, SpeedSample

UNCHECKED_CHECKER_VERSION = "unchecked-planner-draft"
"""Placeholder checker identity on a plan that has not been independently checked yet."""

BASELINE_IDENTITY = "afterlap-baseline-fixed-schedule-1"

BASELINE_DEPLOY_FRACTION: dict[DeploymentProfile, float] = {
    DeploymentProfile.HARVEST: 0.0,
    DeploymentProfile.CONSERVE: 0.10,
    DeploymentProfile.NEUTRAL: 0.25,
    DeploymentProfile.PUSH: 0.40,
    DeploymentProfile.OVERTAKE: 0.50,
}
"""Planner's own model of what each profile asks of the ceiling. Not the
simulator's table: the two are allowed to disagree, and the checker arbitrates."""

BASELINE_HARVEST_FRACTION: dict[DeploymentProfile, float] = {
    DeploymentProfile.HARVEST: 0.45,
    DeploymentProfile.CONSERVE: 0.30,
    DeploymentProfile.NEUTRAL: 0.15,
    DeploymentProfile.PUSH: 0.05,
    DeploymentProfile.OVERTAKE: 0.0,
}
"""Fraction of the *headroom* to the battery ceiling this profile aims to recover."""

_INTENTION_FOR_PROFILE: dict[DeploymentProfile, ActionCode] = {
    DeploymentProfile.HARVEST: ActionCode.RECOVER,
    DeploymentProfile.CONSERVE: ActionCode.RECOVER,
    DeploymentProfile.NEUTRAL: ActionCode.MAINTAIN,
    DeploymentProfile.PUSH: ActionCode.PREPARE_ATTACK,
    DeploymentProfile.OVERTAKE: ActionCode.ATTACK,
}

SAFETY_MARGIN = 0.5
"""Fraction of an available headroom the baseline is willing to consume.

Half of the distance to a bound, so a modelling disagreement between this
planner's integration and the checker's cannot turn a marginal plan illegal.
"""


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """One planning invocation, pinned to the revision it was issued against.

    ``revision`` is what makes a late result discardable: the runtime compares it
    against its current revision before applying anything.
    """

    session_id: str
    revision: int
    now_s: float
    deadline_s: float
    estimate: StateEstimate
    rule_context: RuleContext
    manifest: RuleManifest
    checker_state: CheckerState
    objective_version: str
    admissible: tuple[DeploymentProfile, ...]
    model_hash: str | None = None
    learned_contribution_enabled: bool = False
    baseline_identity: str = BASELINE_IDENTITY
    segment_length_m: float = 600.0
    lead_time_s: float = 1.2
    execution_window_s: float = 1.5
    horizon_s: float = 20.0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.deadline_s <= 0.0:
            raise ValueError("a planning deadline must be positive")
        if self.segment_length_m <= 0.0:
            raise ValueError("segment length must be positive")


@runtime_checkable
class Planner(Protocol):
    """What the session runtime needs from any planner, A06's included."""

    @property
    def identity(self) -> str:
        """Stable identity recorded on every decision this planner produced."""

    def plan(self, request: PlanRequest) -> PlanningResult:
        """Produce candidates for one decision. Never raises for a normal refusal."""


@dataclass(slots=True)
class BaselinePlanner:
    """Legal fixed-schedule planner over the admissible profile set."""

    identity: str = BASELINE_IDENTITY
    max_candidates: int = 5
    _counter: int = field(default=0, repr=False)

    def plan(self, request: PlanRequest) -> PlanningResult:
        started_ms = _now_ms()
        if request.rule_context.unknown_conditions:
            return self._refusal(
                request,
                PlanningStatus.RULES_UNKNOWN,
                (ReasonCode.ELIGIBILITY_UNKNOWN,),
                "the rule context carries unresolved applicable conditions",
                started_ms,
            )

        admissible = tuple(p for p in request.admissible if p in request.rule_context.admissible_profiles)
        if not admissible:
            return self._refusal(
                request,
                PlanningStatus.NO_FEASIBLE_CANDIDATE,
                (ReasonCode.ELIGIBILITY_UNKNOWN,),
                "the rule context admits no deployment profile at this point",
                started_ms,
            )

        speed = _speed_of(request)
        if speed <= 1.0:
            return self._refusal(
                request,
                PlanningStatus.INPUT_UNAVAILABLE,
                (ReasonCode.STALE_OBSERVATIONS,),
                "no usable speed estimate; a schedule in progress needs one",
                started_ms,
            )

        candidates: list[CandidatePlan] = []
        for profile in admissible[: self.max_candidates]:
            plan = self._candidate(request, profile, speed)
            if plan is not None:
                candidates.append(plan)

        if not candidates:
            return self._refusal(
                request,
                PlanningStatus.NO_FEASIBLE_CANDIDATE,
                (ReasonCode.ENERGY_FLOOR,),
                "no admissible profile leaves a feasible energy budget at this state",
                started_ms,
            )

        ranked = sorted(candidates, key=lambda c: -c.objective.final_score)
        return PlanningResult(
            schema_version=SCHEMA_VERSION,
            session_id=request.session_id,
            state_revision=request.revision,
            status=PlanningStatus.OK,
            created_at_s=request.now_s,
            deadline_s=request.deadline_s,
            duration_ms=_now_ms() - started_ms,
            accepted=tuple(ranked),
            rejected=(),
            selected_plan_id=ranked[0].id,
            reason_codes=_reason_codes(request),
            scenario_count=0,
            candidate_count=len(ranked),
            learned_contribution_enabled=request.learned_contribution_enabled,
            baseline_identity=request.baseline_identity,
            detail=(
                "legal fixed-schedule baseline; ranking is a declared heuristic, "
                "not a validated objective, and no scenario rollout was performed"
            ),
        )

    def _candidate(
        self, request: PlanRequest, profile: DeploymentProfile, speed_mps: float
    ) -> CandidatePlan | None:
        state = request.checker_state
        limits = request.rule_context.applicable_limits
        ceiling_w = limits.deployment_ceiling_w
        if ceiling_w is None:
            return None
        derate = limits.thermal_derate_factor
        if derate is None:
            return None

        lead_m = speed_mps * max(request.lead_time_s, 2.0 * state.driver_reaction_time_s)
        start_m = state.progress_m + lead_m
        half = 0.5 * request.segment_length_m
        duration_s = half / speed_mps

        floor_j = limits.battery_energy_min_j or 0.0
        ceiling_j = limits.battery_energy_max_j
        energy_j = state.battery_energy_j

        fraction = min(BASELINE_DEPLOY_FRACTION[profile], SAFETY_MARGIN * derate)
        budget_j = fraction * ceiling_w * duration_s
        headroom_down_j = max(0.0, energy_j - floor_j) * SAFETY_MARGIN
        budget_j = min(budget_j, headroom_down_j)
        if budget_j < 0.0:
            return None

        harvest_j = BASELINE_HARVEST_FRACTION[profile] * ceiling_w * duration_s / 4.0
        if ceiling_j is not None:
            harvest_j = min(harvest_j, max(0.0, ceiling_j - energy_j) * SAFETY_MARGIN)
        remaining_j = limits.recharge_allowance_remaining_j
        if remaining_j is not None:
            harvest_j = min(harvest_j, max(0.0, remaining_j) * state.charge_bus_efficiency * SAFETY_MARGIN)
        harvest_j = max(0.0, harvest_j)

        window_s = max(request.execution_window_s, 2.0 * state.driver_reaction_time_s)
        segments = (
            ProfileSegment(
                start_progress_m=start_m,
                end_progress_m=start_m + half,
                profile_id=profile,
                requested_budget_j=budget_j,
                harvest_target_j=0.0 if budget_j > 0.0 else harvest_j,
                execution_window_s=window_s,
            ),
            ProfileSegment(
                start_progress_m=start_m + half,
                end_progress_m=start_m + 2.0 * half,
                profile_id=profile,
                requested_budget_j=0.0,
                harvest_target_j=harvest_j,
                execution_window_s=window_s,
            ),
        )

        self._counter += 1
        plan_id = f"plan-{request.revision}-{profile.value}-{self._counter}"
        objective = self._objective(request, profile, budget_j, harvest_j, duration_s)
        return CandidatePlan(
            schema_version=SCHEMA_VERSION,
            id=plan_id,
            state_revision=request.revision,
            intention=_INTENTION_FOR_PROFILE[profile],
            profile_segments=segments,
            scenario_outcomes=(),
            terminal_target_energy_j=max(0.0, energy_j - budget_j + harvest_j),
            objective=objective,
            constraint_result=_unchecked_result(request),
            model_version=request.model_hash,
            objective_version=request.objective_version,
            solver_status="baseline_fixed_schedule",
            solve_duration_ms=0.0,
            reason_codes=_reason_codes(request),
            probabilities=(),
        )

    def _objective(
        self,
        request: PlanRequest,
        profile: DeploymentProfile,
        budget_j: float,
        harvest_j: float,
        duration_s: float,
    ) -> ObjectiveTerms:
        """Declared heuristic ranking. Dimensionless, and never reported as seconds.

        Deployed energy is preferred when a rival is close ahead and penalised
        when the battery is near its floor; recovered energy is credited at a
        lower weight because it is worth something later rather than now.
        """
        gap_pressure = _gap_pressure(request.estimate)
        window_j = max(1.0, (request.rule_context.applicable_limits.battery_energy_max_j or 4.0e6))
        deploy_term = (budget_j / window_j) * (0.5 + gap_pressure)
        harvest_term = 0.25 * (harvest_j / window_j)
        expected_utility = deploy_term + harvest_term
        switch_count = 0 if profile is _current_profile(request.estimate) else 1
        lambda_switch = 0.1
        return ObjectiveTerms(
            objective_version=request.objective_version,
            expected_utility=expected_utility,
            tail_alpha=0.1,
            cvar_loss=max(0.0, -expected_utility),
            lambda_tail=0.0,
            switch_count=switch_count,
            lambda_switch=lambda_switch,
            disagreement_penalty=0.0,
            generation_score=None,
            final_score=expected_utility - lambda_switch * switch_count,
        )

    def _refusal(
        self,
        request: PlanRequest,
        status: PlanningStatus,
        reasons: tuple[ReasonCode, ...],
        detail: str,
        started_ms: float,
    ) -> PlanningResult:
        return PlanningResult(
            schema_version=SCHEMA_VERSION,
            session_id=request.session_id,
            state_revision=request.revision,
            status=status,
            created_at_s=request.now_s,
            deadline_s=request.deadline_s,
            duration_ms=_now_ms() - started_ms,
            accepted=(),
            rejected=(),
            selected_plan_id=None,
            reason_codes=tuple(dict.fromkeys((*reasons, *_reason_codes(request)))),
            learned_contribution_enabled=request.learned_contribution_enabled,
            baseline_identity=request.baseline_identity,
            detail=detail,
        )


def checker_state_for(
    *,
    estimate: StateEstimate,
    session_time_s: float,
    track_length_m: float,
    battery_energy_j: float,
    driver_reaction_time_s: float,
    charge_bus_efficiency: float,
    discharge_efficiency: float,
) -> CheckerState:
    """Build the checker's own reintegration state from a published estimate.

    ``current_power_w`` falls back to 0 W when the source publishes no
    electrical-power channel. That is the *conservative* direction for the
    power-ramp check: it maximises the demanded change at entry, so an unknown
    current power can only make a plan look harder to execute, never easier.
    """
    own = estimate.own_car
    speed = own.speed_mps.value
    progress = own.progress_m.value
    if speed is None or speed <= 0.0 or progress is None:
        raise ValueError("a checker state needs a usable speed and progress estimate")
    power = own.electrical_power_w.value
    return CheckerState(
        session_time_s=session_time_s,
        progress_m=float(progress),
        battery_energy_j=float(battery_energy_j),
        speed_profile=SpeedProfile(samples=(SpeedSample(0.0, float(speed)),), step=True),
        track_length_m=track_length_m,
        current_power_w=0.0 if power is None else float(power),
        recharge_used_this_lap_j=float(own.recharge_spent_this_lap_j.value or 0.0),
        driver_reaction_time_s=driver_reaction_time_s,
        charge_bus_efficiency=charge_bus_efficiency,
        discharge_efficiency=discharge_efficiency,
    )


def _unchecked_result(request: PlanRequest) -> ConstraintResult:
    """A placeholder the independent checker replaces.

    ``CandidatePlan`` requires a constraint result, so a draft carries one that
    says plainly it has not been checked. Nothing consumes it: the runtime always
    overwrites it with ``rules.check_plan``'s verdict before publishing.
    """
    return ConstraintResult(
        schema_version=SCHEMA_VERSION,
        status=CheckStatus.UNKNOWN,
        checks=(),
        ruleset_hash=request.rule_context.ruleset_hash,
        checked_at_s=max(request.now_s, 0.0),
        checker_version=UNCHECKED_CHECKER_VERSION,
        unresolved_conditions=("plan_has_not_been_independently_checked",),
    )


def _reason_codes(request: PlanRequest) -> tuple[ReasonCode, ...]:
    reasons: list[ReasonCode] = []
    if not request.estimate.quality.own_energy_capability:
        reasons.append(ReasonCode.OWN_ENERGY_UNAVAILABLE)
    if any(rival.energy_mean_j is None for rival in request.estimate.rival_beliefs):
        reasons.append(ReasonCode.RIVAL_ENERGY_UNKNOWN)
    if not request.learned_contribution_enabled:
        reasons.append(ReasonCode.BASELINE_FALLBACK)
    return tuple(dict.fromkeys(reasons))


def _speed_of(request: PlanRequest) -> float:
    value = request.estimate.own_car.speed_mps.value
    return 0.0 if value is None else float(value)


def _current_profile(estimate: StateEstimate) -> DeploymentProfile | None:
    active = estimate.own_car.active_profile_id
    if active is None:
        return None
    try:
        return DeploymentProfile(active)
    except ValueError:
        return None


def _gap_pressure(estimate: StateEstimate) -> float:
    """How close the nearest rival ahead is, in ``[0, 1]``. Unknown gap is 0."""
    ahead = estimate.nearest_ahead
    if ahead is None or ahead.gap_s.value is None:
        return 0.0
    gap = abs(float(ahead.gap_s.value))
    return max(0.0, min(1.0, 1.0 - gap / 3.0))


def _now_ms() -> float:
    return math.floor(_perf_counter() * 1e6) / 1e3


def _perf_counter() -> float:
    from time import perf_counter

    return perf_counter()


__all__ = [
    "BASELINE_DEPLOY_FRACTION",
    "BASELINE_HARVEST_FRACTION",
    "BASELINE_IDENTITY",
    "SAFETY_MARGIN",
    "UNCHECKED_CHECKER_VERSION",
    "BaselinePlanner",
    "PlanRequest",
    "Planner",
    "checker_state_for",
]
