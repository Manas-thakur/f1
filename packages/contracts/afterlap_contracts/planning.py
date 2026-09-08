"""Planner outputs: candidate plans, scenario outcomes and recommendations.

Physical metrics (position, elapsed time, energy) and the dimensionless utility
are kept as separate fields. A utility number is never reported as seconds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import (
    ActionCode,
    DeploymentProfile,
    PlanningStatus,
    ReasonCode,
    RecommendationStatus,
)

if TYPE_CHECKING:
    from .quantities import ProbabilityStatement
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

    @model_validator(mode="after")
    def _time_ordering(self) -> Recommendation:
        if self.expires_at_s <= self.valid_from_s:
            raise ValueError("recommendation expires before it becomes valid")
        if self.created_at_s < self.observation_cutoff_s:
            raise ValueError("recommendation cannot precede its own observation cutoff")
        if self.action_code is not ActionCode.WITHDRAW_ADVICE and self.plan_id is None:
            raise ValueError("an actionable recommendation must reference its plan")
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
    "ObjectiveTerms",
    "PlanningResult",
    "ProfileSegment",
    "Recommendation",
    "ScenarioOutcome",
    "Trigger",
]
