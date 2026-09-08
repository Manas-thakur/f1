"""Circuit-package fixtures for the catalogue and session-identity suites.

A16-8 shipped the catalogue and session-identity routes with no tests. What
they need is not real telemetry: it is a compiled package tree in each of the
states the routes have to describe. So this module writes **synthetic** package
trees into a temporary ``artifacts/tracks/`` and points the application at
them.

Every package built here is a closed analytic loop. It is written under a
registry circuit id because the routes resolve registry identity, event
overlays and readiness by id, and those paths cannot be exercised under a name
the registry does not know. **No package here is that circuit's geometry**, and
nothing asserted from one is a claim about a real circuit. `synthetic_sketch`
in the geometry provenance says so in the payload itself.

Four states are represented, matching the four the catalogue distinguishes:

* **absent**: a registry id with no package directory at all;
* **discovered**: a compiled package below the readiness rung that may drive;
* **rejected**: a package the validator refused;
* **validated**: ``geometry_validated``, the rung a session may run on.

Imported relatively (``from .conftest import ...``) per coordinator decision
D-03: `tests/` is not a Python package, and a small duplicated builder beats a
path hack into another worker's suite.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from fastapi.testclient import TestClient

from afterlap_api.db import create_all
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

SCENARIO_ID = "two-straight-counterattack"
RULE_PACK_ID = "synthetic-pack-v1"
SEED = 42

VALIDATED_TRACK = "spa"
DISCOVERED_TRACK = "monaco"
REJECTED_TRACK = "suzuka"
ABSENT_TRACK = "melbourne"
UNREGISTERED_TRACK = "synthetic-oval-fixture"
"""Deliberately not in the 2026 registry: the loader must not be keyed on ids."""

FIXTURE_LENGTH_M = 4000.0
"""Long enough for `synthetic-pack-v1`'s detection lines, which reach 3500 m."""

ATTACK_EXIT_S_M = 2100.0
COUNTERATTACK_EXIT_S_M = 3500.0

FIXTURE_LICENCE = "synthetic fixture; no external rights involved"


def analytic_loop(length_m: float = FIXTURE_LENGTH_M) -> CompiledCentreline:
    """A circle of the requested length sampled every metre (synthetic fixture)."""
    count = int(length_m)
    s = np.arange(count, dtype=float)
    radius = length_m / (2.0 * np.pi)
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
        length_m=length_m,
    )


def build_package(
    track_id: str,
    *,
    status: ReadinessStatus = ReadinessStatus.GEOMETRY_VALIDATED,
    centreline: CompiledCentreline | None = None,
) -> TrackPackage:
    """A package document whose checkpoints match the shipped test scenario.

    The corners are named after the scenario's evaluation checkpoints, because
    a compiled source derives its checkpoints from the package's own corners
    and sectors. A package without them is refused by the session factory,
    which is itself one of the behaviours under test.
    """
    centreline = centreline or analytic_loop()
    compiled = status is not ReadinessStatus.DISCOVERED
    return TrackPackage(
        track_id=track_id,
        display_name=f"Synthetic analytic loop written as {track_id} (fixture)",
        direction=Direction.COUNTERCLOCKWISE,
        nominal_length_m=centreline.length_m,
        geometry=GeometryDescriptor(
            sample_spacing_m=1.0,
            point_count=centreline.point_count if compiled else 0,
            crs="local-enu",
            arrays_path="centreline.npz" if compiled else None,
            corridor_quality=CorridorQuality.UNKNOWN,
            provenance=GeometryProvenance.SYNTHETIC_SKETCH,
        ),
        features=TrackFeatures(
            start_finish_s_m=0.0,
            sectors=(
                SRange(start_s_m=0.0, end_s_m=1400.0),
                SRange(start_s_m=1400.0, end_s_m=2800.0),
                SRange(start_s_m=2800.0, end_s_m=FIXTURE_LENGTH_M),
            ),
            corners=(
                NamedRange(id="attack-exit", start_s_m=1900.0, end_s_m=ATTACK_EXIT_S_M),
                NamedRange(id="counterattack-exit", start_s_m=3300.0, end_s_m=COUNTERATTACK_EXIT_S_M),
            ),
        ),
        sources=(
            SourceRecord(
                source_id="synthetic-analytic-loop",
                title="Synthetic analytic loop (test fixture)",
                url="synthetic://tests/api/analytic-loop",
                retrieved_at="2026-09-08T00:00:00Z",
                permission=FIXTURE_LICENCE,
                priority=5,
            ),
        ),
        validation=ValidationReport(
            status=status,
            closure_error_m=0.0 if compiled else None,
            length_error_fraction=0.0 if compiled else None,
            report_path="validation_report.json" if compiled else None,
            checks={"closure": "pass", "length": "pass"} if compiled else {},
            notes=("synthetic fixture; not this circuit's geometry",),
        ),
    )


