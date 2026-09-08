"""Coordinator-owned foundation: clocks, event order, keyed randomness, storage."""

from __future__ import annotations

import json

import numpy as np
import pytest

from afterlap_contracts import Quality
from afterlap_core.paths import ArtifactStore, Paths, atomic_write_json, sha256_bytes
from afterlap_core.rng import KeyedRandom, StreamRegistry, derive_seed
from afterlap_core.timebase import (
    EventPriority,
    EventQueue,
    SessionClock,
    classify_freshness,
    crossing_time,
    laps_and_s,
    progress_of,
    wrap_s,
)


def test_events_at_equal_time_follow_the_contract_priority():
    queue: EventQueue[str] = EventQueue()
    queue.push(1.0, EventPriority.UI_SNAPSHOT, "snapshot")
    queue.push(1.0, EventPriority.OPERATOR_COMMAND, "operator")
    queue.push(1.0, EventPriority.PLAN_VALIDATION, "plan")
    queue.push(1.0, EventPriority.PHYSICAL_LINE_EVENT, "line")
    queue.push(1.0, EventPriority.SAFETY_OR_RULE_INVALIDATION, "safety")

    order = [event.payload for event in queue.pop_until(1.0)]
    assert order == ["safety", "line", "plan", "operator", "snapshot"]


def test_earlier_events_precede_higher_priority_later_events():
    queue: EventQueue[str] = EventQueue()
    queue.push(2.0, EventPriority.SAFETY_OR_RULE_INVALIDATION, "later-safety")
    queue.push(1.0, EventPriority.UI_SNAPSHOT, "earlier-snapshot")
    assert [e.payload for e in queue.pop_until(2.0)] == ["earlier-snapshot", "later-safety"]


def test_equal_time_and_priority_preserves_insertion_order():
    queue: EventQueue[int] = EventQueue()
    for i in range(5):
        queue.push(3.0, EventPriority.PHYSICAL_LINE_EVENT, i)
    assert [e.payload for e in queue.pop_until(3.0)] == [0, 1, 2, 3, 4]


def test_queue_snapshot_and_restore_reproduces_order():
    queue: EventQueue[str] = EventQueue()
    queue.push(1.0, EventPriority.PLAN_VALIDATION, "a")
    queue.push(0.5, EventPriority.UI_SNAPSHOT, "b")
    captured = queue.snapshot()
    counter = queue.counter

    restored: EventQueue[str] = EventQueue()
    restored.restore(captured, counter)
    assert [e.payload for e in restored.pop_until(2.0)] == ["b", "a"]


def test_wall_time_does_not_advance_a_paused_simulation():
    clock = SessionClock()
    clock.advance(1.0)
    clock.pause()
    clock.advance(5.0)
    assert clock.session_time_s == pytest.approx(1.0)
    clock.resume()
    clock.advance(0.5)
    assert clock.session_time_s == pytest.approx(1.5)


def test_the_clock_never_runs_backwards():
    with pytest.raises(ValueError, match="never runs backwards"):
        SessionClock().advance(-0.1)


def test_replay_speed_changes_pacing_not_simulated_time():
    clock = SessionClock()
    clock.set_speed(4.0)
    clock.advance(2.0)
    assert clock.session_time_s == pytest.approx(2.0), "speed must not scale simulated time"
    assert clock.speed == 4.0
    with pytest.raises(ValueError, match="must be positive"):
        clock.set_speed(0.0)


def test_crossing_time_is_interpolated_inside_the_step():
    assert crossing_time(1.0, 1.2, 90.0, 110.0, 100.0) == pytest.approx(1.1)


def test_crossing_outside_the_interval_is_none():
    assert crossing_time(1.0, 1.2, 90.0, 99.0, 100.0) is None
    assert crossing_time(1.0, 1.2, 101.0, 110.0, 100.0) is None


def test_two_lines_in_one_interval_are_both_found_and_ordered():
    first = crossing_time(0.0, 1.0, 0.0, 100.0, 30.0)
    second = crossing_time(0.0, 1.0, 0.0, 100.0, 70.0)
    assert first is not None and second is not None
    assert first < second


def test_a_stationary_quantity_never_reports_a_crossing():
    assert crossing_time(0.0, 1.0, 50.0, 50.0, 50.0) is None


def test_progress_wraps_and_unwraps_consistently():
    length = 5_200.0
    assert wrap_s(5_400.0, length) == pytest.approx(200.0)
    assert progress_of(2, 200.0, length) == pytest.approx(10_600.0)
    laps, s = laps_and_s(10_600.0, length)
    assert (laps, s) == (2, pytest.approx(200.0))


