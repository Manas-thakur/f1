"""The stream cursor a browser resumes from must be one the server can honour.

`contracts/UNITS_TIME.md`: "Snapshot records contain `last_sequence`. WebSocket
clients detect gaps and request a new snapshot." The frontend reducer implements
that literally — a delta whose sequence is not `last_sequence + 1` pauses delta
application and demands a fresh snapshot.

Two defects found in a browser audit of `fa841e6` broke that contract from the
server side, and together they made the engineer console unusable:

1. `POST /sessions/{id}/commands` incremented `Session.last_sequence` without
   publishing an envelope at that number. `Session.last_sequence` is the
   sequence *allocator*, so every command left a permanent hole in the
   published stream and pushed the snapshot's advertised cursor one past
   anything a client could ever receive.
2. `StreamHub` refused any non-zero cursor while its buffer was empty — the
   state of every session after a control-plane restart — so the resync it
   demanded could not succeed.

Either one on its own produces an unbounded loop: the client resyncs, gets the
same cursor back, reconnects, and is told to resync again. A single browser tab
measured 10 947 snapshot requests in nine minutes.

These tests reproduce the conditions rather than asserting the fix's shape:
they run real commands through the real routes and then check the published
sequence space and what a real WebSocket subscription answers.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from afterlap_api.db.models import OutboxRecord
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.stream import StreamHub

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR = "console-operator"


def _settings(root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{(root / 'afterlap.sqlite3').as_posix()}",
        artifact_root=root,
        session_runtime_backend="in_process",
    )


def _start_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": RULE_PACK_ID,
            "seed": SEED,
            "label": "stream cursor drill",
        },
        headers={"Idempotency-Key": "cursor-create", "X-Operator-Id": OPERATOR},
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["manifest"]["id"]

    lease = client.post(
        f"/api/v1/sessions/{session_id}/control-lease",
        json={"operator_id": OPERATOR, "ttl_s": 600.0},
        headers={"Idempotency-Key": "cursor-lease", "X-Operator-Id": OPERATOR},
    )
    assert lease.status_code == 200, lease.text
    return session_id


def _step(client: TestClient, session_id: str, *, revision: int, key: str) -> int:
    response = client.post(
        f"/api/v1/sessions/{session_id}/commands",
        json={
            "kind": "step",
            "expected_revision": revision,
            "operator_id": OPERATOR,
            "step_duration_s": 1.0,
        },
        headers={"Idempotency-Key": key, "X-Operator-Id": OPERATOR},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["revision"])


def _await_publisher(app: object, session_id: str, cursor: int, timeout_s: float = 5.0) -> None:
    """Wait until the outbox publisher has handed the hub everything up to ``cursor``.

    The store advances ``last_sequence`` when an event row is written; the hub
    learns of it only when the publisher drains. A snapshot read inside that
    window advertises a cursor the hub has not seen yet, which is a real (and
    self-correcting) source of one extra resync in the product. It is not what
    this test is about, so it is waited out rather than raced.
    """
    hub = app.state.hub  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout_s
    while hub.channel(session_id).latest_sequence < cursor and time.monotonic() < deadline:
        time.sleep(0.02)


def _published_sequences(app_state: object, session_id: str) -> list[int]:
    factory = app_state.database.factory  # type: ignore[attr-defined]
    with factory() as db:
        rows = db.execute(
            select(OutboxRecord.sequence)
            .where(OutboxRecord.session_id == session_id)
            .order_by(OutboxRecord.sequence)
        ).all()
    return [int(row[0]) for row in rows]


def test_commands_do_not_punch_holes_in_the_published_sequence(tmp_path: Path):
    """Ten steps must not cost ten sequence numbers nobody can receive."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session_id = _start_session(client)

        revision = 0
        for index in range(10):
            revision = _step(client, session_id, revision=revision, key=f"cursor-step-{index}")

        published = _published_sequences(app.state, session_id)
        snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()

    assert published, "a stepped session published nothing at all"
    assert published == list(range(1, len(published) + 1)), (
        "the published stream has holes in it; a browser reducer answers a hole by "
        f"demanding a resync forever. sequences: {published}"
    )
    assert snapshot["last_sequence"] == published[-1], (
        "the snapshot advertises a cursor the stream never emitted, so a client "
        "resuming from it can never be current"
    )


