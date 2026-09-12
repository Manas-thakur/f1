"""Planner outputs: candidate plans, scenario outcomes and recommendations.

Physical metrics (position, elapsed time, energy) and the dimensionless utility
are kept as separate fields. A utility number is never reported as seconds.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import (
    ActionCode,
    CalibrationStatus,
    CheckStatus,
    DeploymentProfile,
    PlanningStatus,
    ReasonCode,
    RecommendationStatus,
)
from .quantities import IntervalValue, ProbabilityStatement
from .rules import ConstraintResult


class ProfileSegment(Contract):
    """One human-executable instruction over a stretch of track.

    Control is expressed as a driver-selectable profile plus an energy budget,
    not a millisecond power trace.
    """

    start_progress_m: float = Field(ge=0.0)
    end_progress_m: float = Field(ge=0.0)
    profile_id: DeploymentProfile
    requested_budget_j: float = Field(
        ge=0.0,
        description=(
            "Electrical energy to deploy over this segment, measured as energy leaving the "
            "battery. The regulated power ceiling applies at the ERS-K DC bus, so a checker "
            "converts before comparing."
        ),
    )
    harvest_target_j: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Energy to recover over this segment, measured as BATTERY ENERGY GAIN. This is the "
            "quantity the car actually stores. The regulatory recharge allowance is measured at "
            "the CU-K DC bus and differs by the charge efficiency, so a consumer converts "
            "explicitly rather than comparing the two numbers directly."
        ),
    )
    execution_window_s: float = Field(gt=0.0, description="Time the driver has to begin this segment.")

    @model_validator(mode="after")
    def _ordered(self) -> ProfileSegment:
        if self.end_progress_m <= self.start_progress_m:
            raise ValueError("profile segment must advance in progress")
        return self

    @property
    def length_m(self) -> float:
        return self.end_progress_m - self.start_progress_m


class CheckpointOutcome(Contract):
    """Predicted or realised state at a named checkpoint."""

    checkpoint_id: str = Field(min_length=1)
    progress_m: float = Field(ge=0.0)
    elapsed_time_s: float | None = None
    gap_to_reference_s: float | None = None
    own_energy_j: float | None = None
    position: int | None = Field(default=None, ge=1)
    ahead_of_rival: bool | None = None


class ScenarioOutcome(Contract):
    """Result of rolling one candidate through one sampled rival scenario."""

    scenario_id: str = Field(min_length=1)
    weight: float = Field(ge=0.0)
    checkpoints: tuple[CheckpointOutcome, ...] = ()
    utility: float = Field(description="Dimensionless objective value; not seconds.")
    elapsed_time_s: float | None = None
    final_energy_j: float | None = None
    terminal_value: float | None = Field(
        default=None, description="Continuation value beyond the explicit horizon."
    )
    terminal_value_source: str | None = Field(
        default=None, description="'analytic' or the learned bundle id that supplied it."
    )
    feasible: bool = True


class OutcomeRange(Contract):
    """The spread of one predicted quantity across the scenario ensemble.

    A point prediction from a weighted ensemble hides the thing an engineer
    needs: whether the scenarios agreed. Every field is an ``IntervalValue`` so
    the interval carries its own ``kind`` and coverage, and a quantity no
    scenario produced is ``None`` rather than a zero-width interval at zero.

    ``kind`` on each interval is ``physical_bounds``: these are the minimum and
    maximum actually observed across the sampled scenarios, not a fitted
    quantile and not a confidence interval. Labelling an observed spread as a
    quantile would overstate what an ensemble of a handful of scenarios can say.
    """

    checkpoint_id: str = Field(min_length=1)
    progress_m: float = Field(ge=0.0)
    scenario_count: int = Field(ge=0, description="Scenarios that reached this checkpoint.")
    weight_covered: float = Field(
        ge=0.0, le=1.0, description="Ensemble weight that reached it; below 1.0 means some did not."
    )
    elapsed_time_s: IntervalValue | None = None
    gap_to_reference_s: IntervalValue | None = None
    own_energy_j: IntervalValue | None = None
    ahead_of_rival_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Weighted share of scenarios that finished ahead."
    )

    @model_validator(mode="after")
    def _coverage_needs_scenarios(self) -> OutcomeRange:
        if self.scenario_count == 0 and self.weight_covered > 0.0:
            raise ValueError("weight cannot be covered by zero scenarios")
        if self.scenario_count == 0 and any(
            field is not None for field in (self.elapsed_time_s, self.gap_to_reference_s, self.own_energy_j)
        ):
            raise ValueError("a checkpoint no scenario reached cannot carry a predicted range")
        return self


class LearnedContribution(Contract):
    """What a learned model contributed to one decision, and whether it was used.

    Published so an engineer can tell a baseline decision from a learned one
    without inferring it from reason codes. ``disagreement`` is carried even
    when ``in_support`` is false: a refusal caused by ensemble spread is more
    informative with the number attached.
    """

    enabled: bool = Field(description="False whenever the validated baseline answered instead.")
    bundle_id: str | None = None
    weights_hash: str | None = None
    in_support: bool = False
    support_reason: str | None = Field(
        default=None, description="Why the learned contribution was or was not in support."
    )
    continuation_value: float | None = Field(
        default=None, description="Dimensionless continuation return; never seconds."
    )
    disagreement: float | None = Field(default=None, ge=0.0)
    member_count: int | None = Field(default=None, ge=0)
    calibrator_id: str | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.UNAVAILABLE
    baseline_identity: str = Field(
        min_length=1, description="The validated path that answers when this is disabled."
    )
    reason_codes: tuple[ReasonCode, ...] = ()

    @model_validator(mode="after")
    def _disabled_carries_no_value(self) -> LearnedContribution:
        if not self.enabled and self.continuation_value is not None:
            raise ValueError(
                "a disabled learned contribution cannot publish a continuation value; the "
                "baseline answered and its result must not carry a learned number"
            )
        if self.enabled and self.bundle_id is None:
            raise ValueError("an enabled learned contribution must name the bundle that produced it")
        if self.continuation_value is not None and not self.in_support:
            raise ValueError("a continuation value cannot be published from outside support")
        return self


class ObjectiveTerms(Contract):
    """Decomposed objective so no term can hide inside a single score."""

    objective_version: str = Field(min_length=1)
    expected_utility: float
    tail_alpha: float = Field(gt=0.0, lt=1.0)
    cvar_loss: float
    lambda_tail: float = Field(ge=0.0)
    switch_count: int = Field(ge=0)
    lambda_switch: float = Field(ge=0.0)
    disagreement_penalty: float = Field(default=0.0, ge=0.0)
    generation_score: float | None = Field(
        default=None, description="Score used to generate the candidate, before learned reranking."
    )
    final_score: float

    @property
    def learned_reranking_applied(self) -> bool:
        return self.generation_score is not None and self.generation_score != self.final_score


class CandidatePlan(VersionedContract):
    """One legal, checked candidate with the full evidence needed to audit it."""

    id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    intention: ActionCode
    profile_segments: tuple[ProfileSegment, ...] = Field(min_length=1)
    scenario_outcomes: tuple[ScenarioOutcome, ...] = ()
    terminal_target_energy_j: float | None = Field(default=None, ge=0.0)
    objective: ObjectiveTerms
    constraint_result: ConstraintResult
    model_version: str | None = None
    objective_version: str = Field(min_length=1)
    solver_status: str | None = None
    solve_duration_ms: float | None = Field(default=None, ge=0.0)
    reason_codes: tuple[ReasonCode, ...] = ()
    probabilities: tuple[ProbabilityStatement, ...] = ()

    @model_validator(mode="after")
    def _segments_are_contiguous(self) -> CandidatePlan:
        for previous, following in zip(self.profile_segments, self.profile_segments[1:], strict=False):
            if abs(following.start_progress_m - previous.end_progress_m) > 1e-6:
                raise ValueError("profile segments must be contiguous in progress")
        if self.objective.objective_version != self.objective_version:
            raise ValueError("objective version mismatch between plan and its objective terms")
        return self

    @property
    def total_requested_energy_j(self) -> float:
        return sum(s.requested_budget_j for s in self.profile_segments)


class PlanningResult(VersionedContract):
    """Everything one planner invocation produced, including why it failed."""

    session_id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    status: PlanningStatus
    created_at_s: float = Field(ge=0.0)
    deadline_s: float = Field(gt=0.0)
    duration_ms: float = Field(ge=0.0)
    accepted: tuple[CandidatePlan, ...] = ()
    rejected: tuple[CandidatePlan, ...] = ()
    selected_plan_id: str | None = None
    reason_codes: tuple[ReasonCode, ...] = ()
    scenario_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    learned_contribution_enabled: bool = False
    baseline_identity: str = Field(
        default="mpc_baseline",
        min_length=1,
        description="Which validated path produced the fallback if learning is disabled.",
    )
    detail: str | None = None

    @model_validator(mode="after")
    def _status_matches_content(self) -> PlanningResult:
        if self.status is PlanningStatus.OK and not self.accepted:
            raise ValueError("status=ok requires at least one accepted candidate")
        if self.status is not PlanningStatus.OK and self.selected_plan_id is not None:
            raise ValueError("a failed planning result cannot name a selected plan")
        if self.selected_plan_id is not None and self.selected_plan_id not in {c.id for c in self.accepted}:
            raise ValueError("selected plan id is not among accepted candidates")
        return self


class Trigger(Contract):
    """When the driver should begin, expressed in checkpoints not wall-clock text."""

    kind: str = Field(pattern="^(immediate|checkpoint|gap_threshold|lap)$")
    checkpoint_id: str | None = None
    progress_m: float | None = Field(default=None, ge=0.0)
    gap_threshold_s: float | None = None
    description: str = Field(min_length=1)


class RecommendationAlternative(Contract):
    """One candidate the planner considered but did not recommend.

    Published so an engineer can see what was rejected and why, rather than
    being shown a single instruction with no visible competition. It carries the
    decomposed comparison the objective actually made -- benefit, downside,
    future energy and switching cost as separate fields -- because a single
    ``final_score`` delta cannot be argued with.

    ``constraint_status`` is the *independent checker's* verdict, not the
    planner's self-assessment. A candidate rejected by the checker is a
    different fact from one that lost on score, and collapsing the two would
    hide a rules problem behind a preference.
    """

    plan_id: str = Field(min_length=1)
    action_code: ActionCode
    display_text: str = Field(min_length=1)
    rank: int = Field(ge=1, description="1 is the recommended plan.")
    selected: bool = False
    constraint_status: CheckStatus
    final_score: float | None = Field(
        default=None, description="Dimensionless objective value; never seconds."
    )
    score_delta_vs_selected: float | None = Field(
        default=None,
        description=(
            "This candidate's score minus the selected one's. A plain difference: the sign's "
            "meaning depends on the producing planner's objective direction, so no better/worse "
            "reading is implied."
        ),
    )
    expected_utility: float | None = None
    cvar_loss: float | None = Field(
        default=None, description="Tail loss at the objective's alpha; the downside term."
    )
    terminal_energy_j: float | None = Field(default=None, description="Future energy at the horizon.")
    switch_count: int | None = Field(default=None, ge=0, description="Instruction changes required.")
    switching_penalty: float | None = None
    rejected_reason: str | None = Field(
        default=None, description="Why this candidate is not the recommendation."
    )
    reason_codes: tuple[ReasonCode, ...] = ()

    @model_validator(mode="after")
    def _selection_is_consistent(self) -> RecommendationAlternative:
        if self.selected and self.rank != 1:
            raise ValueError("the selected candidate must be rank 1")
        if self.selected and self.score_delta_vs_selected not in (None, 0.0):
            raise ValueError("the selected candidate cannot differ in score from itself")
        if self.selected and self.constraint_status is not CheckStatus.PASS:
            raise ValueError("a candidate the independent checker did not pass cannot be the selected one")
        return self


class Recommendation(VersionedContract):
    """The published, lifecycle-managed instruction shown to the engineer.

    ``status`` transitions are owned by the backend. Selection is a human
    decision record and never actuates anything.
    """

    id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    session_id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    plan_id: str | None = None
    status: RecommendationStatus
    action_code: ActionCode
    display_text: str = Field(min_length=1, description="Compact verb plus end condition.")
    trigger: Trigger
    end_condition: str = Field(min_length=1)
    created_at_s: float = Field(ge=0.0)
    valid_from_s: float = Field(ge=0.0)
    expires_at_s: float = Field(gt=0.0)
    observation_cutoff_s: float = Field(ge=0.0)
    ruleset_hash: str = Field(min_length=1)
    model_hash: str | None = None
    objective_version: str = Field(min_length=1)
    reason_codes: tuple[ReasonCode, ...] = ()
    outcomes: tuple[CheckpointOutcome, ...] = ()
    probabilities: tuple[ProbabilityStatement, ...] = ()
    constraint_result: ConstraintResult
    learned_contribution_enabled: bool = False
    baseline_identity: str = Field(default="mpc_baseline", min_length=1)
    outcome_ranges: tuple[OutcomeRange, ...] = Field(
        default=(), description="Per-checkpoint spread across the scenario ensemble."
    )
    alternatives: tuple[RecommendationAlternative, ...] = Field(
        default=(), description="Candidates considered, ranked, with the selected one at rank 1."
    )
    learned: LearnedContribution | None = Field(
        default=None,
        description="What a learned model contributed. None means none was offered at all.",
    )
    planner_identity: str | None = Field(
        default=None, description="Which planner produced this, not which one was hoped for."
    )
    unavailable_reasons: tuple[str, ...] = Field(
        default=(), description="Plain-language reasons a capability did not contribute."
    )

    @model_validator(mode="after")
    def _time_ordering(self) -> Recommendation:
        if self.expires_at_s <= self.valid_from_s:
            raise ValueError("recommendation expires before it becomes valid")
        if self.created_at_s < self.observation_cutoff_s:
            raise ValueError("recommendation cannot precede its own observation cutoff")
        if self.action_code is not ActionCode.WITHDRAW_ADVICE and self.plan_id is None:
            raise ValueError("an actionable recommendation must reference its plan")
        if self.learned is not None and self.learned.enabled != self.learned_contribution_enabled:
            raise ValueError(
                "learned.enabled disagrees with learned_contribution_enabled; one of the two "
                "would misreport whether a model contributed"
            )
        if self.alternatives:
            ranks = [alternative.rank for alternative in self.alternatives]
            if len(set(ranks)) != len(ranks):
                raise ValueError("two alternatives claim the same rank")
            selected = [a for a in self.alternatives if a.selected]
            if len(selected) > 1:
                raise ValueError("more than one alternative claims to be the selected plan")
            if selected and self.plan_id is not None and selected[0].plan_id != self.plan_id:
                raise ValueError("the selected alternative is not the recommendation's own plan")
        return self

    def is_expired_at(self, session_time_s: float) -> bool:
        return session_time_s >= self.expires_at_s

    def is_actionable_at(self, session_time_s: float) -> bool:
        return (
            self.status in (RecommendationStatus.PROPOSED, RecommendationStatus.SELECTED)
            and self.valid_from_s <= session_time_s < self.expires_at_s
        )


__all__ = [
    "CandidatePlan",
    "CheckpointOutcome",
    "LearnedContribution",
    "ObjectiveTerms",
    "OutcomeRange",
    "PlanningResult",
    "ProfileSegment",
    "Recommendation",
    "RecommendationAlternative",
    "ScenarioOutcome",
    "Trigger",
]
