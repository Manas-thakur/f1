"""A package loads only when its hashes verify and its readiness is earned."""

from __future__ import annotations

import json

import pytest

from afterlap_core.simulation.config import load_track
from afterlap_core.simulation.track_source import CompiledTrackSource, TrackSource
from afterlap_core.tracks import ReadinessStatus
from afterlap_core.tracks.loader import (
    TrackPackageError,
    list_track_packages,
    load_centreline,
    load_track_package,
    load_track_package_source,
    require_readiness,
)

from .conftest import SYNTHETIC_TRACK_ID, analytic_loop, build_package, write_package


def test_a_frozen_package_loads_and_verifies(frozen_package):
    package, paths = frozen_package
    loaded = load_track_package(SYNTHETIC_TRACK_ID, paths)
    assert loaded == package
    centreline = load_centreline(SYNTHETIC_TRACK_ID, loaded, paths)
    assert centreline.point_count == package.geometry.point_count
    assert list_track_packages(paths) == (SYNTHETIC_TRACK_ID,)


def test_a_tampered_package_document_is_refused(frozen_package):
    _, paths = frozen_package
    path = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["nominal_length_m"] = payload["nominal_length_m"] + 1.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrackPackageError, match="hash verification"):
        load_track_package(SYNTHETIC_TRACK_ID, paths)


def test_a_tampered_centreline_is_refused(frozen_package):
    package, paths = frozen_package
    analytic_loop(length_m=2401.0).to_npz(paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "centreline.npz")
    with pytest.raises(TrackPackageError, match="hash verification"):
        load_centreline(SYNTHETIC_TRACK_ID, package, paths)


def test_an_unhashed_package_is_refused(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, build_package(centreline=centreline), centreline)
    path = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["package_hash"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrackPackageError, match="never frozen"):
        load_track_package(SYNTHETIC_TRACK_ID, paths)


def test_a_discovered_package_cannot_drive_the_simulator(tmp_path):
    centreline = analytic_loop()
    package = build_package(status=ReadinessStatus.DISCOVERED, centreline=centreline)
    _, paths = write_package(tmp_path, package, centreline)
    with pytest.raises(TrackPackageError, match="discovered; geometry_validated is required"):
        load_track_package_source(SYNTHETIC_TRACK_ID, paths)


def test_require_readiness_names_both_rungs(frozen_package):
    package, _ = frozen_package
    require_readiness(package, ReadinessStatus.GEOMETRY_VALIDATED)
    with pytest.raises(TrackPackageError, match="simulation_eligible is required"):
        require_readiness(package, ReadinessStatus.SIMULATION_ELIGIBLE)


def test_load_track_falls_back_to_the_package_and_yields_a_track_source(frozen_package):
    package, paths = frozen_package
    source = load_track(SYNTHETIC_TRACK_ID, paths)
    assert isinstance(source, CompiledTrackSource)
    assert isinstance(source, TrackSource)
    assert source.config_hash == package.package_hash
    assert source.synthetic is False
    assert source.geometry_provenance == "synthetic_sketch"
    assert source.lateral_geometry_surveyed is False
    assert set(source.checkpoint_ids) >= {"turn-1", "sector-1-end", "sector-2-end", "sector-3-end"}


def test_an_unknown_track_id_is_still_not_found(tmp_path):
    _, paths = write_package(tmp_path, build_package(), analytic_loop())
    with pytest.raises(FileNotFoundError, match="neither a synthetic sketch"):
        load_track("no-such-circuit", paths)
