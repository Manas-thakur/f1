"""REST request and response bodies for ``/api/v1``.

Mutable routes always carry ``expected_revision`` so a stale UI cannot operate
an old recommendation, and an ``Idempotency-Key`` header so a retry is not a
second human decision.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import DeploymentProfile, JobStatus, OperatorAction, SessionCommandKind, SessionMode
from .lifecycle import ControlLease, ExecutionEvent, OperatorEvent
from .models import ExperimentJob, ModelManifest
from .planning import Recommendation
from .rules import RuleManifest
from .session import SessionManifest, SessionSnapshot, SessionSummary, SnapshotReference


class CreateSessionRequest(Contract):
    mode: SessionMode
    scenario_id: str = Field(min_length=1)
    ruleset_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    model_bundle_id: str | None = None
    label: str | None = None
    track_id: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    event_id: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    conditions_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9-]+$",
        description="A coherent weather/surface/race-control tape; absent means the static environment.",
    )


class CreateSessionResponse(Contract):
    manifest: SessionManifest
    snapshot: SessionSnapshot


class SessionListResponse(Contract):
    sessions: tuple[SessionSummary, ...] = ()
    next_cursor: str | None = None


class AcquireLeaseRequest(Contract):
    operator_id: str = Field(min_length=1)
    expected_lease_revision: int | None = Field(default=None, ge=0)
    ttl_s: float = Field(default=120.0, gt=0.0, le=3600.0)


class AcquireLeaseResponse(Contract):
    lease: ControlLease


class SessionCommandRequest(Contract):
    kind: SessionCommandKind
    expected_revision: int = Field(ge=0)
    operator_id: str = Field(min_length=1)
    step_duration_s: float | None = Field(default=None, gt=0.0)


class SessionCommandResponse(Contract):
    accepted: bool
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0)
    status: str = Field(min_length=1)


class RecommendationActionRequest(Contract):
    action: OperatorAction
    expected_revision: int = Field(ge=0)
    operator_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=500)


class RecommendationActionResponse(Contract):
    recommendation: Recommendation
    operator_event: OperatorEvent


class DriverActionRequest(Contract):
    """Simulator-only. The server rejects this in replay and live_team modes."""

    profile_id: DeploymentProfile
    observed_at_s: float = Field(ge=0.0)
    recommendation_id: str | None = None
    operator_id: str = Field(min_length=1)


class DriverActionResponse(Contract):
    execution: ExecutionEvent
    recommendation: Recommendation | None = None


class CreateSnapshotRequest(Contract):
    label: str | None = Field(default=None, max_length=120)


class CreateSnapshotResponse(Contract):
    snapshot: SnapshotReference


class TreatmentSpec(Contract):
    """One branch of a paired experiment."""

    treatment_id: str = Field(min_length=1)
    controller: str = Field(min_length=1)
    model_bundle_id: str | None = None
    description: str | None = None


class CreateExperimentRequest(Contract):
    snapshot_id: str = Field(min_length=1)
    treatments: tuple[TreatmentSpec, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    evaluation_horizon_s: float = Field(gt=0.0)


class CreateExperimentResponse(Contract):
    job: ExperimentJob


class CancelExperimentRequest(Contract):
    reason: str = Field(min_length=1, max_length=500)


class ExperimentStatusResponse(Contract):
    job: ExperimentJob
    status: JobStatus
    report_path: str | None = Field(
        default=None,
        description=(
            "Where the report sits inside the deployment's artefact tree, relative to it "
            "(artifacts/reports/<id>.json). Never an absolute path."
        ),
    )


class ModelListResponse(Contract):
    models: tuple[ModelManifest, ...] = ()


class RulesetResponse(Contract):
    manifest: RuleManifest


class CreateExportRequest(Contract):
    session_id: str = Field(min_length=1)
    format: str = Field(pattern="^(json|csv|parquet)$")
    start_session_time_s: float | None = Field(default=None, ge=0.0)
    end_session_time_s: float | None = Field(default=None, ge=0.0)


class ExportJobResponse(Contract):
    export_id: str = Field(min_length=1)
    status: JobStatus
    path: str | None = Field(
        default=None,
        description=(
            "Where the export sits inside the deployment's artefact tree, relative to it "
            "(artifacts/exports/<id>.<format>). Never an absolute path: that describes the "
            "machine rather than the artefact."
        ),
    )
    hashes: dict[str, str] = Field(default_factory=dict)
    synthetic: bool = True
    created_at: datetime


class HealthResponse(Contract):
    """Liveness proves the loop runs. Readiness proves capabilities exist."""

    status: str = Field(pattern="^(live|ready|not_ready)$")
    detail: dict[str, str] = Field(default_factory=dict)


class DecisionEvidenceResponse(Contract):
    """Full audit record for one published decision."""

    recommendation: Recommendation
    estimate_revision: int = Field(ge=0)
    operator_events: tuple[OperatorEvent, ...] = ()
    execution_events: tuple[ExecutionEvent, ...] = ()


__all__ = [
    "AcquireLeaseRequest",
    "AcquireLeaseResponse",
    "CancelExperimentRequest",
    "CreateExperimentRequest",
    "CreateExperimentResponse",
    "CreateExportRequest",
    "CreateSessionRequest",
    "CreateSessionResponse",
    "CreateSnapshotRequest",
    "CreateSnapshotResponse",
    "DecisionEvidenceResponse",
    "DriverActionRequest",
    "DriverActionResponse",
    "ExperimentStatusResponse",
    "ExportJobResponse",
    "HealthResponse",
    "ModelListResponse",
    "RecommendationActionRequest",
    "RecommendationActionResponse",
    "RulesetResponse",
    "SessionCommandRequest",
    "SessionCommandResponse",
    "SessionListResponse",
    "TreatmentSpec",
]