def test_zero_length_track_is_rejected():
    with pytest.raises(ValueError, match="must be positive"):
        wrap_s(1.0, 0.0)


def test_freshness_uses_the_sources_own_cadence():
    assert classify_freshness(0.02, 0.05) is Quality.VALID
    assert classify_freshness(0.02, 0.27) is Quality.VALID
    assert classify_freshness(0.25, 0.05) is Quality.STALE
    assert classify_freshness(0.25, 0.27) is Quality.VALID


def test_unknown_age_is_missing_not_fresh():
    assert classify_freshness(None, 0.05) is Quality.MISSING


def test_negative_age_is_invalid():
    assert classify_freshness(-1.0, 0.05) is Quality.INVALID


def test_unknown_cadence_cannot_be_called_valid():
    assert classify_freshness(0.01, None) is Quality.DEGRADED


def test_derived_seeds_are_stable_across_calls():
    assert derive_seed("scenario", 42, "wind", 3) == derive_seed("scenario", 42, "wind", 3)
    assert derive_seed("scenario", 42, "wind", 3) != derive_seed("scenario", 42, "wind", 4)


def test_branches_share_exogenous_disturbances_at_the_same_physical_time():
    reference = KeyedRandom("two-straight-counterattack", 42)
    candidate = KeyedRandom("two-straight-counterattack", 42)

    for _ in range(17):
        reference.normal("sensor_noise", 1.0)
    reference_draw = reference.normal("wind", 4.3)
    candidate_draw = candidate.normal("wind", 4.3)

    assert reference_draw == candidate_draw, (
        "a changed call order must not change the exogenous disturbance a branch sees"
    )


def test_different_seeds_produce_different_disturbances():
    a = KeyedRandom("scenario", 1).normal("wind", 4.3)
    b = KeyedRandom("scenario", 2).normal("wind", 4.3)
    assert a != b


def test_named_streams_advance_independently():
    registry = StreamRegistry(root_seed=7, names=("sensor_noise", "driver_response"))
    driver_first = registry.stream("driver_response").normal()

    for _ in range(50):
        registry.stream("sensor_noise").normal()

    fresh = StreamRegistry(root_seed=7, names=("sensor_noise", "driver_response"))
    assert fresh.stream("driver_response").normal() == driver_first


def test_stream_registry_snapshot_restores_exactly():
    registry = StreamRegistry(root_seed=11, names=("sensor_noise",))
    registry.stream("sensor_noise").normal(size=5)

    captured = registry.capture()
    expected = registry.stream("sensor_noise").normal(size=5)

    restored = StreamRegistry(root_seed=0)
    restored.restore(captured)
    assert restored.names == ("sensor_noise",)
    assert np.array_equal(restored.stream("sensor_noise").normal(size=5), expected), (
        "a restored snapshot must reproduce the exact subsequent draws"
    )


def test_stream_registry_state_survives_json_serialisation():
    registry = StreamRegistry(root_seed=11, names=("driver_response",))
    registry.stream("driver_response").normal(size=3)

    captured = json.loads(json.dumps(registry.capture()))
    expected = registry.stream("driver_response").normal(size=3)

    restored = StreamRegistry(root_seed=0)
    restored.restore(captured)
    assert np.array_equal(restored.stream("driver_response").normal(size=3), expected)


def test_artifact_store_is_content_addressed(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    digest = store.put_bytes(b"weights")
    assert digest == sha256_bytes(b"weights")
    assert store.put_bytes(b"weights") == digest, "identical content yields one artefact"
    assert store.get_bytes(digest) == b"weights"
    assert store.has(digest)


def test_artifact_store_verifies_hashes_on_read(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    digest = store.put_bytes(b"weights")
    store.path_of(digest).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="failed hash verification"):
        store.get_bytes(digest)


def test_artifact_store_rejects_a_malformed_digest(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ValueError, match="malformed digest"):
        store.get_bytes("sha256:not-a-hash")
    with pytest.raises(ValueError, match="sha256"):
        store.get_bytes("deadbeef")


def test_paths_reject_traversal_outside_the_storage_root(tmp_path):
    paths = Paths.default(tmp_path).ensure()
    inside = paths.resolve_within("reports/run-1.json")
    assert inside.is_relative_to(paths.artifacts)
    with pytest.raises(ValueError, match="escapes the configured storage root"):
        paths.resolve_within("../../etc/passwd")


def test_atomic_write_leaves_no_partial_file(tmp_path):
    target = tmp_path / "nested" / "report.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert list(tmp_path.rglob("*.staging")) == []
