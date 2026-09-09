"""The stream must announce the same circuit REST and storage record.

A client that resyncs is told to fetch the REST snapshot and continue. If the
initial stream snapshot, the REST snapshot and the persisted row could disagree
about which compiled package a session runs on, a resync would silently swap
the circuit under the operator, and no surface would be evidence of what ran.

This drill drives the real application: a session is created on a compiled
package, a WebSocket client connects and reads the announcement the outbox
publisher actually delivered, the cursor is then taken outside the retained
buffer so a genuine `resync_required` is issued, and the REST snapshot the
resync points at is compared field by field against the announcement and
against the database row.

The package is a synthetic analytic loop written under a registry id: the
identity paths are real, the geometry is not that circuit's, and nothing here
is a claim about a real circuit.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from fastapi.testclient import TestClient

from afterlap_api.db import create_all, transaction
from afterlap_api.db.models import Session as SessionRow
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.session import SessionFactory
from afterlap_contracts import StreamEventType
from afterlap_core.paths import Paths
from afterlap_core.tracks import (
    CompiledCentreline,
    CorridorQuality,
    Direction,
    GeometryDescriptor,
    GeometryProvenance,
    NamedRange,
    ReadinessStatus,
    SourceRecord,
    SRange,
    TrackFeatures,
    TrackPackage,
    ValidationReport,
)

if TYPE_CHECKING:
    from pathlib import Path

TRACK_ID = "spa"
SCENARIO_ID = "two-straight-counterattack"
RULE_PACK_ID = "synthetic-pack-v1"
SEED = 42
LENGTH_M = 4000.0


def _write_package(paths: Paths) -> TrackPackage:
    count = int(LENGTH_M)
    s = np.arange(count, dtype=float)
    radius = LENGTH_M / (2.0 * np.pi)
    theta = s / radius
    z = 2.0 * np.sin(theta)
    centreline = CompiledCentreline(
        s_m=s,
        x_m=radius * np.cos(theta),
        y_m=radius * np.sin(theta),
        z_m=z,
        yaw_rad=theta + np.pi / 2.0,
        curvature_1pm=np.full(count, 1.0 / radius),
        grade_rad=np.gradient(z, s),
        length_m=LENGTH_M,
    )
    directory = paths.artifacts / "tracks" / TRACK_ID
    directory.mkdir(parents=True, exist_ok=True)
    digest = centreline.to_npz(directory / "centreline.npz")
    package = TrackPackage(
        track_id=TRACK_ID,
        display_name=f"Synthetic analytic loop written as {TRACK_ID} (fixture)",
        direction=Direction.COUNTERCLOCKWISE,
        nominal_length_m=LENGTH_M,
        geometry=GeometryDescriptor(
            sample_spacing_m=1.0,
            point_count=centreline.point_count,
            crs="local-enu",
            arrays_path="centreline.npz",
            arrays_sha256=digest,
            corridor_quality=CorridorQuality.UNKNOWN,
            provenance=GeometryProvenance.SYNTHETIC_SKETCH,
        ),
        features=TrackFeatures(
            start_finish_s_m=0.0,
            sectors=(
                SRange(start_s_m=0.0, end_s_m=1400.0),
                SRange(start_s_m=1400.0, end_s_m=2800.0),
                SRange(start_s_m=2800.0, end_s_m=LENGTH_M),
            ),
            corners=(
                NamedRange(id="attack-exit", start_s_m=1900.0, end_s_m=2100.0),
                NamedRange(id="counterattack-exit", start_s_m=3300.0, end_s_m=3500.0),
            ),
        ),
        sources=(
            SourceRecord(
                source_id="synthetic-analytic-loop",
                title="Synthetic analytic loop (test fixture)",
                url="synthetic://tests/backend/analytic-loop",
                retrieved_at="2026-09-08T00:00:00Z",
                permission="synthetic fixture; no external rights involved",
                priority=5,
            ),
        ),
        validation=ValidationReport(
            status=ReadinessStatus.GEOMETRY_VALIDATED,
            closure_error_m=0.0,
            length_error_fraction=0.0,
            report_path="validation_report.json",
            checks={"closure": "pass", "length": "pass"},
            notes=("synthetic fixture; not this circuit's geometry",),
        ),
    ).with_hash()
    (directory / "package.json").write_text(json.dumps(package.to_schema_dict(), indent=2), encoding="utf-8")
    return package


def _paths(root: Path) -> Paths:
    default = Paths.default()
    artifacts = root / "artifacts"
    return Paths(
        root=root,
        configs=default.configs,
        artifacts=artifacts,
        trajectories=artifacts / "trajectories",
        models=artifacts / "models",
        reports=artifacts / "reports",
        exports=artifacts / "exports",
        spool=artifacts / "spool",
    )


@pytest.fixture
def streaming(tmp_path: Path):  # type: ignore[no-untyped-def]
    paths = _paths(tmp_path).ensure()
    package = _write_package(paths)
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        create_all(app.state.database.engine)
        existing = app.state.session_factory
        app.state.session_factory = SessionFactory(
            paths=paths, planner=existing._planner, recorder_factory=existing._recorder_factory
        )
        app.state.track_paths = paths
        yield app, client, package


def _create(client) -> dict:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/v1/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": RULE_PACK_ID,
            "seed": SEED,
            "track_id": TRACK_ID,
        },
        headers={"Idempotency-Key": "stream-circuit-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _identity(manifest: dict) -> tuple:
    return (
        manifest["track_id"],
        manifest["track_package_hash"],
        manifest["track_readiness"],
        manifest["geometry_provenance"],
        manifest["conditions_id"],
        manifest["conditions_hash"],
    )


def test_the_streamed_announcement_carries_the_same_circuit_as_rest_and_storage(streaming):
    """The initial snapshot event a subscriber receives, from the real outbox."""
    app, client, package = streaming
    created = _create(client)
    session_id = created["manifest"]["id"]

    delivered = None
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream?after_sequence=0") as socket:
        for _ in range(20):
            envelope = json.loads(socket.receive_text())
            if envelope["event_type"] == StreamEventType.SNAPSHOT.value:
                delivered = envelope
                break
    assert delivered is not None, "the stream never announced the session it had just created"

    announced = _identity(delivered["payload"]["snapshot"]["manifest"])
    rest = _identity(client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["manifest"])
    print(f"\nannounced {announced}\nrest      {rest}")

    with transaction(app.state.database.factory) as db:
        row = db.get(SessionRow, session_id)
        assert row is not None
        stored = (
            row.track_id,
            row.track_package_hash,
            row.track_readiness,
            row.geometry_provenance,
            row.conditions_id,
            row.conditions_hash,
        )

    assert announced == rest == stored, (
        "the stream, the REST snapshot and the session row do not agree about the circuit; a "
        "client that resynced would be told a different circuit ran"
    )
    assert announced[1] == package.package_hash


def test_a_resync_points_at_a_snapshot_with_the_same_circuit_identity(streaming):
    """The REST snapshot a `resync_required` names is the resync target.

    A client that receives one is instructed to fetch that snapshot and
    continue from it. If the circuit it describes differed from the one the
    session was created on, resynchronising would silently swap the circuit
    under the operator.
    """
    _app, client, package = streaming
    created = _create(client)
    session_id = created["manifest"]["id"]

    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream?after_sequence=9999") as socket:
        first = json.loads(socket.receive_text())
    print(f"\ncursor outside the buffer produced {first['event_type']}")
    assert first["event_type"] == StreamEventType.RESYNC_REQUIRED.value, (
        "a cursor outside the retained window was served a replay with a silent gap"
    )
    assert first["session_id"] == session_id

    resynced = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert _identity(resynced["manifest"]) == _identity(created["manifest"]), (
        "the snapshot a resync points at describes a different circuit from the one the session "
        "was created on"
    )
    assert resynced["manifest"]["track_package_hash"] == package.package_hash


def test_the_hub_issues_a_real_resync_when_a_cursor_falls_out_of_the_window(streaming):
    """The hub's own classification, driven past a genuinely small buffer."""
    import asyncio

    from afterlap_contracts import SCHEMA_VERSION, StreamEnvelope
    from afterlap_contracts.events import HeartbeatPayload

    _app, _client, _package = streaming
    hub_session = "ses-resync-drill"

    async def drive() -> tuple[bool, str]:
        from afterlap_api.stream import StreamHub

        hub = StreamHub(buffer_size=2)
        for sequence in (1, 2, 3, 4):
            await hub.publish(
                StreamEnvelope(
                    schema_version=SCHEMA_VERSION,
                    session_id=hub_session,
                    sequence=sequence,
                    event_type=StreamEventType.HEARTBEAT,
                    session_time_s=float(sequence),
                    payload=HeartbeatPayload(server_uptime_s=float(sequence)),
                )
            )
        subscriber, needs = await hub.subscribe(hub_session, after_sequence=1)
        envelope = subscriber.queue.get_nowait()
        return needs, envelope.event_type.value

    needs_resync, event_type = asyncio.run(drive())
    print(f"\ncursor behind a 2-envelope buffer: resync={needs_resync}, first event {event_type}")
    assert needs_resync is True, "a cursor older than the retained window was replayed with a gap"
    assert event_type == StreamEventType.RESYNC_REQUIRED.value


def test_a_synthetic_sketch_session_announces_no_circuit_identity(streaming):
    """Null on the wire too. An absent package must not arrive as an empty string."""
    _app, client, _package = streaming
    response = client.post(
        "/api/v1/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": RULE_PACK_ID,
            "seed": SEED,
        },
        headers={"Idempotency-Key": "stream-sketch-1"},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["manifest"]["id"]

    delivered = None
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream?after_sequence=0") as socket:
        for _ in range(20):
            envelope = json.loads(socket.receive_text())
            if envelope["event_type"] == StreamEventType.SNAPSHOT.value:
                delivered = envelope
                break
    assert delivered is not None

    manifest = delivered["payload"]["snapshot"]["manifest"]
    print(f"\nsketch announcement: track_package_hash={manifest['track_package_hash']!r}")
    assert manifest["track_package_hash"] is None
    assert manifest["track_readiness"] is None
