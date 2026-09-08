"""Builders for the track-package suite.

Every package built here is **synthetic**: a closed analytic loop written into
a temporary ``artifacts/tracks/<id>/`` tree so the loader, hash verification and
readiness rules can be exercised without any real-circuit data. Nothing here
claims to be a real circuit.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

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

SYNTHETIC_TRACK_ID = "synthetic-oval-package"
SYNTHETIC_LENGTH_M = 2400.0


def analytic_loop(length_m: float = SYNTHETIC_LENGTH_M, *, corridor: bool = False) -> CompiledCentreline:
    """A circle of the requested length sampled every metre (synthetic fixture)."""
    n = int(length_m)
    s = np.arange(n, dtype=float)
    radius = length_m / (2.0 * np.pi)
    theta = s / radius
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)
    z = 2.0 * np.sin(theta)
    yaw = theta + np.pi / 2.0
    curvature = np.full(n, 1.0 / radius)
    grade = np.gradient(z, s)
    widths = (np.full(n, 6.0), np.full(n, 6.0)) if corridor else (None, None)
    return CompiledCentreline(
        s_m=s,
        x_m=x,
        y_m=y,
        z_m=z,
        yaw_rad=yaw,
        curvature_1pm=curvature,
        grade_rad=grade,
        length_m=length_m,
        width_left_m=widths[0],
        width_right_m=widths[1],
    )


def synthetic_source() -> SourceRecord:
    return SourceRecord(
        source_id="synthetic-oval",
        title="Synthetic analytic loop (test fixture)",
        url="synthetic://tests/tracks/analytic-loop",
        retrieved_at="2026-09-08T00:00:00Z",
        permission="synthetic fixture; no external rights involved",
        priority=5,
    )


def build_package(
    *,
    track_id: str = SYNTHETIC_TRACK_ID,
    status: ReadinessStatus = ReadinessStatus.GEOMETRY_VALIDATED,
    corridor: bool = False,
    centreline: CompiledCentreline | None = None,
    arrays_sha256: str | None = None,
) -> TrackPackage:
    centreline = centreline or analytic_loop(corridor=corridor)
    validated = status is not ReadinessStatus.DISCOVERED
    return TrackPackage(
        track_id=track_id,
        display_name="Synthetic oval (fixture)",
        direction=Direction.COUNTERCLOCKWISE,
        nominal_length_m=centreline.length_m,
        geometry=GeometryDescriptor(
            sample_spacing_m=1.0,
            point_count=centreline.point_count if validated else 0,
            crs="local-enu",
            arrays_path="centreline.npz" if validated else None,
            corridor_quality=CorridorQuality.VALIDATED_ESTIMATE if corridor else CorridorQuality.UNKNOWN,
            provenance=GeometryProvenance.SYNTHETIC_SKETCH,
            arrays_sha256=arrays_sha256,
        ),
        features=TrackFeatures(
            start_finish_s_m=0.0,
            sectors=(
                SRange(start_s_m=0.0, end_s_m=800.0),
                SRange(start_s_m=800.0, end_s_m=1600.0),
                SRange(start_s_m=1600.0, end_s_m=2400.0),
            ),
            corners=(NamedRange(id="turn-1", start_s_m=300.0, end_s_m=420.0),),
        ),
        sources=(synthetic_source(),),
        validation=ValidationReport(
            status=status,
            closure_error_m=0.0 if validated else None,
            length_error_fraction=0.0 if validated else None,
            checks={"closure": "pass", "length": "pass"} if validated else {},
            notes=("synthetic fixture",),
        ),
    )


def scratch_paths(root: Path) -> Paths:
    """Real ``configs/`` (cars, scenarios) with a temporary ``artifacts/`` tree."""
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
    root: Path, package: TrackPackage, centreline: CompiledCentreline
) -> tuple[TrackPackage, Paths]:
    """Freeze a package into ``root/artifacts/tracks/<id>/`` the way the compiler will."""
    paths = scratch_paths(root)
    directory = paths.artifacts / "tracks" / package.track_id
    directory.mkdir(parents=True)
    digest = centreline.to_npz(directory / "centreline.npz")
    frozen = package.model_copy(
        update={"geometry": package.geometry.model_copy(update={"arrays_sha256": digest})}
    ).with_hash()
    (directory / "package.json").write_text(json.dumps(frozen.to_schema_dict(), indent=2), encoding="utf-8")
    return frozen, paths


@pytest.fixture
def frozen_package(tmp_path: Path) -> tuple[TrackPackage, Paths]:
    centreline = analytic_loop()
    return write_package(tmp_path, build_package(centreline=centreline), centreline)


@pytest.fixture
def frozen_package_with_corridor(tmp_path: Path) -> tuple[TrackPackage, Paths]:
    centreline = analytic_loop(corridor=True)
    return write_package(tmp_path, build_package(corridor=True, centreline=centreline), centreline)