def scratch_paths(root: Path) -> Paths:
    """The shipped ``configs/`` with a temporary ``artifacts/`` tree.

    Configuration documents stay where the application reads them; only the
    artefact tree moves. That is exactly how `main.py`'s lifespan arranges a
    running install, so these drills exercise the real path resolution.
    """
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


def write_package(
    paths: Paths, package: TrackPackage, centreline: CompiledCentreline | None = None
) -> TrackPackage:
    """Freeze a package into ``artifacts/tracks/<id>/`` the way the compiler does."""
    directory = paths.artifacts / "tracks" / package.track_id
    directory.mkdir(parents=True, exist_ok=True)
    geometry = package.geometry
    if package.validation.status is not ReadinessStatus.DISCOVERED:
        digest = (centreline or analytic_loop()).to_npz(directory / "centreline.npz")
        geometry = geometry.model_copy(update={"arrays_sha256": digest})
    frozen = package.model_copy(update={"geometry": geometry}).with_hash()
    (directory / "package.json").write_text(json.dumps(frozen.to_schema_dict(), indent=2), encoding="utf-8")
    return frozen


def package_document_path(paths: Paths, track_id: str) -> Path:
    return paths.artifacts / "tracks" / track_id / "package.json"


@pytest.fixture
def catalogue_paths(tmp_path: Path) -> Paths:
    """An artefact tree holding one package in each catalogue state."""
    paths = scratch_paths(tmp_path).ensure()
    write_package(paths, build_package(VALIDATED_TRACK))
    write_package(paths, build_package(DISCOVERED_TRACK, status=ReadinessStatus.DISCOVERED))
    write_package(paths, build_package(REJECTED_TRACK, status=ReadinessStatus.REJECTED))
    write_package(paths, build_package(UNREGISTERED_TRACK))
    return paths


@pytest.fixture
def client(tmp_path: Path, catalogue_paths: Paths):
    """The real application, reading the fixture artefact tree.

    Both the catalogue and the session factory are pointed at the same
    ``Paths``. They must be: the catalogue exists so an operator can check a
    hash against the one a session used, and two trees would make that
    comparison meaningless.
    """
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
        )
    )
    with TestClient(app) as test_client:
        create_all(app.state.database.engine)
        factory = app.state.session_factory
        app.state.session_factory = SessionFactory(
            paths=catalogue_paths,
            planner=factory._planner,
            recorder_factory=factory._recorder_factory,
        )
        app.state.track_paths = catalogue_paths
        test_client.app_instance = app  # type: ignore[attr-defined]
        yield test_client


def create_session(client, *, idempotency_key: str, **overrides):  # type: ignore[no-untyped-def]
    body = {
        "mode": "simulation",
        "scenario_id": SCENARIO_ID,
        "ruleset_id": RULE_PACK_ID,
        "seed": SEED,
    }
    body.update(overrides)
    return client.post("/api/v1/sessions", json=body, headers={"Idempotency-Key": idempotency_key})


def track_summary(payload: dict, track_id: str) -> dict:
    for entry in payload["tracks"]:
        if entry["track_id"] == track_id:
            return entry
    raise AssertionError(f"{track_id} is not in the catalogue listing")
