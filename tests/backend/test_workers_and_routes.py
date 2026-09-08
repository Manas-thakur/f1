"""Batch worker leasing/cancellation and the two new control-plane routes.

The batch worker's guarantees are concurrency guarantees: one job id yields at
most one successful report, a lost lease discards its own work, and cancellation
between rollouts preserves partial output labelled incomplete.

The routes are exercised against a real FastAPI app. ``main.py`` is
coordinator-owned and does not yet include these routers, so the app is
assembled here the way ``handoffs/A08-integration-patch.md`` proposes to assemble
it there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from workers.batch_worker import (
    INCOMPLETE_LABEL,
    BatchWorker,
    CancellationToken,
    JobCancelled,
    LeaseLost,
    read_report,
)

from afterlap_api.db import create_all
from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import ExperimentJob, SnapshotRow
from afterlap_api.deps import Settings
from afterlap_api.main import API_PREFIX, create_app
from afterlap_api.routes import experiments as experiments_routes, exports as exports_routes
from afterlap_api.session import SessionFactory
from afterlap_contracts import JobStatus

from .conftest import SCENARIO_ID, actionable, start_session

if TYPE_CHECKING:
    from fastapi import FastAPI


def _queue_job(factory, job_id: str = "job-1") -> str:
    with command_transaction(factory) as db:
        db.add(ExperimentJob(id=job_id, manifest_hash="sha256:" + "e" * 64, status="queued"))
    return job_id


def _worker(factory, tmp_path: Path, worker_id: str) -> BatchWorker:
    return BatchWorker(
        factory,
        worker_id=worker_id,
        staging_root=tmp_path / "staging",
        reports_root=tmp_path / "reports",
    )


def test_two_workers_never_publish_two_successful_reports_for_one_job(db_factory, tmp_path):
    job_id = _queue_job(db_factory)
    first = _worker(db_factory, tmp_path, "worker-a")
    second = _worker(db_factory, tmp_path, "worker-b")

    claimed = first.claim()
    assert claimed == (job_id, "sha256:" + "e" * 64)
    assert second.claim() is None

    with command_transaction(db_factory) as db:
        db.get(ExperimentJob, job_id).worker_lease = "worker-b"  # type: ignore[union-attr]
    assert first.heartbeat(job_id) is False

    context = first.staging_for(job_id)
    from workers.batch_worker import JobContext

    ctx = JobContext(
        job_id=job_id,
        manifest_hash="sha256:" + "e" * 64,
        staging=context,
        token=CancellationToken(),
        heartbeat=lambda: first.heartbeat(job_id),
    )
    with pytest.raises(LeaseLost):
        first.finalise(ctx, {"result": "should not be published"})

    assert read_report(tmp_path / "reports", job_id) is None
    with command_transaction(db_factory) as db:
        assert db.get(ExperimentJob, job_id).status == "running"  # type: ignore[union-attr]

    outcome = second.run(job_id, "sha256:" + "e" * 64, lambda c: {"result": "ok"})
    assert outcome.status is JobStatus.COMPLETED
    report = read_report(tmp_path / "reports", job_id)
    assert report is not None and report["worker_id"] == "worker-b"
    assert report["partial_results"] is False


def test_a_cancelled_job_keeps_its_partial_results_labelled_incomplete(db_factory, tmp_path):
    job_id = _queue_job(db_factory, "job-cancel")
    worker = _worker(db_factory, tmp_path, "worker-c")
    assert worker.claim() is not None
    token = CancellationToken()

    def runner(ctx):  # type: ignore[no-untyped-def]
        for index in range(5):
            ctx.token.raise_if_cancelled()
            ctx.checkpoint(f"rollout-{index}", {"index": index, "utility": 0.1 * index})
            if index == 1:
                token.cancel("operator asked to stop")
        return {"result": "never reached"}

    outcome = worker.run(job_id, "sha256:" + "e" * 64, runner, token=token)
    assert outcome.status is JobStatus.CANCELLED
    assert outcome.partial_results is True
    assert outcome.completed_units == ("rollout-0", "rollout-1")

    report = read_report(tmp_path / "reports", job_id)
    assert report is not None
    assert report["label"] == INCOMPLETE_LABEL
    assert report["partial_results"] is True
    assert report["completed_units"] == ["rollout-0", "rollout-1"]
    assert "must not be aggregated" in report["notice"]

    with command_transaction(db_factory) as db:
        row = db.get(ExperimentJob, job_id)
        assert row is not None
        assert row.status == JobStatus.CANCELLED.value
        assert row.partial_results is True


def test_a_failed_lease_leaves_restartable_checkpoints(db_factory, tmp_path):
    job_id = _queue_job(db_factory, "job-resume")
    worker = _worker(db_factory, tmp_path, "worker-d")
    assert worker.claim() is not None

    def crashing(ctx):  # type: ignore[no-untyped-def]
        ctx.checkpoint("rollout-0", {"index": 0})
        ctx.checkpoint("rollout-1", {"index": 1})
        raise RuntimeError("the worker died between rollouts")

    outcome = worker.run(job_id, "sha256:" + "e" * 64, crashing)
    assert outcome.status is JobStatus.FAILED
    assert outcome.completed_units == ("rollout-0", "rollout-1")

    staging = worker.staging_for(job_id)
    assert sorted(p.name for p in staging.glob("checkpoint-*.json")) == [
        "checkpoint-rollout-0.json",
        "checkpoint-rollout-1.json",
    ]
    with command_transaction(db_factory) as db:
        db.get(ExperimentJob, job_id).status = "queued"  # type: ignore[union-attr]
    resumed = _worker(db_factory, tmp_path, "worker-e")
    assert resumed.claim() is not None

    seen: list[tuple[str, ...]] = []

    def resuming(ctx):  # type: ignore[no-untyped-def]
        seen.append(ctx.existing_checkpoints())
        ctx.checkpoint("rollout-2", {"index": 2})
        return {"result": "ok"}

    final = resumed.run(job_id, "sha256:" + "e" * 64, resuming)
    assert seen == [("rollout-0", "rollout-1")], "the restart did not see the earlier checkpoints"
    assert final.status is JobStatus.COMPLETED
    assert set(final.completed_units) >= {"rollout-2"}


def test_a_cancellation_is_only_observed_between_rollouts(db_factory, tmp_path):
    """The worker never interrupts a rollout in flight."""
    job_id = _queue_job(db_factory, "job-coop")
    worker = _worker(db_factory, tmp_path, "worker-f")
    assert worker.claim() is not None
    token = CancellationToken()
    token.cancel("cancelled before the run even started")

    finished: list[str] = []

    def runner(ctx):  # type: ignore[no-untyped-def]
        ctx.token.raise_if_cancelled()
        finished.append("rollout-0")
        return {"result": "unreachable"}

    outcome = worker.run(job_id, "sha256:" + "e" * 64, runner, token=token)
    assert finished == [], "a rollout ran after cancellation was already requested"
    assert outcome.status is JobStatus.CANCELLED
    assert outcome.partial_results is False
    with pytest.raises(JobCancelled):
        token.raise_if_cancelled()


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'routes.sqlite3').as_posix()}",
        artifact_root=tmp_path,
    )
    app: FastAPI = create_app(settings)
    app.include_router(experiments_routes.router, prefix=API_PREFIX, tags=["experiments"])
    app.include_router(exports_routes.router, prefix=API_PREFIX, tags=["exports"])
    with TestClient(app) as test_client:
        create_all(app.state.database.engine)
        app.state.session_factory = SessionFactory()
        test_client.app_instance = app  # type: ignore[attr-defined]
        yield test_client


def _headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key, "X-Operator-Id": "engineer-route"}


def test_creating_an_experiment_returns_202_and_a_trackable_job(client):
    app = client.app_instance  # type: ignore[attr-defined]
    session = start_session(app.state.database.factory)
    with command_transaction(app.state.database.factory) as db:
        db.add(
            SnapshotRow(
                id="snap-1",
                session_id=session.session_id,
                snapshot_hash="sha256:" + "f" * 64,
                session_time_s=1.0,
                label="branch point",
            )
        )

    response = client.post(
        f"{API_PREFIX}/experiments",
        json={
            "snapshot_id": "snap-1",
            "treatments": [{"treatment_id": "push", "controller": "fixed_push"}],
            "seeds": [1, 2],
            "evaluator_version": "eval-1",
            "evaluation_horizon_s": 20.0,
        },
        headers=_headers("exp-1"),
    )
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    assert job["status"] == "queued"
    assert job["report_hash"] is None
    assert job["partial_results"] is False

    status = client.get(f"{API_PREFIX}/experiments/{job['id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"


def test_an_experiment_on_an_unknown_snapshot_is_refused(client):
    response = client.post(
        f"{API_PREFIX}/experiments",
        json={
            "snapshot_id": "snap-missing",
            "treatments": [{"treatment_id": "a", "controller": "c"}],
            "seeds": [1],
            "evaluator_version": "eval-1",
            "evaluation_horizon_s": 10.0,
        },
        headers=_headers("exp-missing"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_cancelling_a_running_job_labels_its_partial_results(client):
    app = client.app_instance  # type: ignore[attr-defined]
    with command_transaction(app.state.database.factory) as db:
        db.add(
            ExperimentJob(
                id="job-partial",
                manifest_hash="sha256:" + "1" * 64,
                status="running",
                progress=0.4,
            )
        )

    response = client.post(
        f"{API_PREFIX}/experiments/job-partial/cancel",
        json={"reason": "superseded by a newer benchmark"},
        headers=_headers("cancel-1"),
    )
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["status"] == "cancelled"
    assert job["partial_results"] is True, "partial output was not labelled"
    assert job["progress"] == pytest.approx(0.4), "the scope of the partial output was erased"
    assert "superseded" in job["failure"]

    again = client.post(
        f"{API_PREFIX}/experiments/job-partial/cancel",
        json={"reason": "again"},
        headers=_headers("cancel-2"),
    )
    assert again.status_code == 200
    with command_transaction(app.state.database.factory) as db:
        db.add(
            ExperimentJob(
                id="job-done",
                manifest_hash="sha256:" + "2" * 64,
                status="completed",
                progress=1.0,
                report_hash="sha256:" + "3" * 64,
            )
        )
    refused = client.post(
        f"{API_PREFIX}/experiments/job-done/cancel",
        json={"reason": "too late"},
        headers=_headers("cancel-3"),
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"


def test_an_export_writes_inside_the_storage_root_and_redacts_credentials(client, tmp_path):
    app = client.app_instance  # type: ignore[attr-defined]
    session = start_session(app.state.database.factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(
        __import__("afterlap_contracts", fromlist=["DeploymentProfile"]).DeploymentProfile.HARVEST
    )
    session.advance_until(actionable)
    session.sync()

    response = client.post(
        f"{API_PREFIX}/exports",
        json={"session_id": session.session_id, "format": "json"},
        headers=_headers("export-1"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synthetic"] is True
    assert body["hashes"]["content"].startswith("sha256:")

    written = Path(body["path"])
    exports_root = (tmp_path / "artifacts" / "exports").resolve()
    assert written.resolve().is_relative_to(exports_root), "the export escaped the storage root"
    document = json.loads(written.read_text(encoding="utf-8"))
    assert document["session"]["id"] == session.session_id
    assert document["hashes"]["ruleset"] == session.manifest.ruleset_hash
    assert document["units"]["energy_j"] == "J"
    assert "SYNTHETIC EXPORT" in document["notice"]
    assert document["decisions"], "the export carries no decisions"
    text = json.dumps(document).lower()
    for forbidden in ("password", "secret", "credential", "worldstate", "rng_state"):
        assert forbidden not in text

    fetched = client.get(f"{API_PREFIX}/exports/{body['export_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["path"] == body["path"]


def test_an_export_path_cannot_escape_the_storage_root(client, tmp_path):
    from afterlap_core.paths import Paths

    paths = Paths.default(tmp_path).ensure()
    with pytest.raises(ValueError) as escaped:
        paths.resolve_within("../../etc/passwd", root=paths.exports)
    assert "escapes the configured storage root" in str(escaped.value)


def test_an_export_with_an_inverted_range_is_refused(client):
    app = client.app_instance  # type: ignore[attr-defined]
    session = start_session(app.state.database.factory)
    response = client.post(
        f"{API_PREFIX}/exports",
        json={
            "session_id": session.session_id,
            "format": "json",
            "start_session_time_s": 10.0,
            "end_session_time_s": 2.0,
        },
        headers=_headers("export-bad"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_creating_a_session_through_the_factory_route_refuses_an_unknown_scenario(client):
    response = client.post(
        f"{API_PREFIX}/sessions",
        json={
            "mode": "simulation",
            "scenario_id": "no-such-scenario",
            "ruleset_id": "synthetic-pack-v1",
            "seed": 1,
        },
        headers=_headers("session-bad"),
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "no-such-scenario" in error["message"]


def test_creating_a_session_through_the_factory_route_refuses_an_unknown_ruleset(client):
    response = client.post(
        f"{API_PREFIX}/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": "no-such-pack",
            "seed": 1,
        },
        headers=_headers("ruleset-bad"),
    )
    assert response.status_code == 404
    assert "no-such-pack" in response.json()["error"]["message"]


def test_creating_a_session_through_the_route_starts_a_real_runtime(client):
    response = client.post(
        f"{API_PREFIX}/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": "synthetic-pack-v1",
            "seed": 7,
            "label": "route smoke",
        },
        headers=_headers("session-ok"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["manifest"]["scenario_id"] == SCENARIO_ID
    assert body["manifest"]["seed"] == 7
    assert body["manifest"]["track_hash"].startswith("sha256:")
    capabilities = body["snapshot"]["capabilities"]
    assert capabilities["rival_energy"] == "unavailable"
    assert any("synthetic" in note.lower() for note in capabilities["notes"])

    app = client.app_instance  # type: ignore[attr-defined]
    runtime = app.state.runtimes.get(body["manifest"]["id"])
    assert runtime.session_time_s == 0.0
    assert runtime.revision == 1
