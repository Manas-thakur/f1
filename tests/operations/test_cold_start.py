"""Cold start from an empty artefact root.

**Genuinely causes the condition.** Every test here starts from a `tmp_path`
that holds nothing at all: no database file, no schema, no `artifacts/` tree.
Nothing calls `create_all`. The application's own startup path is the only
thing that creates anything, which is exactly the case coordinator decision
D-07 defect 1 describes:

    `create_all()` was called by tests and by nothing else. The first
    `POST /sessions` failed with `no such table: manifest`, surfacing as an
    opaque 500.

So the assertions are deliberately about *evidence that the migration ran*
rather than about the request merely returning 201: an `alembic_version` table
with a revision in it, and the ORM's tables actually present.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text

from afterlap_api.client import TestClient
from afterlap_api.db.models import Base
from afterlap_api.deps import Settings
from afterlap_api.main import create_app

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def cold_root(tmp_path: Path) -> Path:
    """An artefact root that does not exist yet, inside a directory that does."""
    root = tmp_path / "install"
    root.mkdir()
    assert not (root / "artifacts").exists()
    return root


def _settings(root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{(root / 'afterlap.sqlite3').as_posix()}",
        artifact_root=root,
        session_runtime_backend="in_process",
    )


def test_a_cold_start_creates_the_schema_and_the_artefact_tree(cold_root: Path):
    settings = _settings(cold_root)
    app = create_app(settings)

    started = time.perf_counter()
    with TestClient(app) as client:
        cold_start_s = time.perf_counter() - started

        engine = app.state.database.engine
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        assert "alembic_version" in tables, f"no alembic_version table after startup; found {sorted(tables)}"
        with engine.connect() as connection:
            revisions = [r[0] for r in connection.execute(text("select version_num from alembic_version"))]
        assert len(revisions) == 1, f"alembic_version holds {revisions}; exactly one head is expected"
        assert revisions[0], "alembic_version exists but is empty; no migration was applied"

        expected = set(Base.metadata.tables)
        missing = expected - tables
        assert not missing, f"the migration left these ORM tables missing: {sorted(missing)}"

        for relative in ("artifacts", "artifacts/trajectories", "artifacts/models", "artifacts/spool"):
            assert (cold_root / relative).is_dir(), f"{relative} was not created on a cold start"

        assert client.get("/api/v1/health/live").json()["status"] == "live"
        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 200, ready.json()
        detail = ready.json()["detail"]
        assert detail["storage"] == "available"
        assert detail["contracts"] == "available"
        assert detail["numerics"] == "available"

    print(f"\ncold start (lifespan entered to ready): {cold_start_s:.2f} s")
    assert cold_start_s < 120.0, "a cold start that takes minutes is a broken install, not a slow one"


def test_a_session_can_be_created_on_a_clean_install(cold_root: Path):
    """The D-07 regression: the first POST /sessions on a fresh machine."""
    app = create_app(_settings(cold_root))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
                "label": "cold start drill",
            },
            headers={"Idempotency-Key": "cold-start-1", "X-Operator-Id": "console-operator"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        session_id = body["manifest"]["id"]
        assert body["manifest"]["synthetic"] is True
        assert body["snapshot"]["revision"] == 0

        listed = client.get("/api/v1/sessions").json()["sessions"]
        assert [s["id"] for s in listed] == [session_id]

        lease = client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": "console-operator", "ttl_s": 600.0},
            headers={"Idempotency-Key": "cold-start-lease"},
        )
        assert lease.status_code == 200, lease.text

        step = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={
                "kind": "step",
                "expected_revision": 0,
                "operator_id": "console-operator",
                "step_duration_s": 1.0,
            },
            headers={"Idempotency-Key": "cold-start-step"},
        )
        assert step.status_code == 200, step.text
        assert step.json()["accepted"] is True
        assert step.json()["revision"] == 1


def test_a_second_start_on_the_same_root_is_idempotent(cold_root: Path):
    """`upgrade head` runs on every boot; a restart must not fail or duplicate."""
    settings = _settings(cold_root)

    with TestClient(create_app(settings)) as first:
        assert first.get("/api/v1/health/live").status_code == 200

    app = create_app(settings)
    with TestClient(app) as second:
        assert second.get("/api/v1/health/ready").status_code == 200
        engine = app.state.database.engine
        with engine.connect() as connection:
            revisions = [r[0] for r in connection.execute(text("select version_num from alembic_version"))]
        assert len(revisions) == 1, f"a second start left {revisions} in alembic_version"
