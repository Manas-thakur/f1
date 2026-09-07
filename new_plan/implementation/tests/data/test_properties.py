"""Property tests: recording round trip, speed invariance, sequence uniqueness."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from .conftest import SESSION_ID, observation, public_config, simulator_config
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from afterlap_core.data import (
    ChunkReader,
    EstimatorSnapshot,
    IngestionPipeline,
    IngestionRouter,
    MemorySink,
    ReplayClock,
    ReplaySession,
    SnapshotStore,
    TelemetryRecorder,
    normalised_signature,
    sort_normalised,
)

MAPPING_REVISION = "sim-observation-map-1"
SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

speeds = st.floats(min_value=0.0, max_value=110.0, allow_nan=False, allow_infinity=False, width=64)
energies = st.floats(min_value=0.0, max_value=4_000_000.0, allow_nan=False, allow_infinity=False, width=64)
gaps = st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False, width=64)


@st.composite
def event_streams(draw, min_size: int = 1, max_size: int = 24):
    """Arbitrary monotonic observation streams over registered channels."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    deltas = draw(st.lists(gaps, min_size=count, max_size=count))
    records = []
    time_s = 0.0
    for index, delta in enumerate(deltas):
        time_s = round(time_s + delta, 6)
        fields: dict[str, float | None] = {"speed_mps": draw(speeds)}
        if draw(st.booleans()):
            fields["battery_energy_j"] = draw(energies)
        if draw(st.integers(min_value=0, max_value=9)) == 0:
            fields["speed_mps"] = None  # a declared missing sample
        records.append(observation(index, time_s, fields, received_time_s=time_s))
    return records


def _normalise(records) -> list:
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all(records)
    return sink.normalised


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@SETTINGS
@given(records=event_streams())
def test_recording_then_replaying_reproduces_the_same_normalised_sequence(records):
    produced = _normalise(records)
    assume(produced)

    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        recorder = TelemetryRecorder(
            root, SESSION_ID, mapping_revision=MAPPING_REVISION, chunk_duration_s=0.5
        )
        for record in produced:
            recorder.append_normalised(record)
        recorder.flush()

        reader = ChunkReader(root, SESSION_ID)
        assert reader.verify() == ()
        restored = reader.read_normalised()

    expected = sort_normalised(produced)
    assert normalised_signature(restored) == normalised_signature(expected)

    replayed = []
    session = ReplaySession(restored)
    for _, batch in session.run(step_s=0.25):
        replayed.extend(batch)
    assert normalised_signature(replayed) == normalised_signature(expected)


@SETTINGS
@given(records=event_streams())
def test_replay_delivers_every_record_exactly_once_in_session_order(records):
    produced = _normalise(records)
    assume(produced)
    session = ReplaySession(produced)
    delivered = []
    for _, batch in session.run(step_s=0.1):
        delivered.extend(batch)
    assert len(delivered) == len(produced)
    assert [r.event.sequence for r in delivered] == sorted(r.event.sequence for r in produced)
    times = [r.session_time_s for r in delivered]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# Speed invariance
# ---------------------------------------------------------------------------


@SETTINGS
@given(
    records=event_streams(),
    speed=st.floats(min_value=0.1, max_value=64.0, allow_nan=False, allow_infinity=False),
)
def test_replay_speed_changes_pacing_only(records, speed):
    produced = _normalise(records)
    assume(produced)

    baseline = ReplaySession(produced, clock=ReplayClock(speed=1.0))
    fast = ReplaySession(produced, clock=ReplayClock(speed=speed))

    baseline_batches = [(t, batch) for t, batch in baseline.run(step_s=0.1)]
    fast_batches = [(t, batch) for t, batch in fast.run(step_s=0.1)]

    # Simulated timestamps are bit-identical.
    assert [t for t, _ in baseline_batches] == [t for t, _ in fast_batches]
    # The normalised sequence is bit-identical.
    flat_baseline = [r for _, batch in baseline_batches for r in batch]
    flat_fast = [r for _, batch in fast_batches for r in batch]
    assert normalised_signature(flat_baseline) == normalised_signature(flat_fast)
    # Only wall-clock pacing changed, by exactly the speed factor.
    assert baseline.clock.session_time_s == fast.clock.session_time_s
    assert fast.clock.wall_clock_elapsed_s == pytest.approx(
        baseline.clock.wall_clock_elapsed_s / speed, rel=1e-9
    )


