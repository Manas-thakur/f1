"""Replay clock: pause, step, seek, speed and session-mode badges."""

from __future__ import annotations

import pytest

from afterlap_contracts import SessionMode
from afterlap_core.data import (
    EstimatorSnapshot,
    IngestionPipeline,
    MemorySink,
    ReplayClock,
    ReplaySession,
    SnapshotStore,
    badge_for,
)

from .conftest import observation, simulator_config


def _records(count: int = 10):
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all(
        [
            observation(i, round(i * 0.1, 3), {"speed_mps": 70.0 + i}, received_time_s=round(i * 0.1, 3))
            for i in range(count)
        ]
    )
    return sink.normalised


def test_wall_time_never_advances_a_paused_replay():
    clock = ReplayClock(speed=4.0)
    clock.step(1.0)
    assert clock.session_time_s == pytest.approx(1.0)
    clock.pause()
    clock.step(5.0)
    assert clock.session_time_s == pytest.approx(1.0)
    assert clock.wall_clock_elapsed_s == pytest.approx(0.25)
    clock.resume()
    clock.step(0.5)
    assert clock.session_time_s == pytest.approx(1.5)


def test_speed_only_scales_wall_clock_duration():
    slow = ReplayClock(speed=1.0)
    fast = ReplayClock(speed=8.0)
    for clock in (slow, fast):
        clock.step(2.0)
    assert slow.session_time_s == fast.session_time_s == pytest.approx(2.0)
    assert slow.wall_clock_duration_for(2.0) == pytest.approx(2.0)
    assert fast.wall_clock_duration_for(2.0) == pytest.approx(0.25)


def test_speed_must_be_positive_and_steps_move_forward():
    clock = ReplayClock()
    with pytest.raises(ValueError):
        clock.set_speed(0.0)
    with pytest.raises(ValueError):
        clock.step(-1.0)
    with pytest.raises(ValueError):
        clock.seek(-0.5)


def test_step_delivers_only_records_inside_the_interval():
    session = ReplaySession(_records())
    first = session.step(0.25)
    assert all(r.session_time_s <= 0.25 for r in first)
    second = session.step(0.25)
    assert all(0.25 < r.session_time_s <= 0.5 for r in second)


def test_seek_loads_the_preceding_snapshot_and_replays_forward():
    records = _records()
    snapshots = SnapshotStore(
        [
            EstimatorSnapshot(session_time_s=0.0, revision=0),
            EstimatorSnapshot(session_time_s=0.3, revision=1),
            EstimatorSnapshot(session_time_s=0.7, revision=2),
        ]
    )
    session = ReplaySession(records, snapshots=snapshots)
    result = session.seek(0.55)

    assert result.snapshot is not None
    assert result.snapshot.revision == 1
    assert result.resumed_from_s == pytest.approx(0.3)
    assert result.evaluated_future_samples == 0
    assert all(0.3 < r.session_time_s <= 0.55 for r in result.replayed)
    assert session.session_time_s == pytest.approx(0.55)


def test_seek_without_a_snapshot_replays_from_the_start():
    session = ReplaySession(_records(), snapshots=SnapshotStore())
    result = session.seek(0.35)
    assert result.snapshot is None
    assert result.resumed_from_s == 0.0
    assert all(r.session_time_s <= 0.35 for r in result.replayed)


def test_records_at_cutoff_never_include_a_future_sample():
    session = ReplaySession(_records())
    visible = session.records_at_cutoff(0.42)
    assert visible
    assert max(r.session_time_s for r in visible) <= 0.42


def test_advance_to_refuses_to_move_backwards():
    session = ReplaySession(_records())
    session.advance_to(0.5)
    with pytest.raises(ValueError):
        session.advance_to(0.1)


def test_the_three_provenances_carry_different_badges():
    live = badge_for(SessionMode.LIVE_TEAM)
    archive = badge_for(SessionMode.REPLAY)
    simulation = badge_for(SessionMode.SIMULATION)
    counterfactual = badge_for(SessionMode.SIMULATION, counterfactual=True)

    labels = {live.label, archive.label, simulation.label, counterfactual.label}
    tokens = {live.token, archive.token, simulation.token, counterfactual.token}
    assert len(labels) == 4
    assert len(tokens) == 4
    assert "Live" in live.label
    assert archive.label == "Archive replay"
    assert "Counterfactual" in counterfactual.label
    assert counterfactual.counterfactual is True

    with pytest.raises(ValueError):
        badge_for(SessionMode.REPLAY, counterfactual=True)


def test_a_replay_session_reports_its_own_badge():
    session = ReplaySession(_records(), mode=SessionMode.REPLAY)
    assert session.badge.label == "Archive replay"
    counterfactual = ReplaySession(_records(), mode=SessionMode.SIMULATION, counterfactual=True)
    assert counterfactual.badge.label == "Counterfactual simulation"


def test_reset_returns_the_session_to_the_start():
    session = ReplaySession(_records())
    session.advance_to(0.5)
    assert session.cursor > 0
    session.reset()
    assert session.cursor == 0
    assert session.session_time_s == 0.0
    assert session.clock.wall_clock_elapsed_s == 0.0
