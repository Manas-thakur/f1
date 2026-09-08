"""Operator authority, driver execution and realised-outcome records.

Selection, communication and execution are three separate events. Nothing here
lets a human decision imply that the car actually did something.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import (
    DeploymentProfile,
    ExecutionMatch,
    OperatorAction,
    Provenance,
    RecommendationStatus,
    SessionCommandKind,
)


class ControlLease(Contract):
    """Single-operator control lease. A second operator may observe only."""

    session_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    granted_at_s: float = Field(ge=0.0)
    expires_at_s: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _positive_window(self) -> ControlLease:
        if self.expires_at_s <= self.granted_at_s:
            raise ValueError("lease expires before it is granted")
        return self

    def is_held_at(self, session_time_s: float, operator_id: str) -> bool:
        return self.operator_id == operator_id and session_time_s < self.expires_at_s


class OperatorEvent(VersionedContract):
    """An immutable record of a human decision.

    ``idempotency_key`` plus body hash makes a repeated submission return the
    original result instead of creating a second decision.
    """

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    recommendation_id: str | None = None
    expected_revision: int = Field(ge=0)
    operator_id: str = Field(min_length=1)
    action: OperatorAction
    reason: str | None = None
    session_time_s: float = Field(ge=0.0)
    sequence: int = Field(ge=0)
    resulting_status: RecommendationStatus | None = None


class SessionCommand(VersionedContract):
    """A run-control command against the session runtime."""

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    kind: SessionCommandKind
    expected_revision: int = Field(ge=0)
    operator_id: str = Field(min_length=1)
    session_time_s: float = Field(ge=0.0)
    step_duration_s: float | None = Field(default=None, gt=0.0)


class ExecutionEvent(VersionedContract):
    """Observed driver action.

    ``recommendation_id`` may be ``None``: an unsolicited driver action is
    recorded without being forced onto a recommendation.
    """

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    recommendation_id: str | None = None
    source: Provenance = Field(
        description="'simulated' for a simulator driver input, 'measured' for observed telemetry."
    )
    observed_profile_id: DeploymentProfile
    start_time_s: float = Field(ge=0.0)
    end_time_s: float | None = None
    evidence_event_ids: tuple[str, ...] = ()
    match_status: ExecutionMatch
    sequence: int = Field(ge=0)
    delay_from_communication_s: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _unsolicited_has_no_recommendation(self) -> ExecutionEvent:
        if self.match_status is ExecutionMatch.UNSOLICITED and self.recommendation_id is not None:
            raise ValueError("an unsolicited execution must not be attributed to a recommendation")
        if self.match_status is not ExecutionMatch.UNSOLICITED and self.recommendation_id is None:
            raise ValueError("a matched execution must reference the recommendation it responded to")
        if self.end_time_s is not None and self.end_time_s < self.start_time_s:
            raise ValueError("execution ends before it starts")
        return self


class LifecycleTransition(VersionedContract):
    """One audited status change of a recommendation."""

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    recommendation_id: str = Field(min_length=1)
    from_status: RecommendationStatus
    to_status: RecommendationStatus
    session_time_s: float = Field(ge=0.0)
    sequence: int = Field(ge=0)
    evidence_event_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _real_transition(self) -> LifecycleTransition:
        if self.from_status is self.to_status:
            raise ValueError("a lifecycle transition must change status")
        return self


class CheckpointDefinition(Contract):
    """A named evaluation point, frozen before results are produced."""

    checkpoint_id: str = Field(min_length=1)
    progress_m: float = Field(ge=0.0)
    description: str | None = None


class OutcomeRecord(VersionedContract):
    """Realised state at an evaluation checkpoint.

    Retains what actually happened, alongside the decision that preceded it.
    """

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_id: str | None = None
    checkpoint: CheckpointDefinition
    evaluation_horizon_s: float = Field(gt=0.0)
    event_observed: bool
    elapsed_time_s: float | None = None
    energy_j: float | None = None
    position: int | None = Field(default=None, ge=1)
    gap_to_reference_s: float | None = None
    provenance: Provenance
    incomplete_reason: str | None = Field(
        default=None, description="Set when the horizon was truncated; the record is not comparable."
    )

    @model_validator(mode="after")
    def _incomplete_is_explicit(self) -> OutcomeRecord:
        if not self.event_observed and self.incomplete_reason is None and self.elapsed_time_s is None:
            raise ValueError("an unobserved outcome must state why it is incomplete")
        return self


__all__ = [
    "CheckpointDefinition",
    "ControlLease",
    "ExecutionEvent",
    "LifecycleTransition",
    "OperatorEvent",
    "OutcomeRecord",
    "SessionCommand",
]
