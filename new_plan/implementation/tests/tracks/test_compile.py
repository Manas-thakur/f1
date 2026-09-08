"""Centreline compiler: primitives on analytic shapes, then the full pipeline on the synthetic fixture.

No network: the OpenF1 payloads are the synthetic fixture pre-loaded into the raw
cache exactly as ``test_openf1_ingest`` does.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import yaml

from afterlap_core.tracks import CorridorQuality, Direction, GeometryProvenance, ReadinessStatus
from afterlap_core.tracks.compile import (
    LOCAL_CRS,
    CompileError,
    choose_smoothing_across_laps,
    clean_samples,
    compile_track,
    fit_periodic_spline,
    infer_scale,
    loop_direction,
    process_lap,
    raw_finite_difference_curvature,
    register_and_aggregate,
    resample_by_arclength,
)
from afterlap_core.tracks.ingest.openf1 import DEFAULT_MAX_LAPS, LapRecord, ingest_location_session
from afterlap_core.tracks.loader import load_centreline, load_track_package
from afterlap_core.tracks.provenance import RawSourceCache

from .conftest import scratch_paths
from .test_openf1_ingest import load_fixture, seed_cache


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


# -- analytic primitives ------------------------------------------------------------- #


def noisy_circle(
    radius_m: float, *, speed_mps: float = 55.0, hz: float = 3.7, noise_m: float = 0.25, seed: int = 1
):
    """One lap of a circle sampled the way OpenF1 samples: sparse in space, noisy in position."""
    rng = np.random.default_rng(seed)
    length = 2.0 * np.pi * radius_m
    dt = 1.0 / hz
    n = int(length / speed_mps / dt)
    t = np.arange(n) * dt
    theta = (t * speed_mps) / radius_m
    xyz = np.column_stack([radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros(n)])
    xyz[:, :2] += rng.normal(0.0, noise_m, size=(n, 2))
    return t, xyz, length


def circle_laps(radius_m: float, n_laps: int, *, seed: int = 0) -> list:
    """``n_laps`` independent noisy laps of one circle, processed exactly as the compiler does."""
    speed, hz = 55.0, 3.7
    duration = 2.0 * np.pi * radius_m / speed
    laps = []
    for k in range(n_laps):
        rng = np.random.default_rng(seed + k)
        t = np.arange(-1.0, duration + 1.0, 1.0 / hz) + rng.uniform(0.0, 1.0 / hz)
        theta = t * speed / radius_m
        xyz = np.column_stack([radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros_like(t)])
        xyz[:, :2] += rng.normal(0.0, 0.25, size=(len(t), 2))
        laps.append(process_lap(_lap_record(k + 2, duration), t, xyz, scale=1.0, origin_units=np.zeros(3)))
    return laps


def test_smoothed_curvature_of_a_noisy_circle_is_within_two_percent_but_raw_differences_are_not():
    """The compiler's multi-lap product, on a circle sampled like OpenF1 (3.7 Hz, 0.25 m noise).

    Raw three-point curvature of the same samples is useless; the aggregated,
    penalised-spline curvature is within 2 % of 1/R at every 1 m sample. A
    single lap alone does not reach 2 % (about 5 % at the hold-out-chosen
    bandwidth); that limitation is stated in the handoff, not hidden here.
    """
    radius = 300.0
    kappa_true = 1.0 / radius
    laps = circle_laps(radius, DEFAULT_MAX_LAPS)

    raw = np.concatenate([raw_finite_difference_curvature(lap.xyz_m[:, :2]) for lap in laps])
    raw_rel_error = np.abs(raw - kappa_true) / kappa_true
    assert np.percentile(raw_rel_error, 50) > 0.02, (
        "raw three-point curvature should be visibly noisy at 3.7 Hz"
    )

    aggregated, _ = register_and_aggregate(laps)
    selection = choose_smoothing_across_laps(laps)
    line = resample_by_arclength(fit_periodic_spline(aggregated, selection.chosen_bandwidth_m))
    rel_error = np.abs(line.curvature_1pm - kappa_true) / kappa_true
    assert np.max(rel_error) < 0.02, f"smoothed curvature off by up to {np.max(rel_error) * 100:.2f} %"
    assert np.all(line.curvature_1pm > 0.0)  # counterclockwise: positive curvature throughout
    # Canonical storage is one sample per metre starting at 0 and stopping short of
    # the closing sample, so a loop of non-integer length carries ceil(L) samples.
    assert line.s_m[0] == 0.0
    assert line.s_m[-1] < line.length_3d_m
    assert np.allclose(np.diff(line.s_m), 1.0)
    assert len(line.s_m) == int(np.ceil(line.length_3d_m))
    assert line.length_3d_m == pytest.approx(2.0 * np.pi * radius, rel=1e-3)
    # Both selection metrics were recorded for every candidate, and a heavier smoothing than the
    # chosen one is measurably worse on held-out laps (bias), not merely unexplored.
    assert all(c.holdout_rms_m > 0.0 and c.curvature_stability_rms_1pm >= 0.0 for c in selection.candidates)
    heavier = [c for c in selection.candidates if c.bandwidth_m > selection.chosen_bandwidth_m]
    assert heavier and max(c.holdout_rms_m for c in heavier) > min(
        c.holdout_rms_m for c in selection.candidates
    )


def test_a_knot_dropping_smoother_is_not_what_we_use_heavy_smoothing_keeps_a_circle_circular():
    """Heavier smoothing of a circle must not make its curvature oscillate (the splprep failure mode)."""
    _, xyz, _ = noisy_circle(300.0)
    for bandwidth in (20.0, 45.0):
        line = resample_by_arclength(fit_periodic_spline(xyz, bandwidth))
        spread = np.std(line.curvature_1pm) / np.mean(line.curvature_1pm)
        assert spread < 0.05, f"bandwidth {bandwidth}: curvature spread {spread:.3f}"


def test_scale_inference_needs_evidence_and_records_it():
    dm = infer_scale(57_600.0, 5793.0)
    assert dm.chosen_unit == "dm" and dm.scale_m_per_unit == 0.1 and dm.accepted
    assert "57600.0 units" in dm.evidence and "5793.0 m" in dm.evidence
    metres = infer_scale(5810.0, 5793.0)
    assert metres.chosen_unit == "m" and metres.accepted
    nonsense = infer_scale(20_000.0, 5793.0)  # 0.29 m/unit fits no decimal hypothesis
    assert not nonsense.accepted
    with pytest.raises(CompileError):
        infer_scale(0.0, 5793.0)


def test_duplicate_and_jump_removal_uses_cadence_and_speed_thresholds():
    t, xyz, _ = noisy_circle(300.0)
    t = list(t)
    p = list(xyz)
    # exact duplicate, time duplicate (20 ms later, 0.3 m away) and an isolated 700 m jump
    t.insert(41, t[40])
    p.insert(41, p[40].copy())
    t.insert(81, t[80] + 0.02)
    p.insert(81, p[80] + np.array([0.3, 0.0, 0.0]))
    p[120] = p[120] + np.array([500.0, -400.0, 0.0])
    t_arr = np.asarray(t)
    p_arr = np.vstack(p)

    t_out, p_out, report = clean_samples(t_arr, p_arr)
    assert report.samples_in == len(t_arr)
    assert report.exact_duplicates == 1
    assert report.time_duplicates == 1
    assert report.jumps == 1
    assert report.samples_out == len(t_arr) - 3 == len(t_out) == len(p_out)
    assert report.median_dt_s == pytest.approx(1.0 / 3.7, rel=1e-6)
    assert report.duplicate_dt_threshold_s == pytest.approx(0.25 / 3.7, rel=1e-6)
    assert np.all(np.diff(t_out) > 0.0)
    # no remaining segment implies a speed above the ceiling
    seg = np.hypot(np.diff(p_out[:, 0]), np.diff(p_out[:, 1])) / np.diff(t_out)
    assert np.max(seg) < report.speed_ceiling_mps


def test_timing_line_alignment_rotates_without_changing_length():
    _, xyz, _ = noisy_circle(250.0)
    tck = fit_periodic_spline(xyz, 20.0)
    base = resample_by_arclength(tck)
    shifted = resample_by_arclength(tck, s_offset_m=base.length_3d_m * 0.37)
    assert shifted.length_3d_m == base.length_3d_m
    assert shifted.length_2d_m == base.length_2d_m
    assert np.array_equal(shifted.s_m, base.s_m)
    # the shifted line starts where the base line was 37 % of the way round
    idx = round(base.length_3d_m * 0.37)
    assert np.hypot(*(shifted.xyz_m[0, :2] - base.xyz_m[idx, :2])) < 1.0
    # and its curvature is the same set of values, rotated
    assert np.max(np.abs(np.roll(base.curvature_1pm, -idx) - shifted.curvature_1pm)) < 1e-3


def test_direction_from_progression():
    theta = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    ccw = np.column_stack([np.cos(theta), np.sin(theta)]) * 100.0
    assert loop_direction(ccw) is Direction.COUNTERCLOCKWISE
    assert loop_direction(ccw[::-1]) is Direction.CLOCKWISE
    # a figure-eight has no net turning
    eight = np.column_stack([np.sin(theta), np.sin(theta) * np.cos(theta)]) * 100.0
    assert loop_direction(eight) is Direction.MIXED


def _lap_record(lap_number: int, duration_s: float) -> LapRecord:
    return LapRecord(
        lap_number=lap_number,
        driver_number=1,
        date_start="2025-01-01T12:00:00.000000+00:00",
        lap_duration_s=duration_s,
        window_start="",
        window_end="",
        sector_durations_s=(None, None, None),
        location_sha256="0" * 64,
        location_url="synthetic://lap",
        sample_count=0,
        retrieved_at="2025-01-01T12:00:00Z",
    )


def test_non_closing_lap_is_refused():
    """A lap whose end is far from its start (a spiral) cannot be a circuit lap."""
    speed, hz, radius = 55.0, 3.7, 300.0
    dt = 1.0 / hz
    duration = 2.0 * np.pi * radius / speed
    t = np.arange(-1.0, duration + 1.0, dt)
    theta = t * speed / radius
    r = radius * (1.0 + 0.25 * np.clip(t, 0.0, duration) / duration)  # ends 75 m out from where it started
    xyz = np.column_stack([r * np.cos(theta), r * np.sin(theta), np.zeros_like(t)])
    with pytest.raises(CompileError, match="does not close"):
        process_lap(_lap_record(5, duration), t, xyz, scale=1.0, origin_units=np.zeros(3))

    closed = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.zeros_like(t)])
    geometry = process_lap(_lap_record(5, duration), t, closed, scale=1.0, origin_units=np.zeros(3))
    assert geometry.spline_length_m == pytest.approx(2.0 * np.pi * radius, rel=1e-3)


def test_lap_window_must_bracket_the_timing_line():
    speed, hz, radius = 55.0, 3.7, 300.0
    duration = 2.0 * np.pi * radius / speed
    t = np.arange(0.5, duration - 0.5, 1.0 / hz)  # starts after the boundary time
    theta = t * speed / radius
    xyz = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.zeros_like(t)])
    with pytest.raises(CompileError, match="bracket"):
        process_lap(_lap_record(5, duration), t, xyz, scale=1.0, origin_units=np.zeros(3))


# -- full pipeline on the synthetic fixture ------------------------------------------- #


def write_manifest(path: Path, *, official_length_m: float, direction: str = "counterclockwise") -> Path:
    doc = {
        "track_id": "synthetic-loop",
        "display_name": "Synthetic loop (fixture)",
        "direction": direction,
        "official_length_m": {
            "value": official_length_m,
            "source_url": "synthetic://fixture/official-length",
            "retrieved_at": "2025-01-01T00:00:00Z",
            "title": "Synthetic analytic length",
            "permission": "synthetic fixture",
        },
        "openf1": {
            "sessions": [{"session_key": 900001, "year": 2025, "session_name": "Race", "driver_number": None}]
        },
        "fia_documents": [],
        "permissions": {"openf1": "synthetic fixture"},
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def ingested(tmp_path):
    fixture = load_fixture()
    paths = scratch_paths(tmp_path)
    cache = RawSourceCache(paths=paths)
    seed_cache(cache, fixture)
    ingest_location_session(fixture["session_key"], "synthetic-loop", paths, cache=cache)
    return fixture, paths


def test_compile_writes_a_discovered_package_with_verified_arrays(ingested):
    fixture, paths = ingested
    truth = fixture["truth"]
    manifest = write_manifest(paths.artifacts / "manifest.yaml", official_length_m=truth["length_m"])
    package = compile_track(manifest, paths)

    assert package.validation.status is ReadinessStatus.DISCOVERED
    assert package.geometry.provenance is GeometryProvenance.OPENF1_LOCATION_TELEMETRY
    assert package.geometry.corridor_quality is CorridorQuality.UNKNOWN
    assert package.geometry.crs == LOCAL_CRS
    assert package.direction is Direction.COUNTERCLOCKWISE
    assert package.nominal_length_m == truth["length_m"]
    assert package.package_hash is not None

    loaded = load_track_package("synthetic-loop", paths)
    assert loaded == package
    centreline = load_centreline("synthetic-loop", loaded, paths)
    assert not centreline.corridor_known
    assert np.all(np.isnan(centreline.mu))
    assert centreline.closure_error_m < 0.5
    assert abs(centreline.length_m - truth["length_m"]) / truth["length_m"] < 0.01
    assert package.validation.length_error_fraction == pytest.approx(
        abs(centreline.length_m - truth["length_m"]) / truth["length_m"]
    )
    assert package.validation.closure_error_m == pytest.approx(centreline.closure_error_m)
    assert len(package.sources) == 1 + 2 + 3  # official length + sessions + laps + three location pages
    assert package.sources[0].source_id == "official-length-synthetic-loop"
    assert all(s.sha256 for s in package.sources[1:])

    report = json.loads((paths.artifacts / "tracks" / "synthetic-loop" / "compile_report.json").read_text())
    assert report["frame"]["scale"]["chosen_unit"] == "dm"
    assert report["frame"]["scale"]["scale_m_per_unit"] == truth["scale_m_per_unit"]
    assert "implies" in report["frame"]["scale"]["evidence"]
    assert report["flags"] == []
    assert [lap["lap_number"] for lap in report["laps"]] == [5, 6, 7]
    lap6 = next(lap for lap in report["laps"] if lap["lap_number"] == 6)
    assert lap6["cleaning"]["exact_duplicates"] == 1
    assert lap6["cleaning"]["time_duplicates"] == 1
    assert lap6["cleaning"]["jumps"] == 1
    assert (
        report["timing_line"]["length_before_alignment_m"]
        == report["timing_line"]["length_after_alignment_m"]
    )
    assert report["timing_line"]["distance_from_line_m"] < 2.0
    for lap in report["laps"]:
        assert lap["residual_vs_final"]["lateral_rms_m"] < 1.0
        assert len(lap["smoothing_candidates"]) > 3
    # The local frame is translated to a sample origin, so absolute fixture
    # coordinates are not an invariant of the package. What must hold is that the
    # recorded transform recovers them: local + scale * origin_units.
    scale = report["frame"]["scale"]["scale_m_per_unit"]
    origin_units = report["frame"]["origin_units"]
    start = centreline.position_at(0.0)
    recovered = (start[0] + scale * origin_units[0], start[1] + scale * origin_units[1])
    # s = 0 is the timing line: the fixture crosses it at theta = 0, i.e. at (R(1+a), 0)
    assert recovered[1] == pytest.approx(0.0, abs=3.0)
    assert recovered[0] == pytest.approx(truth["radius_m"] * (1.0 + truth["lobe"]), abs=3.0)
    # theta = 0 is a lobe apex, so the timing line must sit at a curvature maximum
    assert centreline.curvature_at(0.0) == pytest.approx(centreline.curvature_1pm.max(), rel=0.05)
    # sectors were derived from the fixture's 30/35/35 % sector durations
    assert len(package.features.sectors) == 3
    assert package.features.sectors[0].end_s_m == pytest.approx(0.30 * truth["length_m"], abs=15.0)


def test_length_disagreement_above_two_percent_is_flagged_not_hidden(ingested):
    fixture, paths = ingested
    truth = fixture["truth"]
    manifest = write_manifest(paths.artifacts / "manifest.yaml", official_length_m=truth["length_m"] * 1.05)
    package = compile_track(manifest, paths)
    report = json.loads((paths.artifacts / "tracks" / "synthetic-loop" / "compile_report.json").read_text())
    assert package.validation.length_error_fraction > 0.02
    assert "length_error_exceeds_2pct" in report["flags"]
    assert "length_outside_validation_tolerance" in report["flags"]
    assert package.validation.status is ReadinessStatus.DISCOVERED


def test_direction_disagreement_with_manifest_is_flagged(ingested):
    fixture, paths = ingested
    manifest = write_manifest(
        paths.artifacts / "manifest.yaml",
        official_length_m=fixture["truth"]["length_m"],
        direction="clockwise",
    )
    package = compile_track(manifest, paths)
    report = json.loads((paths.artifacts / "tracks" / "synthetic-loop" / "compile_report.json").read_text())
    assert package.direction is Direction.COUNTERCLOCKWISE  # computed from progression, not copied
    assert "direction_disagrees_with_manifest" in report["flags"]


def test_compile_is_offline_and_refuses_without_an_ingest_summary(tmp_path):
    paths = scratch_paths(tmp_path)
    manifest = write_manifest(tmp_path / "manifest.yaml", official_length_m=1945.0)
    with pytest.raises(FileNotFoundError, match="run `afterlap tracks ingest"):
        compile_track(manifest, paths)


def test_manifest_without_provenance_for_the_official_length_is_refused(tmp_path):
    paths = scratch_paths(tmp_path)
    path = tmp_path / "manifest.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "track_id": "x",
                "display_name": "X",
                "official_length_m": 5000,
                "openf1": {"sessions": [{"session_key": 1}]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompileError, match="no provenance"):
        compile_track(path, paths)
