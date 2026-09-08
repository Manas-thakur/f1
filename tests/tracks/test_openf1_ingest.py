"""OpenF1 ingestion: clean-lap rules, driver choice, provenance, and no network.

Every payload comes from ``fixtures/synthetic_openf1_session.json`` -- a
synthetic analytic loop written in OpenF1 payload shape -- and is pre-loaded
into a :class:`RawSourceCache` with ``put``. ``urlopen`` is patched to raise so
any attempt to reach the real API fails the test.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from afterlap_core.tracks.ingest.openf1 import (
    OPENF1_LICENCE_URL,
    IngestResult,
    OpenF1IngestError,
    choose_driver,
    ingest_location_session,
    load_ingest_summary,
    select_clean_laps,
)
from afterlap_core.tracks.provenance import RawSourceCache

from .conftest import scratch_paths

FIXTURE = Path(__file__).with_name("fixtures") / "synthetic_openf1_session.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def seed_cache(cache: RawSourceCache, fixture: dict) -> None:
    def put(url: str, payload: object, source_id: str) -> None:
        cache.put(
            json.dumps(payload).encode("utf-8"),
            source="openf1",
            source_id=source_id,
            title=f"synthetic fixture {source_id}",
            url=url,
            permission="synthetic fixture in OpenF1 shape; no external rights involved",
            priority=3,
            content_type="application/json",
            filename="payload.json",
        )

    put(fixture["sessions_url"], fixture["sessions_payload"], "fixture-sessions")
    put(fixture["laps_url"], fixture["laps_payload"], "fixture-laps")
    for key, entry in fixture["location_payloads"].items():
        put(entry["url"], entry["payload"], f"fixture-location-{key}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def seeded(tmp_path):
    fixture = load_fixture()
    paths = scratch_paths(tmp_path)
    cache = RawSourceCache(paths=paths)
    seed_cache(cache, fixture)
    return fixture, paths, cache


def test_fixture_is_labelled_synthetic():
    fixture = load_fixture()
    assert fixture["synthetic"] is True
    assert "SYNTHETIC" in fixture["note"]


def test_clean_lap_rules_reject_first_pit_out_missing_and_slow_laps():
    fixture = load_fixture()
    accepted, rejected, median = select_clean_laps(fixture["laps_payload"])
    truth = fixture["truth"]
    assert rejected["first_lap"] == 2
    assert rejected["pit_out_lap"] == 2
    assert rejected["no_lap_duration"] == 1
    assert rejected["duration_outside_tolerance"] == 2
    assert median == pytest.approx(truth["lap_time_s"], abs=1e-3)
    by_driver = {}
    for lap in accepted:
        by_driver.setdefault(str(lap["driver_number"]), []).append(lap["lap_number"])
    assert by_driver == truth["clean_laps"]


def test_slow_lap_is_outside_two_percent_but_a_lap_at_one_percent_is_kept():
    laps = [
        {"lap_number": n, "driver_number": 1, "is_pit_out_lap": False, "lap_duration": d}
        for n, d in ((2, 100.0), (3, 100.0), (4, 101.0), (5, 100.0), (6, 103.0))
    ]
    accepted, rejected, median = select_clean_laps(laps)
    assert median == 100.0
    assert [lap["lap_number"] for lap in accepted] == [2, 3, 4, 5]
    assert rejected["duration_outside_tolerance"] == 1


def test_driver_with_most_clean_laps_is_chosen():
    accepted, _, _ = select_clean_laps(load_fixture()["laps_payload"])
    driver, counts = choose_driver(accepted)
    assert driver == 1
    assert counts == {1: 3, 2: 2}


def test_ingest_from_cache_selects_driver_persists_laps_and_records_provenance(seeded):
    fixture, paths, cache = seeded
    result = ingest_location_session(fixture["session_key"], "synthetic-loop", paths, cache=cache)
    assert result.driver_number == 1
    assert [lap.lap_number for lap in result.laps] == [5, 6, 7]
    assert result.session["circuit_short_name"] == "Synthetic"
    for lap in result.laps:
        cached = cache.get("openf1", lap.location_sha256)
        assert cached.record.url == lap.location_url
        assert lap.sample_count == len(json.loads(cached.read_bytes()))
        assert lap.sample_count > 100
    assert len(result.sources) == 2 + 3
    assert result.summary_path.exists()
    reloaded = load_ingest_summary("synthetic-loop", fixture["session_key"], paths)
    assert reloaded == result


def test_ingest_result_round_trips_through_json(seeded):
    fixture, paths, cache = seeded
    result = ingest_location_session(fixture["session_key"], "synthetic-loop", paths, cache=cache)
    again = IngestResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert again == result


def test_explicit_driver_is_honoured_and_unknown_driver_is_refused(seeded):
    fixture, paths, cache = seeded
    result = ingest_location_session(
        fixture["session_key"], "synthetic-loop", paths, driver_number=2, cache=cache
    )
    assert result.driver_number == 2
    assert [lap.lap_number for lap in result.laps] == [2, 4]
    with pytest.raises(OpenF1IngestError, match="no clean laps"):
        ingest_location_session(
            fixture["session_key"], "synthetic-loop", paths, driver_number=99, cache=cache
        )


def test_second_run_is_offline_and_identical(seeded):
    fixture, paths, cache = seeded
    first = ingest_location_session(fixture["session_key"], "synthetic-loop", paths, cache=cache)
    second = ingest_location_session(fixture["session_key"], "synthetic-loop", paths, cache=cache)
    assert [lap.location_sha256 for lap in first.laps] == [lap.location_sha256 for lap in second.laps]


def test_missing_payload_reaches_for_the_network_and_is_refused(tmp_path):
    paths = scratch_paths(tmp_path)
    with pytest.raises(AssertionError, match="must not reach the network"):
        ingest_location_session(123456, "nowhere", paths, cache=RawSourceCache(paths=paths))


def test_licence_recorded_is_the_verified_one():
    from afterlap_core.tracks.ingest.openf1 import OPENF1_PERMISSION

    assert "CC BY-NC-SA 4.0" in OPENF1_PERMISSION
    assert OPENF1_LICENCE_URL in OPENF1_PERMISSION
    assert "non-commercial" in OPENF1_PERMISSION
