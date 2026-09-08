"""Experiment job creation, status and cancellation.

``POST /experiments`` returns **202** with a trackable job id: the job is queued,
not run, and HTTP success means the queue insertion *plus* an accepted state
transition, never that results exist.

Cancellation is cooperative. This route records the terminal ``cancelled``
status; the batch worker observes it between rollouts and stops there. Any work
already finished is preserved and **labelled incomplete** — a cancelled job with
progress is stored with ``partial_results=True``, which the contract itself
enforces, so partial output can never be aggregated as if it were a complete run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import (
    SCHEMA_VERSION,
    ErrorCode,
    ExperimentJob as ExperimentJobContract,
    ExperimentManifest,
    JobStatus,
)
from afterlap_contracts.requests import (
    CancelExperimentRequest,
    CreateExperimentRequest,
    CreateExperimentResponse,
    ExperimentStatusResponse,
)

from ..db import LifecycleError
from ..db.models import ExperimentJob, Manifest, SnapshotRow

if TYPE_CHECKING:
    from ..deps import CommandDbSession, DbSession, IdempotencyKey, OperatorId

router = APIRouter()

METRICS_VERSION = "metrics-v1"


def _as_contract(row: ExperimentJob) -> ExperimentJobContract:
    return ExperimentJobContract(
        schema_version=SCHEMA_VERSION,
        id=row.id,
        manifest_hash=row.manifest_hash,
        status=JobStatus(row.status),
        progress=row.progress,
        created_at=row.created_at or datetime.now(UTC),
        started_at=row.started_at,
        finished_at=row.finished_at,
        report_hash=row.report_hash,
        failure=row.failure,
        partial_results=row.partial_results,
    )


def _job(db: OrmSession, job_id: str) -> ExperimentJob:
    row = db.get(ExperimentJob, job_id)
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"experiment job {job_id} does not exist")
    return row


@router.post("/experiments", response_model=CreateExperimentResponse, status_code=202)
async def create_experiment(
    request: Request,
    payload: CreateExperimentRequest,
    db: CommandDbSession,
    operator_id: OperatorId,
    idempotency_key: IdempotencyKey,
) -> CreateExperimentResponse:
    snapshot = db.get(SnapshotRow, payload.snapshot_id)
    if snapshot is None:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"snapshot {payload.snapshot_id} does not exist; an experiment cannot branch from it",
            snapshot_id=payload.snapshot_id,
        )

    treatment_ids = tuple(t.treatment_id for t in payload.treatments)
    if len(set(treatment_ids)) != len(treatment_ids):
        raise LifecycleError(
            ErrorCode.VALIDATION_FAILED, "treatment ids must be unique within one experiment"
        )

    manifest = ExperimentManifest(
        schema_version=SCHEMA_VERSION,
        id=f"exp-{uuid.uuid4().hex[:16]}",
        snapshot_hash=snapshot.snapshot_hash,
        treatment_ids=treatment_ids,
        disturbance_seed_ids=payload.seeds,
        evaluator_version=payload.evaluator_version,
        metrics_version=METRICS_VERSION,
        evaluation_horizon_s=payload.evaluation_horizon_s,
        created_at=datetime.now(UTC),
    )
    manifest_hash = manifest.content_hash()
    if db.get(Manifest, manifest_hash) is None:
        db.add(
            Manifest(
                hash=manifest_hash,
                kind="experiment",
                schema_version=manifest.schema_version,
                payload=manifest.model_dump(mode="json"),
            )
        )

    row = ExperimentJob(
        id=manifest.id,
        manifest_hash=manifest_hash,
        status=JobStatus.QUEUED.value,
        progress=0.0,
        partial_results=False,
    )
    db.add(row)
    db.flush()
    del request, operator_id, idempotency_key
    return CreateExperimentResponse(job=_as_contract(row))


@router.get("/experiments/{job_id}", response_model=ExperimentStatusResponse)
async def get_experiment(request: Request, job_id: str, db: DbSession) -> ExperimentStatusResponse:
    row = _job(db, job_id)
    report_path: str | None = None
    if row.report_hash is not None:
        reports = getattr(request.app.state, "reports_root", None)
        report_path = None if reports is None else str(reports / f"{row.id}.json")
    return ExperimentStatusResponse(
        job=_as_contract(row), status=JobStatus(row.status), report_path=report_path
    )


@router.get("/experiments", response_model=list[ExperimentStatusResponse])
async def list_experiments(
    db: DbSession,
    status: Annotated[JobStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[ExperimentStatusResponse]:
    statement = select(ExperimentJob).order_by(ExperimentJob.created_at.desc()).limit(limit)
    if status is not None:
        statement = statement.where(ExperimentJob.status == status.value)
    rows = db.execute(statement).scalars().all()
    return [ExperimentStatusResponse(job=_as_contract(row), status=JobStatus(row.status)) for row in rows]


@router.post("/experiments/{job_id}/cancel", response_model=ExperimentStatusResponse)
async def cancel_experiment(
    job_id: str,
    payload: CancelExperimentRequest,
    db: CommandDbSession,
    operator_id: OperatorId,
    idempotency_key: IdempotencyKey,
) -> ExperimentStatusResponse:
    row = _job(db, job_id)
    terminal = {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
    if row.status in terminal:
        if row.status != JobStatus.CANCELLED.value:
            raise LifecycleError(
                ErrorCode.VALIDATION_FAILED,
                f"experiment job {job_id} is already {row.status} and cannot be cancelled",
                status=row.status,
            )
        return ExperimentStatusResponse(job=_as_contract(row), status=JobStatus.CANCELLED)

    row.status = JobStatus.CANCELLED.value
    row.partial_results = row.progress > 0.0
    row.failure = f"cancelled by {operator_id}: {payload.reason}"
    row.finished_at = datetime.now(UTC)
    db.flush()
    del idempotency_key
    return ExperimentStatusResponse(job=_as_contract(row), status=JobStatus.CANCELLED)


__all__ = ["METRICS_VERSION", "router"]
