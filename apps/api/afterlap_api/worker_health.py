"""Whether a background worker is alive, and what it last did.

The batch worker runs no HTTP server, so ``infra/docker-compose.yml`` disables
the image's healthcheck for that service: a container reporting unhealthy for
a reason nobody intends is worse than one reporting nothing. The cost is that
a wedged batch worker looks exactly like an idle one, from inside the stack and
from outside it.

A heartbeat closes that gap without inventing a second control plane. The
worker writes one small document per poll into the artefact root it already
shares with the API; the API serves it, and the worker's own process can read
it back as a container healthcheck. Three states are distinguished, because
they need three different operator actions:

* **absent**: no worker has ever run against this artefact root. Not a fault.
  A single-process development install is expected to look like this.
* **stale**: a heartbeat exists and has stopped advancing. The worker is
  wedged, was killed, or lost the artefact volume.
* **live**: the worker wrote recently, and the document says whether it is
  idle, running a job, or refusing work because the artefact root is full.

A stale batch worker never makes the API unready. ``ARCHITECTURE.md`` puts
experiment jobs first in line to stop when resources run short; a control
plane that refused to answer because a batch worker died would invert that.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BATCH_WORKER = "batch"

DEFAULT_MAX_HEARTBEAT_AGE_S = 30.0
"""A worker polling every two seconds that has been silent this long is wedged."""

HEARTBEAT_SCHEMA = "afterlap.worker.heartbeat/1"


def heartbeat_path(artifacts_root: Path, kind: str = BATCH_WORKER) -> Path:
    return artifacts_root / "workers" / f"{kind}.json"


@dataclass(frozen=True, slots=True)
class WorkerHeartbeat:
    """One worker's last self-report."""

    kind: str
    worker_id: str
    pid: int
    state: str
    written_at: datetime
    detail: str | None = None
    jobs_completed: int = 0
    current_job_id: str | None = None
    quota_verdict: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": HEARTBEAT_SCHEMA,
            "kind": self.kind,
            "worker_id": self.worker_id,
            "pid": self.pid,
            "state": self.state,
            "written_at": self.written_at.isoformat(),
            "detail": self.detail,
            "jobs_completed": self.jobs_completed,
            "current_job_id": self.current_job_id,
            "quota_verdict": self.quota_verdict,
        }

    @classmethod
    def now(
        cls,
        *,
        worker_id: str,
        state: str,
        kind: str = BATCH_WORKER,
        detail: str | None = None,
        jobs_completed: int = 0,
        current_job_id: str | None = None,
        quota_verdict: str | None = None,
    ) -> WorkerHeartbeat:
        return cls(
            kind=kind,
            worker_id=worker_id,
            pid=os.getpid(),
            state=state,
            written_at=datetime.now(UTC),
            detail=detail,
            jobs_completed=jobs_completed,
            current_job_id=current_job_id,
            quota_verdict=quota_verdict,
        )

    def write(self, artifacts_root: Path) -> Path:
        from afterlap_core.paths import atomic_write_text

        target = heartbeat_path(artifacts_root, self.kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        return atomic_write_text(target, json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, artifacts_root: Path, kind: str = BATCH_WORKER) -> WorkerHeartbeat | None:
        """The last heartbeat, or ``None`` when there is not a readable one.

        A malformed document reads as absent rather than as a fault of its own:
        the only honest thing it proves is that no usable report exists.
        """
        path = heartbeat_path(artifacts_root, kind)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return cls(
                kind=str(document["kind"]),
                worker_id=str(document["worker_id"]),
                pid=int(document["pid"]),
                state=str(document["state"]),
                written_at=datetime.fromisoformat(str(document["written_at"])),
                detail=document.get("detail"),
                jobs_completed=int(document.get("jobs_completed", 0)),
                current_job_id=document.get("current_job_id"),
                quota_verdict=document.get("quota_verdict"),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    """What the API reports about one background worker."""

    kind: str
    status: str
    detail: str
    age_s: float | None = None
    heartbeat: dict[str, Any] | None = None

    @property
    def live(self) -> bool:
        return self.status == "live"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
            "age_s": self.age_s,
            "heartbeat": self.heartbeat,
        }


def worker_status(
    artifacts_root: Path,
    kind: str = BATCH_WORKER,
    *,
    max_age_s: float = DEFAULT_MAX_HEARTBEAT_AGE_S,
    now: datetime | None = None,
) -> WorkerStatus:
    """Classify a worker as absent, stale or live from its heartbeat alone."""
    heartbeat = WorkerHeartbeat.read(artifacts_root, kind)
    if heartbeat is None:
        return WorkerStatus(
            kind=kind,
            status="absent",
            detail=(
                f"no {kind} worker has written a heartbeat under this artefact root. A single-process "
                "install has no such worker; this is not a fault and no experiment job will be claimed."
            ),
        )
    age_s = max(0.0, ((now or datetime.now(UTC)) - heartbeat.written_at).total_seconds())
    if age_s > max_age_s:
        return WorkerStatus(
            kind=kind,
            status="stale",
            detail=(
                f"{kind} worker {heartbeat.worker_id} last reported {age_s:.1f} s ago, past the "
                f"{max_age_s:.0f} s expectation; it is wedged, was killed, or lost the artefact volume"
            ),
            age_s=age_s,
            heartbeat=heartbeat.as_dict(),
        )
    return WorkerStatus(
        kind=kind,
        status="live",
        detail=f"{kind} worker {heartbeat.worker_id} is {heartbeat.state}",
        age_s=age_s,
        heartbeat=heartbeat.as_dict(),
    )


__all__ = [
    "BATCH_WORKER",
    "DEFAULT_MAX_HEARTBEAT_AGE_S",
    "HEARTBEAT_SCHEMA",
    "WorkerHeartbeat",
    "WorkerStatus",
    "heartbeat_path",
    "worker_status",
]