def test_a_client_resuming_from_the_snapshot_cursor_is_not_told_to_resync(tmp_path: Path):
    """The end-to-end shape: snapshot, then subscribe at the cursor it gave."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session_id = _start_session(client)

        revision = 0
        for index in range(6):
            revision = _step(client, session_id, revision=revision, key=f"resume-step-{index}")

        cursor = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["last_sequence"]
        _await_publisher(app, session_id, cursor)

        url = f"/api/v1/sessions/{session_id}/stream?after_sequence={cursor}"
        with client.websocket_connect(url) as socket:
            client.post(
                f"/api/v1/sessions/{session_id}/commands",
                json={
                    "kind": "step",
                    "expected_revision": revision,
                    "operator_id": OPERATOR,
                    "step_duration_s": 1.0,
                },
                headers={"Idempotency-Key": "resume-step-final", "X-Operator-Id": OPERATOR},
            )
            first = socket.receive_json()

    assert first["event_type"] != "resync_required", (
        "a client resuming from the cursor the control plane just handed it was told to "
        f"resync: {first['payload']}"
    )
    assert first["sequence"] == cursor + 1, (
        "the first delta after the advertised cursor is not the next sequence, so the "
        f"reducer sees a gap: cursor {cursor}, delta {first['sequence']}"
    )


def test_operator_actions_do_not_punch_holes_either(tmp_path: Path):
    """Select and mark-communicated are audited, not published, and must be free.

    The ``operator_action`` event is deliberately kept out of the outbox. When
    it also claimed a sequence of its own, every human action left a hole and
    the console resynced its way through the whole lifecycle.
    """
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session_id = _start_session(client)

        revision = 0
        recommendation: dict[str, object] | None = None
        for index in range(40):
            revision = _step(client, session_id, revision=revision, key=f"action-step-{index}")
            candidate = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["recommendation"]
            if candidate is not None and candidate["action_code"] != "withdraw_advice":
                recommendation = candidate
                break

        assert recommendation is not None, "the shipped scenario never produced an actionable plan"

        for action, key in (("select", "act-select"), ("mark_communicated", "act-communicated")):
            response = client.post(
                f"/api/v1/sessions/{session_id}/recommendations/{recommendation['id']}/actions",
                json={
                    "action": action,
                    "operator_id": OPERATOR,
                    "expected_revision": recommendation["revision"],
                },
                headers={"Idempotency-Key": key, "X-Operator-Id": OPERATOR},
            )
            assert response.status_code == 200, response.text
            recommendation = response.json()["recommendation"]

        published = _published_sequences(app.state, session_id)
        cursor = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["last_sequence"]

    missing = [n for n in range(1, published[-1] + 1) if n not in set(published)]
    assert not missing, f"operator actions left unreachable sequences in the stream: {missing}"
    assert cursor == published[-1], (
        "after two operator actions the snapshot cursor no longer matches the stream"
    )


def _subscribe(cursor: int, known: int | None) -> bool:
    hub = StreamHub(buffer_size=16, client_queue=32)

    async def scenario() -> bool:
        _, resync = await hub.subscribe("ses-empty-channel", cursor, known_sequence=known)
        return resync

    return asyncio.run(scenario())


def test_an_empty_channel_accepts_a_cursor_the_store_agrees_with():
    """A restarted control plane holds no history but the store still does.

    Refusing a current cursor here is not a repair: the client refetches the
    snapshot, returns with the same cursor, and is refused again for the same
    reason.
    """
    assert _subscribe(10, 10) is False, (
        "an empty channel refused a cursor the store says is current, which is the "
        "restart loop this exists to prevent"
    )


@pytest.mark.parametrize(("cursor", "known"), [(4, 10), (0, 10), (4096, 10), (11, 10)])
def test_an_empty_channel_refuses_a_cursor_the_store_disagrees_with(cursor: int, known: int):
    """Behind and ahead are both refusals, and both converge on the snapshot.

    Accepting a cursor *ahead* of the store is the dangerous half: the reducer
    discards every later sequence as already applied, so the client goes silent
    with no resync and no error. Accepting one *behind* silently skips the
    events this process no longer holds.
    """
    assert _subscribe(cursor, known) is True, (
        f"cursor {cursor} was accepted against a durable cursor of {known}"
    )


def test_an_empty_channel_without_an_authority_only_accepts_a_fresh_client():
    """No store answer means no evidence, so only a cursor of zero is safe."""
    assert _subscribe(0, None) is False
    assert _subscribe(7, None) is True


def test_a_cursor_ahead_of_the_store_is_told_to_resync_over_the_wire(tmp_path: Path):
    """The route-level shape of the ahead case, through a real subscription."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session_id = _start_session(client)
        revision = 0
        for index in range(3):
            revision = _step(client, session_id, revision=revision, key=f"ahead-step-{index}")

        cursor = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["last_sequence"]

        url = f"/api/v1/sessions/{session_id}/stream?after_sequence={cursor + 500}"
        with client.websocket_connect(url) as socket:
            first = socket.receive_json()

    assert first["event_type"] == "resync_required", (
        "a cursor far past anything the session issued was accepted as current; the "
        "reducer then discards every real delta as a duplicate and goes silent"
    )
    assert first["payload"]["reason"] == "cursor ahead of the published stream"