@SETTINGS
@given(
    records=event_streams(min_size=4),
    speed=st.floats(min_value=0.25, max_value=16.0, allow_nan=False, allow_infinity=False),
)
def test_speed_change_mid_replay_does_not_alter_simulated_time_or_integration(records, speed):
    produced = _normalise(records)
    assume(produced)
    horizon = max(r.session_time_s for r in produced) + 0.1

    def energy_integral(session: ReplaySession, step_s: float) -> float:
        total = 0.0
        previous = 0.0
        while session.clock.session_time_s < horizon:
            target = min(horizon, session.clock.session_time_s + step_s)
            batch = session.advance_to(target)
            dt = target - previous
            previous = target
            values = [r.event.value for r in batch if r.event.channel == "speed_mps"]
            numeric = [v for v in values if v is not None]
            if numeric:
                total += sum(numeric) / len(numeric) * dt
        return total

    steady = ReplaySession(produced, clock=ReplayClock(speed=1.0))
    varying = ReplaySession(produced, clock=ReplayClock(speed=1.0))

    steady_total = energy_integral(steady, 0.1)
    varying.clock.set_speed(speed)
    varying_total = energy_integral(varying, 0.1)

    assert varying_total == steady_total
    assert varying.clock.session_time_s == steady.clock.session_time_s


# ---------------------------------------------------------------------------
# Sequence assignment
# ---------------------------------------------------------------------------


@SETTINGS
@given(
    interleaving=st.lists(st.sampled_from(["simulator", "public-replay"]), min_size=1, max_size=40),
)
def test_session_sequences_are_strictly_monotonic_and_never_reused(interleaving):
    router = IngestionRouter([simulator_config(reorder_window_s=0.0), public_config(reorder_window_s=0.0)])
    counters = {"simulator": 0, "public-replay": 0}
    delivered = []
    time_s = 0.0
    for source_id in interleaving:
        time_s = round(time_s + 0.05, 6)
        sequence = counters[source_id]
        counters[source_id] += 1
        fields = {"speed_mps": 70.0} if source_id == "simulator" else {"speed": 250.0, "driver_number": 1}
        delivered.extend(
            router.ingest(
                observation(sequence, time_s, fields, source_id=source_id, received_time_s=time_s)
            ).normalised
        )
    delivered.extend(router.close(time_s + 5.0).normalised)

    sequences = [r.event.sequence for r in delivered]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
    assert sequences == list(range(len(sequences)))
    assert router.sequences.issued == len(sequences)


@SETTINGS
@given(records=event_streams())
def test_duplicating_an_arbitrary_stream_never_produces_extra_records(records):
    once = _normalise(records)
    twice = _normalise([*records, *records])
    assert normalised_signature(sort_normalised(twice)) == normalised_signature(sort_normalised(once))


# ---------------------------------------------------------------------------
# Seek
# ---------------------------------------------------------------------------


@SETTINGS
@given(records=event_streams(min_size=6), fraction=st.floats(min_value=0.0, max_value=1.0))
def test_seek_never_evaluates_a_sample_after_the_cutoff(records, fraction):
    produced = _normalise(records)
    assume(produced)
    horizon = max(r.session_time_s for r in produced)
    target = horizon * fraction

    snapshots = SnapshotStore(
        EstimatorSnapshot(session_time_s=horizon * step / 4.0, revision=step) for step in range(5)
    )
    session = ReplaySession(produced, snapshots=snapshots)
    session.advance_to(horizon)  # play to the end first, then seek backwards

    result = session.seek(target)
    assert result.evaluated_future_samples == 0
    assert all(r.session_time_s <= target for r in result.replayed)
    if result.snapshot is not None:
        assert result.snapshot.session_time_s <= target
        assert all(r.session_time_s > result.snapshot.session_time_s for r in result.replayed)
    assert session.clock.session_time_s == pytest.approx(max(target, result.resumed_from_s))

    # The state visible at the cutoff is exactly the records at or before it.
    visible = session.records_at_cutoff(target)
    assert all(r.session_time_s <= target for r in visible)
    assert len(visible) == len([r for r in produced if r.session_time_s <= target])
