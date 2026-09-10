"""Graceful shutdown: flush the outbox, leave no partial artefact.

**Genuinely causes the conditions.** The outbox rows are written by a real
session through the real recorder, the publisher is a real `OutboxPublisher`
running as a real asyncio task, and shutdown is the real
`OutboxPublisher.stop_running()`. The partial-write drill makes the operating
system fail a real rename rather than patching `os.replace`.

One of these tests is expected to fail and is marked `xfail(strict=True)`.
That is not a weakened assertion: it asserts exactly what
`operations/TECHNICAL_SPEC.md` requires, the product does not do it, and
the strict marker means the suite will complain the moment the patch in
`handoffs/A14-integration-patch.md` lands and it starts passing.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from afterlap_api.db.engine import transaction
from afterlap_api.db.repository import unpublished_outbox
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.session import OutboxPublisher
from afterlap_api.stream import StreamHub
from afterlap_contracts import StreamEventType
from afterlap_core.paths import atomic_write_json, atomic_write_text

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED, LocalStore, actionable, start_session

if TYPE_CHECKING:
    from pathlib import Path

NEVER_POLLS_S = 600.0


def _pending(store: LocalStore) -> list[tuple[str, int, str]]:
    with transaction(store.factory) as db:
        return [
            (row.session_id, row.sequence, row.event_type)
            for row in unpublished_outbox(db, limit=500)
            if row.event_type in {e.value for e in StreamEventType}
        ]


async def _after_the_first_pass(store: LocalStore, *, timeout_s: float = 30.0) -> list[tuple[str, int, str]]:
    """What is still unpublished once the publisher's first poll has finished.

    The drain does its database work in a worker thread, so a contended
    SQLite writer never stalls the event loop. One tick of the loop is
    therefore no longer enough for the first pass to complete, and waiting for
    the backlog to clear is what "the first pass ran" now means. A pass that
    never clears it still fails, on the same assertion, at the deadline.
    """
    deadline = time.monotonic() + timeout_s
    pending = _pending(store)
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
        pending = _pending(store)
    return pending


def _running_session(store: LocalStore, tmp_path: Path):  # type: ignore[no-untyped-def]
    session = start_session(store.factory, spool_root=tmp_path / "spool")
    session.advance_until(actionable)
    assert _pending(store), "the session committed no publishable outbox rows"
    return session


def test_graceful_shutdown_flushes_the_outbox(store: LocalStore, tmp_path: Path):
    session = _running_session(store, tmp_path)

    async def start_then_shut_down() -> tuple[list[tuple[str, int, str]], int]:
        hub = StreamHub(buffer_size=1024, client_queue=512)
        await hub.subscribe(session.session_id, 0)
        publisher = OutboxPublisher(store.factory, hub)
        publisher.start(interval_s=NEVER_POLLS_S)
        assert await _after_the_first_pass(store) == [], (
            "the publisher's first pass did not clear the backlog"
        )

        session.advance(1.0)
        committed = _pending(store)
        assert committed, "advancing the session committed no new outbox rows"

        await publisher.stop_running()
        return _pending(store), len(committed)

    remaining, committed = asyncio.run(start_then_shut_down())
    assert remaining == [], (
        f"{len(remaining)} of {committed} lifecycle change(s) committed before shutdown were "
        f"never delivered: {remaining[:5]}"
    )


def test_a_further_drain_after_shutdown_is_a_no_op(store: LocalStore, tmp_path: Path):
    """The final drain now lives inside ``stop_running``, so a second is empty.

    Written before that fix, to show an extra ``drain_once`` would deliver what
    shutdown had left behind. With the drain moved inside ``stop_running`` the
    extra call has nothing to do, so the property worth asserting changed:
    shutdown must deliver everything, and draining again must be harmless
    rather than double-publishing what the client already received.
    """
    session = _running_session(store, tmp_path)

    async def start_then_shut_down_with_a_final_drain() -> tuple[list[tuple[str, int, str]], int, int]:
        hub = StreamHub(buffer_size=1024, client_queue=512)
        subscriber, resync = await hub.subscribe(session.session_id, 0)
        assert resync is False
        publisher = OutboxPublisher(store.factory, hub)
        publisher.start(interval_s=NEVER_POLLS_S)
        assert await _after_the_first_pass(store) == []

        session.advance(1.0)
        committed = len(_pending(store))

        await publisher.stop_running()
        report = await publisher.drain_once()
        drained = 0
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
            drained += 1
        return _pending(store), committed, report.published

    remaining, committed, published = asyncio.run(start_then_shut_down_with_a_final_drain())
    print(f"\ncommitted after the last poll: {committed}; published by the extra drain: {published}")
    assert remaining == [], f"shutdown left {remaining[:5]}"
    assert committed > 0, "advancing the session committed no new outbox rows"
    assert published == 0, (
        f"the extra drain published {published} rows; shutdown should already have "
        "delivered them, and re-publishing would duplicate what the client received"
    )


def test_the_application_lifespan_stops_its_background_task_and_disposes_the_engine(tmp_path: Path):
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        publisher = app.state.publisher
        assert publisher._task is not None, "the outbox publisher never started"

    assert app.state.publisher._task is None, "the publisher task survived shutdown"
    assert app.state.database.engine.pool.checkedout() == 0, "a connection was still checked out"
    print("\nlifespan shutdown: publisher task stopped, no connection checked out")


def test_a_failed_write_leaves_no_staging_file_behind(tmp_path: Path):
    """The operating system fails a real rename; nothing is patched.

    `atomic_write_bytes` stages into a temporary file beside the target and
    then renames. Pointing it at a path that is an existing *directory* makes
    `os.replace` fail inside the OS, which is the closest reachable analogue of
    a crash between the write and the rename.
    """
    target = tmp_path / "occupied"
    target.mkdir()

    with pytest.raises(OSError):
        atomic_write_json(target, {"session_id": "ses-drill", "synthetic": True})

    leftovers = [p.name for p in tmp_path.iterdir() if ".staging" in p.name]
    assert leftovers == [], f"a staging file survived a failed write: {leftovers}"
    assert target.is_dir(), "the failed write replaced the existing entry"

    good = tmp_path / "record.json"
    atomic_write_text(good, json.dumps({"complete": True}))
    assert json.loads(good.read_text(encoding="utf-8")) == {"complete": True}
    assert [p.name for p in tmp_path.iterdir() if ".staging" in p.name] == []


def test_a_full_run_and_shutdown_leaves_only_complete_artefacts(tmp_path: Path):
    """Drive a real session through the app, shut down, then audit the tree."""
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "shutdown-1"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]

        client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": "console-operator", "ttl_s": 600.0},
            headers={"Idempotency-Key": "shutdown-lease"},
        )
        revision = 0
        for index in range(3):
            step = client.post(
                f"/api/v1/sessions/{session_id}/commands",
                json={
                    "kind": "step",
                    "expected_revision": revision,
                    "operator_id": "console-operator",
                    "step_duration_s": 1.0,
                },
                headers={"Idempotency-Key": f"shutdown-step-{index}"},
            )
            assert step.status_code == 200, step.text
            revision = step.json()["revision"]

        snapshot = client.post(
            f"/api/v1/sessions/{session_id}/snapshots",
            json={"label": "before shutdown"},
            headers={"Idempotency-Key": "shutdown-snapshot"},
        )
        assert snapshot.status_code == 201, snapshot.text
        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": "shutdown-export"},
        )
        assert export.status_code == 201, export.text

    artifacts = tmp_path / "artifacts"
    staging = [
        p for p in artifacts.rglob("*") if p.is_file() and (".staging" in p.name or p.suffix == ".tmp")
    ]
    assert staging == [], f"shutdown left partially written artefacts: {staging}"

    checked = 0
    for candidate in artifacts.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix == ".json" or candidate.parent.name in {"spool", "exports"}:
            text = candidate.read_text(encoding="utf-8")
            json.loads(text)
            checked += 1
    print(f"\naudited {checked} JSON artefact(s) after shutdown; all parse")
    assert checked > 0, "the run produced no JSON artefact to audit"

    from afterlap_core.paths import ArtifactStore

    store = ArtifactStore(artifacts / "objects")
    digests = list(store.iter_digests())
    for digest in digests:
        store.get_bytes(digest)
    print(f"verified {len(digests)} content-addressed object(s)")
    assert digests, "the snapshot wrote no content-addressed object"
