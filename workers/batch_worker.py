"""Batch experiment worker.

Claims jobs through the coordinator's existing ``claim_experiment_job`` lease,
heartbeats ownership, writes artefacts to a **staging** directory and finalises
the manifest and report **atomically**.

The guarantees the specification asks for, and where each lives:

* *"two workers must not publish separate successful reports for one job id"* —
  the claim uses ``FOR UPDATE SKIP LOCKED`` where the engine supports it, and
  :meth:`BatchWorker.finalise` refuses to write a report for a job whose
  ``worker_lease`` is no longer this worker's. A worker that lost its lease
  discards its own work rather than racing the new owner.
* *"a failed lease leaves restartable checkpoints"* — progress is written to the
  staging directory as it is produced, so a restart resumes from the last
  checkpoint instead of from zero.
* *"cancellation is cooperative between rollouts"* — the runner is handed a
  :class:`CancellationToken` and is expected to check it between rollouts. The
  worker never kills a rollout mid-flight.
* *"terminal status records partial output scope"* — a cancelled job with any
  progress is stored with ``partial_results=True`` and the report is labelled
  incomplete, naming exactly which rollouts finished.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from afterlap_api.db.engine import transaction
from afterlap_api.db.models import ExperimentJob
from afterlap_api.db.repository import claim_experiment_job
from afterlap_contracts import JobStatus
from afterlap_core.paths import atomic_write_json, sha256_json

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session as OrmSession, sessionmaker

logger = logging.getLogger("afterlap.workers.batch")

DEFAULT_LEASE_S = 120.0
INCOMPLETE_LABEL = "incomplete"


class LeaseLost(RuntimeError):
    """Another worker owns this job now; this worker's output must be discarded."""


@dataclass(slots=True)
class CancellationToken:
    """Cooperative cancellation. Checked between rollouts, never mid-rollout."""

    cancelled: bool = False
    reason: str | None = None

    def cancel(self, reason: str) -> None:
        self.cancelled = True
        self.reason = reason

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled(self.reason or "cancelled")


class JobCancelled(RuntimeError):
    """The runner observed a cancellation between rollouts."""


