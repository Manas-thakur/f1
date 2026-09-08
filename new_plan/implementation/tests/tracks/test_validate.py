"""The independent validator derives readiness from evidence and nothing else."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from afterlap_core.paths import Paths
from afterlap_core.tracks import (
    CompiledCentreline,
    CorridorQuality,
    Direction,
    EventOverlay,
    ReadinessStatus,
    SourceRecord,
    TrackPackage,
)
from afterlap_core.tracks.loader import TrackPackageError, load_centreline, load_track_package
from afterlap_core.tracks.validate import (
    CONDITIONS_REPORT_RELATIVE,
    GEOMETRY_CHECKS,
    REPORT_FILENAME,
    validate_track,
)

from .conftest import SYNTHETIC_TRACK_ID, analytic_loop, build_package, write_package

HASHED_SOURCE = SourceRecord(
    source_id="synthetic-hashed",
    title="Synthetic analytic loop (test fixture, hash-pinned)",
    url="synthetic://tests/tracks/analytic-loop",
    retrieved_at="2026-09-08T00:00:00Z",
    sha256="0" * 64,
    permission="synthetic fixture; no external rights involved",
    priority=5,
)


def _discovered(centreline: CompiledCentreline, *, corridor: bool = False, **overrides) -> TrackPackage:
    """A compiler-style package: arrays present, status still discovered, source hash-pinned."""
    base = build_package(centreline=centreline, corridor=corridor, status=ReadinessStatus.GEOMETRY_VALIDATED)
    validation = base.validation.model_copy(
        update={"status": ReadinessStatus.DISCOVERED, "closure_error_m": None, "length_error_fraction": None}
    )
    validation = validation.model_copy(update={"official_length_m": centreline.length_m})
    return base.model_copy(update={"validation": validation, "sources": (HASHED_SOURCE,), **overrides})


def _write_raw_npz(paths: Paths, track_id: str, **arrays: np.ndarray) -> str:
    """Bypass CompiledCentreline so deliberately broken arrays reach the validator."""
    import hashlib

    path = paths.artifacts / "tracks" / track_id / "centreline.npz"
    with path.open("wb") as handle:
        np.savez(handle, **arrays)  # type: ignore[arg-type]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_package(paths: Paths, package: TrackPackage) -> None:
    (paths.artifacts / "tracks" / package.track_id / "package.json").write_text(
        json.dumps(package.to_schema_dict(), indent=2), encoding="utf-8"
    )


def _arrays_of(centreline: CompiledCentreline) -> dict[str, np.ndarray]:
    return {
        "s_m": centreline.s_m.copy(),
        "x_m": centreline.x_m.copy(),
        "y_m": centreline.y_m.copy(),
        "z_m": centreline.z_m.copy(),
        "yaw_rad": centreline.yaw_rad.copy(),
        "curvature_1pm": centreline.curvature_1pm.copy(),
        "grade_rad": centreline.grade_rad.copy(),
        "width_left_m": centreline.width_left_m.copy(),
        "width_right_m": centreline.width_right_m.copy(),
        "mu": centreline.mu.copy(),
        "length_m": np.asarray([centreline.length_m]),
    }


def _validate_with_arrays(tmp_path: Path, arrays: dict[str, np.ndarray], **overrides) -> TrackPackage:
    clean = analytic_loop()
    package, paths = write_package(tmp_path, _discovered(clean, **overrides), clean)
    digest = _write_raw_npz(paths, SYNTHETIC_TRACK_ID, **arrays)
    _rewrite_package(
        paths,
        package.model_copy(
            update={"geometry": package.geometry.model_copy(update={"arrays_sha256": digest})}
        ).with_hash(),
    )
    return validate_track(SYNTHETIC_TRACK_ID, paths)


# --------------------------------------------------------------------------- #
# passing geometry
# --------------------------------------------------------------------------- #


def test_a_clean_loop_reaches_geometry_validated_with_all_checks_passing(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    validated = validate_track(SYNTHETIC_TRACK_ID, paths)

    assert validated.validation.status is ReadinessStatus.GEOMETRY_VALIDATED
    assert all(validated.validation.checks[c] == "pass" for c in GEOMETRY_CHECKS), validated.validation.checks
    assert validated.validation.closure_error_m is not None and validated.validation.closure_error_m < 0.05
    assert validated.validation.length_error_fraction is not None
    assert validated.validation.length_error_fraction < 1e-4
    assert validated.validation.checks["corridor"] == "unknown"
    assert validated.validation.checks["event_overlay_confirmed"] == "unknown"
    assert validated.package_hash == validated.content_hash()

    report = json.loads((paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / REPORT_FILENAME).read_text())
    assert report["status"] == "geometry_validated"
    assert abs(report["numbers"]["recomputed_length_m"] - 2400.0) < 0.5
    # The frozen file on disk is the returned object and loads through the verifying loader.
    assert load_track_package(SYNTHETIC_TRACK_ID, paths) == validated
    load_centreline(SYNTHETIC_TRACK_ID, validated, paths)


def test_revalidating_a_validated_package_is_idempotent(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    first = validate_track(SYNTHETIC_TRACK_ID, paths)
    second = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert first == second
    assert first.package_hash == second.package_hash


def test_a_hand_edited_status_above_evidence_is_refused(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    path = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["validation"]["status"] = "simulation_eligible"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="requires"):
        validate_track(SYNTHETIC_TRACK_ID, paths)


def test_an_edited_but_structurally_valid_package_fails_hash_verification(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    path = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["nominal_length_m"] = 2500.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrackPackageError, match="hash verification"):
        validate_track(SYNTHETIC_TRACK_ID, paths)


def test_missing_package_is_a_named_error(tmp_path):
    from .conftest import scratch_paths

    with pytest.raises(TrackPackageError, match="no compiled package"):
        validate_track("nowhere", scratch_paths(tmp_path))


# --------------------------------------------------------------------------- #
# each check fails on a centreline built to fail it
# --------------------------------------------------------------------------- #


def test_open_loop_fails_closure_and_stays_discovered(tmp_path):
    arrays = _arrays_of(analytic_loop())
    # Shear the second half sideways so the ends no longer meet; the geometry
    # stays smooth so no integrity check fires.
    n = len(arrays["s_m"])
    ramp = np.linspace(0.0, 3.0, n)
    arrays["x_m"] = arrays["x_m"] + ramp
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["closure"] == "fail"
    assert result.validation.status is ReadinessStatus.DISCOVERED
    assert result.validation.closure_error_m is not None and result.validation.closure_error_m > 0.5


def test_length_disagreement_with_official_reference_blocks_publication(tmp_path):
    centreline = analytic_loop()
    package = _discovered(centreline)
    package = package.model_copy(
        update={"validation": package.validation.model_copy(update={"official_length_m": 2450.0})}
    )
    _, paths = write_package(tmp_path, package, centreline)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["length_official"] == "fail"
    assert result.validation.checks["length_declared"] == "pass"
    assert result.validation.status is ReadinessStatus.DISCOVERED
    frac = result.validation.length_error_fraction
    assert frac is not None and abs(frac - 50.0 / 2450.0) < 1e-3


def test_declared_length_disagreement_fails(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["length_m"] = np.asarray([2430.0])
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["length_declared"] == "fail"
    assert result.validation.status is ReadinessStatus.DISCOVERED


def test_manifest_official_length_and_tolerance_are_honoured(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    configs = tmp_path / "configs"
    (configs / "tracks" / SYNTHETIC_TRACK_ID).mkdir(parents=True)
    (configs / "tracks" / SYNTHETIC_TRACK_ID / "source.yaml").write_text(
        "track_id: synthetic-oval-package\n"
        "official_length_m:\n  value: 2410\n  source_url: synthetic://official\n"
        "length_tolerance_fraction: 0.001\n",
        encoding="utf-8",
    )
    paths = dataclasses.replace(paths, configs=configs)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.official_length_m == 2410.0
    assert result.validation.checks["length_official"] == "fail"  # 0.4 % > 0.1 % manifest tolerance
    assert any("taken from source manifest" in n for n in result.validation.notes)


def test_non_monotonic_s_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["s_m"][100] = arrays["s_m"][99]
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["s_monotonic_spacing"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_wrong_spacing_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["s_m"] = arrays["s_m"] * 0.5
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["s_monotonic_spacing"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_nan_in_a_required_array_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["z_m"][10] = np.nan
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["no_nan"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED
    assert result.validation.closure_error_m is None


def test_yaw_inconsistent_with_tangent_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["yaw_rad"] = arrays["yaw_rad"] + 0.2
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["yaw_tangent"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_curvature_inconsistent_with_yaw_derivative_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["curvature_1pm"] = arrays["curvature_1pm"] + 0.01  # still bounded, no longer d(yaw)/ds
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["curvature_yaw"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_curvature_out_of_bounds_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["curvature_1pm"][500] = 0.5
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["curvature_bounded"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_grade_out_of_bounds_is_rejected(tmp_path):
    arrays = _arrays_of(analytic_loop())
    arrays["grade_rad"][700] = 0.4
    result = _validate_with_arrays(tmp_path, arrays)
    assert result.validation.checks["grade_bounded"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_direction_contradicting_signed_area_is_rejected(tmp_path):
    centreline = analytic_loop()  # counterclockwise by construction
    _, paths = write_package(tmp_path, _discovered(centreline, direction=Direction.CLOCKWISE), centreline)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["direction"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_mixed_direction_is_unknown_not_failed(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline, direction=Direction.MIXED), centreline)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["direction"] == "unknown"
    assert result.validation.status is ReadinessStatus.DISCOVERED


def test_tampered_arrays_fail_the_hash_check_and_are_rejected(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    analytic_loop(length_m=2401.0).to_npz(paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "centreline.npz")
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["arrays_sha256"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED


def test_unpinned_sources_block_publication(tmp_path):
    centreline = analytic_loop()
    package = build_package(centreline=centreline)  # conftest source has no sha256
    package = package.model_copy(
        update={
            "validation": package.validation.model_copy(
                update={
                    "status": ReadinessStatus.DISCOVERED,
                    "closure_error_m": None,
                    "length_error_fraction": None,
                    "official_length_m": centreline.length_m,
                }
            )
        }
    )
    _, paths = write_package(tmp_path, package, centreline)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["sources_hashed"] == "fail"
    assert result.validation.status is ReadinessStatus.DISCOVERED


def test_missing_centreline_file_leaves_geometry_unknown(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    (paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "centreline.npz").unlink()
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.status is ReadinessStatus.DISCOVERED
    assert result.validation.checks["closure"] == "unknown"


# --------------------------------------------------------------------------- #
# the upper rungs need their own evidence
# --------------------------------------------------------------------------- #


def _confirmed_overlay(event_id: str = "2026-synthetic") -> EventOverlay:
    return EventOverlay(
        event_id=event_id,
        ruleset_hash="synthetic",
        detection_lines_m=(1200.0,),
        activation_lines_m=(1350.0,),
        review_status="confirmed",
        reviewers=("reviewer-a", "reviewer-b"),
    )


def _queue_overlay(paths: Paths, overlay: EventOverlay) -> None:
    events = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / "events"
    events.mkdir(parents=True, exist_ok=True)
    (events / f"{overlay.event_id}.json").write_text(
        json.dumps(overlay.model_dump(mode="json")), encoding="utf-8"
    )


def test_an_unreviewed_overlay_does_not_lift_the_status(tmp_path):
    centreline = analytic_loop()
    _, paths = write_package(tmp_path, _discovered(centreline), centreline)
    _queue_overlay(
        paths, _confirmed_overlay().model_copy(update={"review_status": "unreviewed", "reviewers": ()})
    )
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.status is ReadinessStatus.GEOMETRY_VALIDATED
    assert result.event_overlay is None


def test_a_confirmed_overlay_lifts_to_event_rules_validated_only(tmp_path):
    centreline = analytic_loop(corridor=True)
    _, paths = write_package(tmp_path, _discovered(centreline, corridor=True), centreline)
    _queue_overlay(paths, _confirmed_overlay())
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    # Corridor is known and the overlay confirmed, but no condition calibration exists.
    assert result.validation.status is ReadinessStatus.EVENT_RULES_VALIDATED
    assert result.event_overlay is not None and result.event_overlay.event_id == "2026-synthetic"
    assert result.validation.checks["corridor"] == "pass"
    assert result.validation.checks["conditions_calibrated"] == "unknown"


def test_full_evidence_reaches_simulation_eligible_and_unknown_corridor_stops_short(tmp_path):
    for corridor, expected in (
        (True, ReadinessStatus.SIMULATION_ELIGIBLE),
        (False, ReadinessStatus.CONDITION_CALIBRATED),
    ):
        root = tmp_path / ("corridor" if corridor else "nocorridor")
        root.mkdir()
        centreline = analytic_loop(corridor=corridor)
        _, paths = write_package(root, _discovered(centreline, corridor=corridor), centreline)
        _queue_overlay(paths, _confirmed_overlay())
        report = paths.artifacts / "tracks" / SYNTHETIC_TRACK_ID / CONDITIONS_REPORT_RELATIVE
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"status": "calibrated", "source_sessions": [9912]}), encoding="utf-8")
        result = validate_track(SYNTHETIC_TRACK_ID, paths)
        assert result.validation.status is expected, corridor
        assert load_track_package(SYNTHETIC_TRACK_ID, paths) == result


def test_a_corridor_claim_without_finite_widths_is_rejected(tmp_path):
    centreline = analytic_loop()  # widths are nan
    package = _discovered(centreline)
    package = package.model_copy(
        update={
            "geometry": package.geometry.model_copy(update={"corridor_quality": CorridorQuality.SURVEYED})
        }
    )
    _, paths = write_package(tmp_path, package, centreline)
    result = validate_track(SYNTHETIC_TRACK_ID, paths)
    assert result.validation.checks["corridor"] == "fail"
    assert result.validation.status is ReadinessStatus.REJECTED
