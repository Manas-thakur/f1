"""REST request and response bodies for ``/api/v1``.

Mutable routes always carry ``expected_revision`` so a stale UI cannot operate
an old recommendation, and an ``Idempotency-Key`` header so a retry is not a
second human decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from .base import ContentHash, Contract
from .enums import DeploymentProfile, JobStatus, OperatorAction, SessionCommandKind, SessionMode
from .lifecycle import ControlLease, ExecutionEvent, OperatorEvent
from .models import ExperimentJob, ModelManifest
from .planning import Recommendation
from .rules import RuleManifest
from .session import SessionManifest, SessionSnapshot, SessionSummary, SnapshotReference

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Seed = Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]
Revision = Annotated[int, Field(strict=True, ge=0)]


class RequestContract(Contract):
    model_config = ConfigDict(allow_inf_nan=False)


class CreateSessionRequest(RequestContract):
    mode: SessionMode
    scenario_id: Identifier
    ruleset_id: Identifier
    seed: Seed
    model_bundle_id: Identifier | None = None
    label: str | None = Field(default=None, max_length=120)
    track_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-z0-9-]+$")
    event_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-z0-9-]+$")
    conditions_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-z0-9-]+$",
        description="A coherent weather/surface/race-control tape; absent means the static environment.",
    )


class CreateSessionResponse(Contract):
    manifest: SessionManifest
    snapshot: SessionSnapshot


class SessionListResponse(Contract):
    sessions: tuple[SessionSummary, ...] = ()
    next_cursor: str | None = Field(default=None, min_length=1, max_length=512)


class AcquireLeaseRequest(RequestContract):
    operator_id: Identifier
    expected_lease_revision: Revision | None = None
    ttl_s: float = Field(default=120.0, strict=True, gt=0.0, le=3600.0)


class AcquireLeaseResponse(Contract):
    lease: ControlLease


class SessionCommandRequest(RequestContract):
    kind: SessionCommandKind
    expected_revision: Revision
    operator_id: Identifier
    step_duration_s: float | None = Field(default=None, strict=True, gt=0.0, le=60.0)


class SessionCommandResponse(Contract):
    accepted: bool
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0)
    status: str = Field(min_length=1, max_length=64)


class RecommendationActionRequest(RequestContract):
    action: OperatorAction
    expected_revision: Revision
    operator_id: Identifier
    reason: str | None = Field(default=None, max_length=500)


class RecommendationActionResponse(Contract):
    recommendation: Recommendation
    operator_event: OperatorEvent


class DriverActionRequest(RequestContract):
    """Simulator-only. The server rejects this in replay and live_team modes."""

    profile_id: DeploymentProfile
    observed_at_s: float = Field(strict=True, ge=0.0)
    recommendation_id: Identifier | None = None
    operator_id: Identifier


class DriverActionResponse(Contract):
    execution: ExecutionEvent
    recommendation: Recommendation | None = None


class CreateSnapshotRequest(RequestContract):
    label: str | None = Field(default=None, max_length=120)


class CreateSnapshotResponse(Contract):
    snapshot: SnapshotReference


class TreatmentSpec(RequestContract):
    """One branch of a paired experiment."""

    treatment_id: Identifier
    controller: Identifier
    model_bundle_id: Identifier | None = None
    description: str | None = Field(default=None, max_length=500)


class CreateExperimentRequest(RequestContract):
    snapshot_id: Identifier
    treatments: tuple[TreatmentSpec, ...] = Field(min_length=1, max_length=16)
    seeds: tuple[Seed, ...] = Field(min_length=1, max_length=64)
    evaluator_version: Identifier
    evaluation_horizon_s: float = Field(strict=True, gt=0.0, le=3600.0)

    @model_validator(mode="after")
    def unique_branches(self) -> Self:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("experiment seeds must be unique")
        if len({item.treatment_id for item in self.treatments}) != len(self.treatments):
            raise ValueError("experiment treatment identifiers must be unique")
        return self


class CreateExperimentResponse(Contract):
    job: ExperimentJob


class CancelExperimentRequest(RequestContract):
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


class CreateExportRequest(RequestContract):
    session_id: Identifier
    format: str = Field(pattern="^(json|csv|parquet)$")
    start_session_time_s: float | None = Field(default=None, strict=True, ge=0.0)
    end_session_time_s: float | None = Field(default=None, strict=True, ge=0.0)

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if (
            self.start_session_time_s is not None
            and self.end_session_time_s is not None
            and self.end_session_time_s < self.start_session_time_s
        ):
            raise ValueError("the selected range ends before it starts")
        return self


class ExportJobResponse(Contract):
    export_id: Identifier
    status: JobStatus
    path: str | None = Field(
        default=None,
        description=(
            "Where the export sits inside the deployment's artefact tree, relative to it "
            "(artifacts/exports/<id>.<format>). Never an absolute path: that describes the "
            "machine rather than the artefact."
        ),
    )
    hashes: dict[str, ContentHash] = Field(default_factory=dict)
    synthetic: bool = True
    created_at: datetime


class HealthResponse(Contract):
    """Liveness proves the loop runs. Readiness proves capabilities exist."""

    status: str = Field(pattern="^(live|ready|not_ready)$")
    detail: dict[str, Annotated[str, Field(max_length=512)]] = Field(default_factory=dict)


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
