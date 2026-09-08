"""Tape interpolation, clamping, hashing and serialisation."""

from __future__ import annotations

import dataclasses
import math

import pytest

from afterlap_core.conditions.tape import ConditionsSample, ConditionsTape

from .conftest import simple_tape, synthetic_provenance


def test_interpolation_is_linear_deterministic_and_clamped():
    tape = simple_tape()
    a = tape.at(30.0)
    b = tape.at(30.0)
    assert a == b
    assert a.air_temperature_k == pytest.approx(293.65)
    assert tape.at(-500.0).air_temperature_k == 293.15  # clamped to the first sample
    assert tape.at(-500.0).session_time_s == 0.0
    assert tape.at(1e6).air_temperature_k == 295.15  # clamped to the last sample
    assert tape.at(1e6).session_time_s == 120.0


def test_wind_direction_interpolates_along_the_short_arc():
    tape = simple_tape(wind_dir_rad=(math.radians(350.0), math.radians(10.0), math.radians(10.0)))
    mid = tape.at(30.0).wind_direction_rad
    assert mid is not None
    assert min(mid, 2.0 * math.pi - mid) < 1e-9


def test_rainfall_is_a_zero_order_hold():
    tape = simple_tape(rainfall=(False, True, False))
    assert tape.at(59.0).rainfall is False
    assert tape.at(60.0).rainfall is True
    assert tape.at(119.0).rainfall is True
    assert tape.at(120.0).rainfall is False
    assert tape.rainfall_seconds() == pytest.approx(60.0)


def test_unknown_fields_stay_unknown_and_are_skipped_in_interpolation():
    samples = [
        ConditionsSample(0.0, air_temperature_k=290.0, pressure_pa=100000.0),
        ConditionsSample(60.0, air_temperature_k=292.0, pressure_pa=None),
        ConditionsSample(120.0, air_temperature_k=294.0, pressure_pa=100200.0),
    ]
    tape = ConditionsTape("gappy", samples, synthetic_provenance())
    at = tape.at(60.0)
    assert at.pressure_pa == pytest.approx(100100.0), "the None sample is skipped, not treated as zero"
    assert at.humidity_fraction is None
    assert at.wind_speed_mps is None
    assert at.rainfall is None


def test_content_hash_changes_when_any_sample_changes():
    base = simple_tape()
    for index in range(3):
        samples = list(base.samples)
        s = samples[index]
        samples[index] = ConditionsSample(
            s.session_time_s,
            air_temperature_k=(s.air_temperature_k or 0.0) + 0.01,
            track_temperature_k=s.track_temperature_k,
            pressure_pa=s.pressure_pa,
            humidity_fraction=s.humidity_fraction,
            wind_speed_mps=s.wind_speed_mps,
            wind_direction_rad=s.wind_direction_rad,
            rainfall=s.rainfall,
        )
        changed = ConditionsTape(base.tape_id, samples, base.provenance)
        assert changed.content_hash != base.content_hash
    rain_flip = ConditionsTape(
        base.tape_id,
        [dataclasses.replace(s, rainfall=True) if i == 1 else s for i, s in enumerate(base.samples)],
        base.provenance,
    )
    assert rain_flip.content_hash != base.content_hash
    assert simple_tape().content_hash == base.content_hash, "identical content, identical hash"


def test_json_round_trip_preserves_hash_and_detects_tampering(tmp_path):
    tape = simple_tape(altitude_m=100.0)
    path = tmp_path / "tape.json"
    digest = tape.write_json(path)
    loaded = ConditionsTape.read_json(path)
    assert loaded.content_hash == digest == tape.content_hash
    assert loaded.altitude_m == 100.0
    text = path.read_text(encoding="utf-8").replace("293.15", "293.16", 1)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="changed since it was written"):
        ConditionsTape.read_json(path)


def test_sample_validation_catches_unit_slips():
    with pytest.raises(ValueError):
        ConditionsSample(0.0, pressure_pa=1013.25)
    with pytest.raises(ValueError):
        ConditionsSample(0.0, air_temperature_k=26.0)
    with pytest.raises(ValueError):
        ConditionsSample(0.0, humidity_fraction=44.0)


def test_tape_needs_strictly_increasing_times_and_an_altitude_source():
    with pytest.raises(ValueError):
        ConditionsTape("dup", [ConditionsSample(0.0), ConditionsSample(0.0)], synthetic_provenance())
    with pytest.raises(ValueError):
        ConditionsTape("alt", [ConditionsSample(0.0)], synthetic_provenance(), altitude_m=10.0)
