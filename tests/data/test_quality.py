"""Freshness comes from observations, never from transport liveness."""

from __future__ import annotations

import pytest

from afterlap_contracts import Quality
from afterlap_core.data import (
    ChannelExpectation,
    IngestionPipeline,
    QualityTracker,
    expectations_from_capability,
    public_replay_capability,
    simulator_capability,
)

from .conftest import CAR_ID, observation, public_config, simulator_config


def _tracker(rate_hz: float, *, clock_uncertainty_s: float = 0.0, channel: str = "speed_mps"):
    return QualityTracker(
        [ChannelExpectation(channel=channel, expected_rate_hz=rate_hz, car_id=CAR_ID)],
        clock_uncertainty_s=clock_uncertainty_s,
    )


def test_freshness_is_computed_from_observation_age_and_the_sources_own_cadence():
    tracker = _tracker(20.0)
    tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=70.0, quality=Quality.VALID)

    fresh = tracker.assess(10.02).by_channel("speed_mps", CAR_ID)
    assert fresh is not None
    assert fresh.quality is Quality.VALID
    assert fresh.age_s == pytest.approx(0.02)
    assert fresh.expected_period_s == pytest.approx(0.05)

    degraded = tracker.assess(10.15).by_channel("speed_mps", CAR_ID)
    assert degraded.quality is Quality.DEGRADED

    stale = tracker.assess(10.30).by_channel("speed_mps", CAR_ID)
    assert stale.quality is Quality.STALE
    assert "expected periods" in (stale.reason or "")

    missing = tracker.assess(20.0).by_channel("speed_mps", CAR_ID)
    assert missing.quality is Quality.MISSING


def test_a_heartbeat_cannot_make_a_stale_channel_fresh():
    with_heartbeat = _tracker(20.0)
    without_heartbeat = _tracker(20.0)
    for tracker in (with_heartbeat, without_heartbeat):
        tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=70.0, quality=Quality.VALID)

    for tick in range(1, 11):
        with_heartbeat.heartbeat(10.0 + tick * 0.03)

    stale = with_heartbeat.assess(10.30)
    control = without_heartbeat.assess(10.30)

    assert with_heartbeat.heartbeat_count == 10
    assert stale.by_channel("speed_mps", CAR_ID).quality is Quality.STALE
    assert stale.by_channel("speed_mps", CAR_ID).quality is control.by_channel("speed_mps", CAR_ID).quality
    assert stale.by_channel("speed_mps", CAR_ID).age_s == control.by_channel("speed_mps", CAR_ID).age_s
    assert stale.heartbeat_age_s is not None
    assert "never contribute" in stale.heartbeat_note


def test_a_heartbeat_cannot_upgrade_a_channel_that_never_reported():
    tracker = _tracker(20.0)
    for tick in range(20):
        tracker.heartbeat(tick * 0.05)
    assessment = tracker.assess(1.0)
    entry = assessment.by_channel("speed_mps", CAR_ID)
    assert entry.quality is Quality.MISSING
    assert entry.age_s is None


def test_a_3_7_hz_source_is_not_judged_stale_by_20_hz_expectations():
    slow = _tracker(3.7)
    fast = _tracker(20.0)
    for tracker in (slow, fast):
        tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=70.0, quality=Quality.VALID)

    at = 10.5
    slow_entry = slow.assess(at).by_channel("speed_mps", CAR_ID)
    fast_entry = fast.assess(at).by_channel("speed_mps", CAR_ID)

    assert slow_entry.quality is Quality.VALID
    assert fast_entry.quality is Quality.STALE
    assert slow_entry.expected_period_s == pytest.approx(1.0 / 3.7)


def test_expectations_are_taken_from_the_capability_the_source_declared():
    public = expectations_from_capability(public_replay_capability(), car_id=CAR_ID)
    assert [e.expected_rate_hz for e in public] == [pytest.approx(3.7)]
    simulated = expectations_from_capability(simulator_capability(rate_hz=20.0), car_id=CAR_ID)
    assert all(e.expected_rate_hz == 20.0 for e in simulated)


def test_clock_uncertainty_can_only_age_an_observation_never_freshen_it():
    certain = _tracker(20.0, clock_uncertainty_s=0.0)
    uncertain = _tracker(20.0, clock_uncertainty_s=0.06)
    for tracker in (certain, uncertain):
        tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=70.0, quality=Quality.VALID)
    at = 10.06
    assert certain.assess(at).by_channel("speed_mps", CAR_ID).quality is Quality.VALID
    assert uncertain.assess(at).by_channel("speed_mps", CAR_ID).quality is Quality.DEGRADED


