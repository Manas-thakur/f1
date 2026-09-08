"""OpenF1 record conversion on synthetic fixtures, plus the frozen real tapes when present."""

from __future__ import annotations

import math

import pytest

from afterlap_core.conditions.atmosphere import air_density
from afterlap_core.conditions.openf1_weather import CONVERSIONS, sample_from_record, tape_from_openf1_records
from afterlap_core.conditions.tape import ConditionsTape
from afterlap_core.paths import Paths


def _mean_density(tape: ConditionsTape) -> float:
    values = [
        r.value_kgpm3
        for s in tape.samples
        if (
            r := air_density(
                temperature_k=s.air_temperature_k,
                pressure_pa=s.pressure_pa,
                humidity_fraction=s.humidity_fraction,
                altitude_m=tape.altitude_m,
            )
        ).value_kgpm3
        is not None
    ]
    assert values
    return sum(values) / len(values)


def test_units_are_converted_to_si(synthetic_openf1_records):
    records = synthetic_openf1_records["monza_like"]
    tape = tape_from_openf1_records(records, tape_id="fixture-monza", session_key=1001, source=None)
    first = tape.samples[0]
    assert first.session_time_s == 0.0
    assert first.air_temperature_k == pytest.approx(299.15)
    assert first.track_temperature_k == pytest.approx(316.65)
    assert first.pressure_pa == pytest.approx(99750.0)
    assert first.humidity_fraction == pytest.approx(0.44)
    assert first.wind_direction_rad == pytest.approx(math.radians(263.0))
    assert first.wind_speed_mps == 2.5
    assert first.rainfall is False
    assert tape.samples[1].session_time_s == 60.0
    assert tape.provenance.conversions == CONVERSIONS
    assert tape.provenance.source_kind == "openf1"
    assert tape.provenance.raw_sha256 is None, "no raw cache record for a fixture"


def test_null_fields_stay_unknown(synthetic_openf1_records):
    records = synthetic_openf1_records["wet_transition"]
    tape = tape_from_openf1_records(records, tape_id="fixture-wet", session_key=1003, source=None)
    third = tape.samples[2]
    assert third.pressure_pa is None
    assert third.track_temperature_k is None
    assert third.rainfall is True
    assert tape.rainfall_seconds() == pytest.approx(120.0)


def test_mixed_sessions_are_refused(synthetic_openf1_records):
    records = synthetic_openf1_records["monza_like"] + synthetic_openf1_records["mexico_like"]
    with pytest.raises(ValueError, match="mixed into session"):
        tape_from_openf1_records(records, tape_id="bad", session_key=1001, source=None)


def test_mexico_like_air_is_thinner_than_monza_like_air_on_fixtures(synthetic_openf1_records):
    monza = tape_from_openf1_records(
        synthetic_openf1_records["monza_like"], tape_id="fixture-monza", session_key=1001, source=None
    )
    mexico = tape_from_openf1_records(
        synthetic_openf1_records["mexico_like"], tape_id="fixture-mexico", session_key=1002, source=None
    )
    rho_monza = _mean_density(monza)
    rho_mexico = _mean_density(mexico)
    assert rho_mexico < 0.85 * rho_monza
    assert 1.10 < rho_monza < 1.25
    assert 0.85 < rho_mexico < 0.98


def test_frozen_real_tapes_if_present_agree_on_the_altitude_ordering():
    root = Paths.default().artifacts / "conditions"
    monza_path = root / "monza-2025-race.json"
    mexico_path = root / "mexico-city-2025-race.json"
    if not (monza_path.exists() and mexico_path.exists()):
        pytest.skip("frozen OpenF1 tapes not present on this checkout")
    monza = ConditionsTape.read_json(monza_path)  # hash-verified on read
    mexico = ConditionsTape.read_json(mexico_path)
    assert monza.provenance.session_key == 9912
    assert mexico.provenance.session_key == 9877
    assert monza.provenance.raw_sha256 and mexico.provenance.raw_sha256
    assert _mean_density(mexico) < 0.85 * _mean_density(monza)


def test_record_timestamps_need_a_timezone():
    from datetime import UTC, datetime

    with pytest.raises(ValueError, match="timezone"):
        sample_from_record({"date": "2025-01-01T12:00:00", "session_key": 1}, datetime.now(UTC))