@dataclass(slots=True)
class JobContext:
    """What a runner is given, and where it writes its restartable checkpoints."""

    job_id: str
    manifest_hash: str
    staging: Path
    token: CancellationToken
    heartbeat: Callable[[], bool]
    completed: list[str] = field(default_factory=list)

    def checkpoint(self, name: str, payload: dict[str, Any]) -> Path:
        """Record one completed unit of work so a restart can resume from it."""
        path = self.staging / f"checkpoint-{name}.json"
        atomic_write_json(path, payload)
        self.completed.append(name)
        return path

    def existing_checkpoints(self) -> tuple[str, ...]:
        return tuple(
            sorted(p.stem.removeprefix("checkpoint-") for p in self.staging.glob("checkpoint-*.json"))
        )


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Terminal state of one job, including the scope of any partial output."""

    job_id: str
    status: JobStatus
    report_hash: str | None = None
    report_path: Path | None = None
    partial_results: bool = False
    completed_units: tuple[str, ...] = ()
    failure: str | None = None


class BatchWorker:
    """One batch worker. Owns nothing beyond the job it has claimed."""

    def __init__(
        self,
        factory: sessionmaker[OrmSession],
        *,
        worker_id: str | None = None,
        staging_root: Path,
        reports_root: Path,
        lease_seconds: float = DEFAULT_LEASE_S,
    ) -> None:
        self._factory = factory
        self.worker_id = worker_id or f"batch-{uuid.uuid4().hex[:12]}"
        self.staging_root = Path(staging_root)
        self.reports_root = Path(reports_root)
        self.lease_seconds = lease_seconds
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.reports_root.mkdir(parents=True, exist_ok=True)

    def claim(self) -> tuple[str, str] | None:
        """Claim one queued job. Returns ``(job_id, manifest_hash)`` or ``None``."""
        with transaction(self._factory) as db:
            job = claim_experiment_job(db, worker_id=self.worker_id, lease_seconds=self.lease_seconds)
            if job is None:
                return None
            return job.id, job.manifest_hash

    def heartbeat(self, job_id: str) -> bool:
        """Extend the lease. Returns False once another worker owns the job."""
        with transaction(self._factory) as db:
            job = db.get(ExperimentJob, job_id)
            if job is None or job.worker_lease != self.worker_id:
                return False
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
            return True

    def _require_lease(self, db: OrmSession, job_id: str) -> ExperimentJob:
        job = db.get(ExperimentJob, job_id)
        if job is None:
            raise LeaseLost(f"job {job_id} no longer exists")
        if job.worker_lease != self.worker_id:
            raise LeaseLost(
                f"job {job_id} is now leased to {job.worker_lease!r}; this worker will not publish a "
                "second report for it"
            )
        return job

    def staging_for(self, job_id: str) -> Path:
        path = self.staging_root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(
        self,
        job_id: str,
        manifest_hash: str,
        runner: Callable[[JobContext], dict[str, Any]],
        *,
        token: CancellationToken | None = None,
    ) -> JobOutcome:
        """Run one claimed job to a terminal state."""
        context = JobContext(
            job_id=job_id,
            manifest_hash=manifest_hash,
            staging=self.staging_for(job_id),
            token=token or CancellationToken(),
            heartbeat=lambda: self.heartbeat(job_id),
        )
        resumed = context.existing_checkpoints()
        if resumed:
            logger.info("job %s resuming from checkpoints %s", job_id, list(resumed))

        try:
            report = runner(context)
        except JobCancelled as cancelled:
            return self.finalise_cancelled(context, reason=str(cancelled))
        except LeaseLost:
            raise
        except Exception as exc:
            logger.exception("job %s failed", job_id)
            return self.finalise_failed(job_id, f"{type(exc).__name__}: {exc}", context)
        return self.finalise(context, report)

    def finalise(self, context: JobContext, report: dict[str, Any]) -> JobOutcome:
        """Atomically publish the report and mark the job completed."""
        body = {
            **report,
            "job_id": context.job_id,
            "manifest_hash": context.manifest_hash,
            "worker_id": self.worker_id,
            "completed_units": list(context.completed or context.existing_checkpoints()),
            "partial_results": False,
            "synthetic": True,
        }
        digest = sha256_json(body)
        with transaction(self._factory) as db:
            job = self._require_lease(db, context.job_id)
            path = self._publish(context, body, digest)
            job.status = JobStatus.COMPLETED.value
            job.report_hash = digest
            job.progress = 1.0
            job.partial_results = False
            job.finished_at = datetime.now(UTC)
            job.failure = None
        self._clear_staging(context)
        return JobOutcome(
            job_id=context.job_id,
            status=JobStatus.COMPLETED,
            report_hash=digest,
            report_path=path,
            completed_units=tuple(body["completed_units"]),
        )

    def finalise_cancelled(self, context: JobContext, *, reason: str) -> JobOutcome:
        """Cancellation preserves partial results, labelled incomplete."""
        completed = tuple(context.completed or context.existing_checkpoints())
        body = {
            "job_id": context.job_id,
            "manifest_hash": context.manifest_hash,
            "worker_id": self.worker_id,
            "status": JobStatus.CANCELLED.value,
            "label": INCOMPLETE_LABEL,
            "partial_results": bool(completed),
            "completed_units": list(completed),
            "reason": reason,
            "synthetic": True,
            "notice": (
                "Cancelled job. These results cover only the units listed in completed_units and "
                "must not be aggregated with a complete run."
            ),
        }
        digest = sha256_json(body)
        with transaction(self._factory) as db:
            job = self._require_lease(db, context.job_id)
            path = self._publish(context, body, digest)
            job.status = JobStatus.CANCELLED.value
            job.report_hash = digest
            job.partial_results = bool(completed)
            job.progress = job.progress if completed else 0.0
            job.failure = reason
            job.finished_at = datetime.now(UTC)
        return JobOutcome(
            job_id=context.job_id,
            status=JobStatus.CANCELLED,
            report_hash=digest,
            report_path=path,
            partial_results=bool(completed),
            completed_units=completed,
            failure=reason,
        )

    def finalise_failed(self, job_id: str, failure: str, context: JobContext | None = None) -> JobOutcome:
        completed = tuple(context.completed) if context is not None else ()
        with transaction(self._factory) as db:
            job = self._require_lease(db, job_id)
            job.status = JobStatus.FAILED.value
            job.failure = failure
            job.partial_results = bool(completed)
            job.finished_at = datetime.now(UTC)
        return JobOutcome(
            job_id=job_id,
            status=JobStatus.FAILED,
            partial_results=bool(completed),
            completed_units=completed,
            failure=failure,
        )

    def _publish(self, context: JobContext, body: dict[str, Any], digest: str) -> Path:
        """Stage the report, then rename it into place. Readers see it or nothing."""
        staged = context.staging / "report.json"
        atomic_write_json(staged, body)
        target = self.reports_root / f"{context.job_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)
        (self.reports_root / f"{context.job_id}.hash").write_text(digest, encoding="utf-8")
        return target

    def _clear_staging(self, context: JobContext) -> None:
        shutil.rmtree(context.staging, ignore_errors=True)


def read_report(reports_root: Path, job_id: str) -> dict[str, Any] | None:
    path = Path(reports_root) / f"{job_id}.json"
    if not path.exists():
        return None
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def run_forever(  # pragma: no cover - the polling loop is the process entry point
    factory: sessionmaker[OrmSession],
    runner: Callable[[JobContext], dict[str, Any]],
    *,
    staging_root: Path,
    reports_root: Path,
    poll_interval_s: float = 1.0,
    max_jobs: int | None = None,
) -> Sequence[JobOutcome]:
    """Claim and run jobs until ``max_jobs`` is reached or the process is stopped."""
    import time

    worker = BatchWorker(factory, staging_root=staging_root, reports_root=reports_root)
    outcomes: list[JobOutcome] = []
    while max_jobs is None or len(outcomes) < max_jobs:
        claimed = worker.claim()
        if claimed is None:
            time.sleep(poll_interval_s)
            continue
        job_id, manifest_hash = claimed
        outcomes.append(worker.run(job_id, manifest_hash, runner))
    return outcomes


__all__ = [
    "DEFAULT_LEASE_S",
    "INCOMPLETE_LABEL",
    "BatchWorker",
    "CancellationToken",
    "JobCancelled",
    "JobContext",
    "JobOutcome",
    "LeaseLost",
    "read_report",
    "run_forever",
]