def test_a_value_outside_registered_bounds_is_invalid_not_merely_stale():
    tracker = _tracker(20.0)
    tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=400.0, quality=Quality.VALID)
    entry = tracker.assess(10.01).by_channel("speed_mps", CAR_ID)
    assert entry.quality is Quality.INVALID
    assert "registered bound" in entry.reason


def test_battery_power_integration_gap_is_reported_so_estimation_can_widen_uncertainty():
    tracker = QualityTracker(
        [ChannelExpectation(channel="electrical_power_w", expected_rate_hz=20.0, car_id=CAR_ID)]
    )
    tracker.observe(
        "electrical_power_w", session_time_s=10.0, car_id=CAR_ID, value=120_000.0, quality=Quality.VALID
    )
    gap = tracker.observe(
        "electrical_power_w", session_time_s=12.0, car_id=CAR_ID, value=130_000.0, quality=Quality.VALID
    )
    assert gap is not None
    assert gap.integration_gap_s == pytest.approx(2.0 - 0.05)
    assert gap.cumulative_gap_s == pytest.approx(gap.integration_gap_s)
    assert "widen energy uncertainty" in gap.reason

    assessment = tracker.assess(12.01)
    assert assessment.integration_gaps
    assert assessment.integration_gap_for("electrical_power_w", CAR_ID) == pytest.approx(1.95)
    entry = assessment.by_channel("electrical_power_w", CAR_ID)
    assert "integration_gap_s=" in entry.reason
    assert entry.quality is Quality.DEGRADED


def test_no_integration_gap_is_reported_for_a_healthy_cadence():
    tracker = QualityTracker(
        [ChannelExpectation(channel="electrical_power_w", expected_rate_hz=20.0, car_id=CAR_ID)]
    )
    for i in range(10):
        gap = tracker.observe(
            "electrical_power_w",
            session_time_s=10.0 + i * 0.05,
            car_id=CAR_ID,
            value=120_000.0,
            quality=Quality.VALID,
        )
        assert gap is None
    assert tracker.assess(10.5).integration_gaps == ()


def test_pipeline_surfaces_the_integration_gap_it_observed():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    output = pipeline.ingest_all(
        [
            observation(0, 10.0, {"electrical_power_w": 120_000.0}, received_time_s=10.0),
            observation(1, 12.0, {"electrical_power_w": 130_000.0}, received_time_s=12.0),
        ]
    )
    assert output.integration_gaps
    assert output.integration_gaps[0].channel == "electrical_power_w"
    assert output.integration_gaps[0].integration_gap_s > 1.9


def test_a_late_arrival_does_not_make_a_channel_look_fresher():
    tracker = _tracker(20.0)
    tracker.observe("speed_mps", session_time_s=10.0, car_id=CAR_ID, value=70.0, quality=Quality.VALID)
    tracker.observe("speed_mps", session_time_s=12.0, car_id=CAR_ID, value=71.0, quality=Quality.VALID)
    tracker.observe("speed_mps", session_time_s=10.5, car_id=CAR_ID, value=70.5, quality=Quality.VALID)
    entry = tracker.assess(12.02).by_channel("speed_mps", CAR_ID)
    assert entry.last_source_time_s == pytest.approx(12.0)
    assert entry.age_s == pytest.approx(0.02)


def test_public_pipeline_is_not_judged_stale_by_simulator_expectations():
    public = IngestionPipeline(public_config(reorder_window_s=0.0))
    public.ingest_all(
        [
            observation(
                0,
                10.0,
                {"speed": 250.0, "driver_number": 1},
                source_id="public-replay",
                received_time_s=10.0,
            )
        ]
    )
    simulator = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    simulator.ingest_all([observation(0, 10.0, {"speed_mps": 69.4}, received_time_s=10.0)])

    at = 10.3
    public_entry = public.assess_quality(at).by_channel("speed_mps", CAR_ID)
    sim_entry = simulator.assess_quality(at).by_channel("speed_mps", CAR_ID)

    assert sim_entry.quality is Quality.STALE
    assert public_entry.quality is Quality.DEGRADED
    assert public_entry.expected_period_s == pytest.approx(1.0 / 3.7)
    assert "clock uncertainty" in public_entry.reason
