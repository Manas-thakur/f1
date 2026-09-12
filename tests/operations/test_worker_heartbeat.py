"""A background worker that stops working must be distinguishable from an idle one.

The batch service runs no HTTP server, so before this its container
healthcheck was disabled and a wedged worker looked exactly like one with
nothing to do. These drills run the real worker loop, read the heartbeat it
actually wrote, and check the three states the API distinguishes.

Nothing is simulated: `scripts/batch_worker_main.py --once` is the same entry
point `infra/docker-compose.yml` runs, and the staleness case is produced by
letting a real heartbeat age past its expectation rather than by asserting a
status into existence.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from afterlap_api.client import TestClient
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.worker_health import (
    BATCH_WORKER,
    WorkerHeartbeat,
    heartbeat_path,
    worker_status,
)

if TYPE_CHECKING:
    from pathlib import Path


def _app(tmp_path: Path) -> object:
    return create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )


def test_no_worker_is_absent_and_says_so_rather_than_reporting_health(tmp_path: Path):
    """An install with no batch worker is not a failing install."""
    status = worker_status(tmp_path / "artifacts")
    print(f"\nno worker: {status.status}: {status.detail}")
    assert status.status == "absent"
    assert status.age_s is None
    assert status.heartbeat is None
    assert "not a fault" in status.detail


def test_a_real_worker_loop_writes_a_heartbeat_reporting_what_it_did(tmp_path: Path, monkeypatch):
    """Run the shipped entry point once and read what it left behind."""
    import batch_worker_main

    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "AFTERLAP_DATABASE_URL", f"sqlite+pysqlite:///{(tmp_path / 'batch.sqlite3').as_posix()}"
    )

    from afterlap_api.db.engine import create_all, create_db_engine

    engine = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'batch.sqlite3').as_posix()}")
    create_all(engine)
    engine.dispose()

    exit_code = batch_worker_main.main(["--once", "--wait-for-database", "0"])
    assert exit_code == 0

    written = heartbeat_path(tmp_path / "artifacts")
    assert written.is_file(), "the worker loop wrote no heartbeat at all"
    document = json.loads(written.read_text(encoding="utf-8"))
    print(f"\nheartbeat: {document}")
    assert document["kind"] == BATCH_WORKER
    assert document["state"] == "idle"
    assert document["pid"] > 0
    assert document["worker_id"]

    status = worker_status(tmp_path / "artifacts")
    assert status.status == "live", status.detail
    assert status.age_s is not None and status.age_s < 30.0
    assert batch_worker_main._healthcheck() == 0


def test_a_running_job_refreshes_its_heartbeat_until_it_finishes():
    """A healthy long job must remain live past more than one heartbeat interval."""
    import batch_worker_main

    observed = threading.Event()
    writes = 0

    def write() -> None:
        nonlocal writes
        writes += 1
        if writes >= 3:
            observed.set()

    with batch_worker_main.repeating_heartbeat(write, interval_s=0.01):
        assert observed.wait(timeout=1.0), "the running heartbeat stopped after the initial write"

    completed_writes = writes
    assert completed_writes >= 3
    observed.clear()
    assert not observed.wait(timeout=0.03)
    assert writes == completed_writes


def test_a_heartbeat_that_stops_advancing_is_stale_not_idle(tmp_path: Path):
    """The age is the signal: a worker that stopped writing is wedged."""
    root = tmp_path / "artifacts"
    stale = WorkerHeartbeat(
        kind=BATCH_WORKER,
        worker_id="batch-drill",
        pid=4242,
        state="idle",
        written_at=datetime.now(UTC) - timedelta(seconds=120.0),
    )
    stale.write(root)

    status = worker_status(root, max_age_s=30.0)
    print(f"\n{status.status}: {status.detail}")
    assert status.status == "stale"
    assert status.age_s is not None and status.age_s > 30.0
    assert status.heartbeat is not None
    assert status.heartbeat["state"] == "idle", (
        "the last reported state must survive into the stale report; 'idle 2 minutes ago' and "
        "'running a job 2 minutes ago' need different operator actions"
    )


def test_a_malformed_heartbeat_reads_as_absent_rather_than_as_health(tmp_path: Path):
    root = tmp_path / "artifacts"
    target = heartbeat_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json", encoding="utf-8")

    assert WorkerHeartbeat.read(root) is None
    assert worker_status(root).status == "absent"


def test_the_api_reports_worker_health_without_making_itself_unready(tmp_path: Path):
    """A dead batch worker must not take the control plane down with it.

    `ARCHITECTURE.md` stops experiment jobs first when resources run short. A
    readiness endpoint that failed because a batch worker died would invert
    that: the decision system would go away to protect the queue.
    """
    app = _app(tmp_path)
    with TestClient(app) as client:
        absent = client.get("/api/v1/health/workers")
        assert absent.status_code == 200, absent.text
        assert [w["status"] for w in absent.json()["workers"]] == ["absent"]
        assert client.get("/api/v1/health/ready").json()["detail"]["batch_worker"] == "absent"

        WorkerHeartbeat(
            kind=BATCH_WORKER,
            worker_id="batch-drill",
            pid=99,
            state="running",
            written_at=datetime.now(UTC) - timedelta(seconds=600.0),
            current_job_id="exp-stuck",
        ).write(tmp_path / "artifacts")

        body = client.get("/api/v1/health/workers").json()["workers"][0]
        print(f"\nwedged worker: {body['status']}: {body['detail']}")
        assert body["status"] == "stale"
        assert body["heartbeat"]["current_job_id"] == "exp-stuck"

        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 200, (
            f"a stale batch worker made the control plane unready ({ready.json()})"
        )
        assert ready.json()["detail"]["batch_worker"] == "stale"


def test_worker_uses_the_same_configured_artifact_root_as_the_api(tmp_path: Path, monkeypatch):
    import batch_worker_main
    from afterlap_api.db.engine import create_all, create_db_engine

    storage = tmp_path / "isolated-storage"
    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    monkeypatch.setenv("AFTERLAP_ARTIFACT_ROOT", str(storage))
    url = f"sqlite+pysqlite:///{(tmp_path / 'worker.sqlite3').as_posix()}"
    monkeypatch.setenv("AFTERLAP_DATABASE_URL", url)
    engine = create_db_engine(url)
    create_all(engine)
    engine.dispose()
    assert batch_worker_main.main(["--once", "--wait-for-database", "0"]) == 0
    assert heartbeat_path(storage / "artifacts").is_file()
    assert not heartbeat_path(tmp_path / "artifacts").exists()
    assert batch_worker_main._healthcheck() == 0
