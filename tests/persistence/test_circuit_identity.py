"""Circuit identity has to survive everything that outlives the process.

A16-8 added the identity columns on `session` and `simulation_snapshot` and
its handoff records that it added no tests. What matters is not that the
columns exist: it is that the same package hash comes back out of every route
that claims to describe the session, after the process that created it is
gone.

So this drill creates a session on a compiled circuit, **disposes the whole
application**, starts a second one against the same database, and then reads
the identity back from the snapshot, the export and the replay of that export.
Five surfaces have to agree, and a mismatch anywhere means none of them is
evidence of which geometry ran.

The package is a synthetic analytic loop written under a registry id, so the
identity resolution paths are exercised; it is not that circuit's geometry and
nothing here is a claim about a real circuit.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from afterlap_api.client import TestClient
from afterlap_api.db import create_all
from afterlap_api.db.models import Session as SessionRow, SnapshotRow
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.session import SessionFactory
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
OPERATOR = "console-operator"


def _analytic_loop() -> CompiledCentreline:
    count = int(LENGTH_M)
    s = np.arange(count, dtype=float)
    radius = LENGTH_M / (2.0 * np.pi)
    theta = s / radius
    z = 2.0 * np.sin(theta)
    return CompiledCentreline(
        s_m=s,
        x_m=radius * np.cos(theta),
        y_m=radius * np.sin(theta),
        z_m=z,
        yaw_rad=theta + np.pi / 2.0,
        curvature_1pm=np.full(count, 1.0 / radius),
        grade_rad=np.gradient(z, s),
        length_m=LENGTH_M,
    )


def _write_package(paths: Paths) -> TrackPackage:
    """Freeze a synthetic package into ``artifacts/tracks/<id>/``."""
    centreline = _analytic_loop()
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
                url="synthetic://tests/persistence/analytic-loop",
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
def circuit(tmp_path: Path) -> TrackPackage:
    return _write_package(_paths(tmp_path).ensure())


def _open(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A fresh application over the same database and artefact tree."""
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    paths = _paths(tmp_path)
    client = TestClient(app)
    client.__enter__()
    create_all(app.state.database.engine)
    existing = app.state.session_factory
    app.state.session_factory = SessionFactory(
        paths=paths, planner=existing._planner, recorder_factory=existing._recorder_factory
    )
    app.state.track_paths = paths
    return app, client


def _drive(client, session_id: str, steps: int = 3) -> None:
    lease = client.post(
        f"/api/v1/sessions/{session_id}/control-lease",
        json={"operator_id": OPERATOR, "ttl_s": 600.0},
        headers={"Idempotency-Key": f"{session_id}-lease"},
    )
    assert lease.status_code == 200, lease.text
    revision = 0
    for index in range(steps):
        step = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={
                "kind": "step",
                "expected_revision": revision,
                "operator_id": OPERATOR,
                "step_duration_s": 1.0,
            },
            headers={"Idempotency-Key": f"{session_id}-step-{index}"},
        )
        assert step.status_code == 200, step.text
        revision = step.json()["revision"]


def test_circuit_identity_survives_a_restart_snapshot_export_and_replay(
    tmp_path: Path, circuit: TrackPackage
):
    app, client = _open(tmp_path)
    try:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
                "track_id": TRACK_ID,
                "label": "persistence circuit drill",
            },
            headers={"Idempotency-Key": "persist-circuit-1"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]
        assert created.json()["manifest"]["track_package_hash"] == circuit.package_hash

        _drive(client, session_id)
        snapshot = client.post(
            f"/api/v1/sessions/{session_id}/snapshots",
            json={"label": "before the restart"},
            headers={"Idempotency-Key": "persist-circuit-snapshot"},
        )
        assert snapshot.status_code in (200, 201), snapshot.text
    finally:
        client.__exit__(None, None, None)

    app, client = _open(tmp_path)
    try:
        row_identity = None
        snapshot_identity = None
        from afterlap_api.db import transaction

        with transaction(app.state.database.factory) as db:
            row = db.get(SessionRow, session_id)
            assert row is not None, "the session did not survive the restart at all"
            row_identity = (row.track_id, row.track_package_hash, row.track_readiness)
            stored = db.query(SnapshotRow).filter_by(session_id=session_id).all()
            assert stored, "no snapshot row survived the restart"
            snapshot_identity = (stored[0].track_id, stored[0].track_package_hash)

        print(f"\nafter restart: session row {row_identity}, snapshot row {snapshot_identity}")
        assert row_identity == (TRACK_ID, circuit.package_hash, "geometry_validated")
        assert snapshot_identity == (TRACK_ID, circuit.package_hash), (
            "a snapshot cannot be branched from honestly if it does not record which geometry produced it"
        )

        rest = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
        assert rest["manifest"]["track_package_hash"] == circuit.package_hash
        assert rest["manifest"]["track_id"] == TRACK_ID

        catalogued = next(
            entry for entry in client.get("/api/v1/tracks").json()["tracks"] if entry["track_id"] == TRACK_ID
        )
        assert catalogued["package_hash"] == circuit.package_hash, (
            "the catalogue and the persisted session disagree about the circuit's hash"
        )

        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": "persist-circuit-export"},
        )
        assert export.status_code == 201, export.text
        reported = export.json()["path"]
        assert not reported.startswith("/"), f"the export response names a server path: {reported}"
        document = json.loads((tmp_path / reported).read_text(encoding="utf-8"))
        print(f"exported circuit block: {document['circuit']}")

        assert document["circuit"]["track_id"] == TRACK_ID
        assert document["circuit"]["track_package_hash"] == circuit.package_hash
        assert document["circuit"]["run_label"] == "real_circuit_synthetic_energy"
        assert document["hashes"]["track_package"] == circuit.package_hash

        replayed = json.loads((tmp_path / reported).read_text(encoding="utf-8"))
        assert replayed["content_hash"] == document["content_hash"], (
            "reading the export twice produced two different documents"
        )
        assert replayed["circuit"] == document["circuit"]
    finally:
        client.__exit__(None, None, None)


def test_a_synthetic_sketch_session_persists_null_circuit_identity(tmp_path: Path, circuit: TrackPackage):
    """Null is the honest value, and it must not become an empty string.

    `AGENTS.md`: unknown values are null plus provenance, never a placeholder.
    A synthetic sketch has no compiled package, so every package column stays
    null and the export makes no real-circuit claim.
    """
    app, client = _open(tmp_path)
    try:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "persist-sketch-1"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]
        _drive(client, session_id, steps=1)

        from afterlap_api.db import transaction

        with transaction(app.state.database.factory) as db:
            row = db.get(SessionRow, session_id)
            assert row is not None
            print(f"\nsketch row: track_id={row.track_id!r} hash={row.track_package_hash!r}")
            assert row.track_package_hash is None
            assert row.track_readiness is None
            assert row.event_package_hash is None

        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": "persist-sketch-export"},
        )
        assert export.status_code == 201, export.text
        document = json.loads((tmp_path / export.json()["path"]).read_text(encoding="utf-8"))
        assert document["circuit"]["track_package_hash"] is None
        assert document["circuit"]["run_label"] is None, (
            "a synthetic sketch session was exported with a real-circuit label"
        )
    finally:
        client.__exit__(None, None, None)


def test_the_identity_columns_are_migrated_not_only_declared(tmp_path: Path):
    """A column the ORM knows about and the migration does not is a restart bug.

    `main.py` runs `ensure_schema` on startup, so the columns under test are
    created by the migration chain rather than by `create_all`.
    """
    from sqlalchemy import inspect

    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'migrated.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app):
        columns = {c["name"] for c in inspect(app.state.database.engine).get_columns("session")}
        snapshot_columns = {
            c["name"] for c in inspect(app.state.database.engine).get_columns("simulation_snapshot")
        }

    expected = {
        "track_id",
        "track_package_hash",
        "event_id",
        "event_package_hash",
        "conditions_id",
        "conditions_hash",
        "track_readiness",
        "geometry_provenance",
    }
    print(f"\nmigrated session identity columns: {sorted(expected & columns)}")
    assert expected <= columns, f"the migration is missing {sorted(expected - columns)}"
    assert {"track_id", "track_package_hash"} <= snapshot_columns
