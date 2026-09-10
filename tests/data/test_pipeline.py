"""Ingestion pipeline behaviour: duplicates, clocks, units, restarts, reorder."""

from __future__ import annotations

import pytest

from afterlap_contracts import Provenance, Quality, channel
from afterlap_core.data import (
    LABEL_BACKWARDS_CLOCK,
    LABEL_MISSING_VALUE,
    LABEL_OUT_OF_ORDER,
    LABEL_UNMAPPED_FIELD,
    IngestionPipeline,
    IngestionRouter,
    MemorySink,
    RejectionReason,
    SequenceAllocator,
    TelemetryRecorder,
)
from afterlap_core.data.recording import ChunkReader

from .conftest import (
    CAR_ID,
    SESSION_ID,
    observation,
    public_config,
    simulator_config,
)

try:
    import pyarrow as pa  # noqa: F401

    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False

requires_parquet = pytest.mark.skipif(
    not HAS_PARQUET, reason="reads or writes parquet chunks, which needs pyarrow"
)


def _speed_records(output_records):
    return [r for r in output_records if r.event.channel == "speed_mps"]


def test_duplicate_events_produce_exactly_one_normalised_record():
    pipeline = IngestionPipeline(simulator_config())
    first = observation(1, 1.00, {"speed_mps": 70.0}, received_time_s=1.00)
    duplicate = observation(1, 1.00, {"speed_mps": 70.0}, received_time_s=1.02)

    output = pipeline.ingest(first)
    output = output + pipeline.ingest(duplicate)
    output = output + pipeline.close(2.0)

    speeds = _speed_records(output.normalised)
    assert len(speeds) == 1
    assert speeds[0].event.value == pytest.approx(70.0)
    assert [r.reason for r in output.rejected] != []
    assert output.rejected[0].reason is RejectionReason.DUPLICATE
    assert pipeline.stats().duplicates == 1


def test_duplicate_across_a_burst_keeps_one_of_each_sequence():
    pipeline = IngestionPipeline(simulator_config())
    records = [observation(i, i * 0.05, {"speed_mps": 70.0 + i}, received_time_s=i * 0.05) for i in range(5)]
    output = pipeline.ingest_all([*records, *records])
    assert len(_speed_records(output.normalised)) == 5
    assert pipeline.stats().duplicates == 5


def test_backwards_source_clock_is_detected_and_labelled_not_silently_accepted():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    output = pipeline.ingest(observation(1, 5.0, {"speed_mps": 70.0}, received_time_s=5.0))
    output = output + pipeline.ingest(observation(2, 4.0, {"speed_mps": 71.0}, received_time_s=5.05))
    output = output + pipeline.close(6.0)

    assert pipeline.stats().backwards_clock == 1
    flagged = [r for r in output.normalised if LABEL_BACKWARDS_CLOCK in r.labels]
    assert len(flagged) == 1
    assert flagged[0].event.quality is Quality.INVALID
    assert "backwards" in (flagged[0].reason or "")
    assert flagged[0].event.value == pytest.approx(71.0)


def test_backwards_clock_does_not_move_the_converter_reference_backwards():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    pipeline.ingest(observation(1, 5.0, {"speed_mps": 70.0}, received_time_s=5.0))
    pipeline.ingest(observation(2, 4.0, {"speed_mps": 71.0}, received_time_s=5.05))
    pipeline.ingest(observation(3, 4.5, {"speed_mps": 72.0}, received_time_s=5.10))
    pipeline.close(6.0)
    assert pipeline.stats().backwards_clock == 2


def test_vendor_kph_field_becomes_si_mps_and_displays_back_as_kph():
    pipeline = IngestionPipeline(public_config(reorder_window_s=0.0))
    output = pipeline.ingest_all(
        [
            observation(
                0,
                10.0,
                {"speed": 324.0, "driver_number": 1, "n_gear": 8},
                source_id="public-replay",
                received_time_s=10.0,
            )
        ]
    )
    speeds = _speed_records(output.normalised)
    assert len(speeds) == 1
    event = speeds[0].event
    assert event.unit == "m/s"
    assert event.value == pytest.approx(90.0)
    spec = channel("speed_mps")
    assert spec.to_display(event.value) == pytest.approx(324.0)
    assert spec.display_unit == "km/h"


def test_unmapped_vendor_fields_are_preserved_raw_and_never_guessed():
    pipeline = IngestionPipeline(public_config(reorder_window_s=0.0))
    output = pipeline.ingest_all(
        [
            observation(
                0,
                10.0,
                {"speed": 180.0, "driver_number": 1, "n_gear": 8, "rpm": 11000, "drs": 12},
                source_id="public-replay",
                received_time_s=10.0,
            )
        ]
    )
    channels = {r.event.channel for r in output.normalised}
    assert channels == {"speed_mps"}
    raw = output.raw[0]
    assert raw.fields["n_gear"] == 8
    assert raw.fields["rpm"] == 11000
    assert raw.fields["drs"] == 12
    assert raw.mapping_revision is not None
    assert any(LABEL_UNMAPPED_FIELD in r.labels for r in output.normalised)


def test_source_restart_does_not_replay_old_packets():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    original = [observation(i, i * 0.05, {"speed_mps": 70.0}, received_time_s=i * 0.05) for i in range(3)]
    output = pipeline.ingest_all(original)
    assert len(_speed_records(output.normalised)) == 3

    replay = [
        observation(0, 0.00, {"speed_mps": 70.0}, received_time_s=5.0, restart_marker=True),
        observation(1, 0.05, {"speed_mps": 70.0}, received_time_s=5.05),
        observation(2, 0.10, {"speed_mps": 70.0}, received_time_s=5.10),
    ]
    replay_output = pipeline.ingest_all(replay)
    assert replay_output.normalised == ()
    assert all(r.reason is RejectionReason.RESTART_REPLAY for r in replay_output.rejected)
    assert pipeline.stats().replays == 3

    fresh = pipeline.ingest_all([observation(3, 0.50, {"speed_mps": 72.0}, received_time_s=6.0)])
    assert len(_speed_records(fresh.normalised)) == 1


def test_silent_restart_without_a_marker_is_still_caught_as_duplicates():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    original = [observation(i, i * 0.05, {"speed_mps": 70.0}, received_time_s=i * 0.05) for i in range(3)]
    pipeline.ingest_all(original)
    output = pipeline.ingest_all(original)
    assert output.normalised == ()
    assert pipeline.stats().duplicates == 3


def test_missing_channel_value_is_missing_with_a_reason_never_zero():
    pipeline = IngestionPipeline(public_config(reorder_window_s=0.0))
    output = pipeline.ingest_all(
        [
            observation(
                0,
                10.0,
                {"speed": -1, "driver_number": 1},
                source_id="public-replay",
                received_time_s=10.0,
            )
        ]
    )
    speeds = _speed_records(output.normalised)
    assert len(speeds) == 1
    record = speeds[0]
    assert record.event.value is None
    assert record.event.value != 0.0
    assert record.event.quality is Quality.MISSING
    assert record.reason
    assert LABEL_MISSING_VALUE in record.labels


def test_channel_never_observed_is_reported_missing_with_a_reason():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    pipeline.ingest_all([observation(0, 1.0, {"speed_mps": 70.0}, received_time_s=1.0)])
    assessment = pipeline.assess_quality(1.0)
    energy = assessment.by_channel("battery_energy_j")
    assert energy is not None
    assert energy.quality is Quality.MISSING
    assert energy.reason
    assert energy.age_s is None


def test_delayed_burst_is_reordered_within_the_window_and_latency_is_reported():
    window = 0.5
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=window))
    arrivals = [
        (observation(0, 1.0, {"speed_mps": 70.0}, received_time_s=1.00), 1.00),
        (observation(3, 1.3, {"speed_mps": 73.0}, received_time_s=1.30), 1.30),
        (observation(1, 1.1, {"speed_mps": 71.0}, received_time_s=1.45), 1.45),
        (observation(2, 1.2, {"speed_mps": 72.0}, received_time_s=1.46), 1.46),
    ]
    delivered = []
    for record, now in arrivals:
        delivered.extend(pipeline.ingest(record, now_s=now).normalised)
    now = 1.46
    while now <= 2.10:
        delivered.extend(pipeline.flush(now).normalised)
        now = round(now + 0.01, 4)
    delivered.extend(pipeline.close(2.20).normalised)

    speeds = _speed_records(delivered)
    assert [round(r.session_time_s, 3) for r in speeds] == [1.0, 1.1, 1.2, 1.3]
    assert not any(LABEL_OUT_OF_ORDER in r.labels for r in speeds)

    reorder = pipeline.stats().reorder
    assert reorder.window_s == window
    assert reorder.released == 4
    assert reorder.max_induced_latency_s == pytest.approx(window, abs=0.02)
    assert reorder.mean_induced_latency_s <= reorder.max_induced_latency_s
    assert reorder.max_reordering_depth >= 2


def test_the_window_closes_on_time_when_a_packet_never_arrives():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.3))
    pipeline.ingest(observation(0, 1.0, {"speed_mps": 70.0}, received_time_s=1.0), now_s=1.0)
    released = pipeline.flush(1.29).normalised
    assert released == ()
    released = pipeline.flush(1.31).normalised
    assert len(_speed_records(released)) == 1


def test_a_record_behind_the_released_watermark_is_archived_as_out_of_order():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.1))
    pipeline.ingest(observation(0, 1.0, {"speed_mps": 70.0}), now_s=1.0)
    pipeline.ingest(observation(1, 1.5, {"speed_mps": 71.0}), now_s=1.5)
    pipeline.flush(2.0)
    late = pipeline.ingest(observation(2, 1.05, {"speed_mps": 70.5}), now_s=2.5)
    speeds = _speed_records(late.normalised)
    assert len(speeds) == 1
    assert LABEL_OUT_OF_ORDER in speeds[0].labels
    assert pipeline.stats().reorder.late_after_close == 1


def test_sequence_assignment_is_monotonic_across_interleaved_sources():
    router = IngestionRouter([simulator_config(reorder_window_s=0.0), public_config(reorder_window_s=0.0)])
    delivered = []
    for i in range(6):
        delivered.extend(
            router.ingest(
                observation(i, i * 0.1, {"speed_mps": 70.0 + i}, received_time_s=i * 0.1)
            ).normalised
        )
        delivered.extend(
            router.ingest(
                observation(
                    i,
                    i * 0.1,
                    {"speed": 250.0 + i, "driver_number": 1},
                    source_id="public-replay",
                    received_time_s=i * 0.1,
                )
            ).normalised
        )
    delivered.extend(router.close(5.0).normalised)
    sequences = [r.event.sequence for r in delivered]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def test_sequence_allocator_never_reuses_a_number():
    allocator = SequenceAllocator()
    issued = [allocator.allocate() for _ in range(100)]
    assert issued == list(range(100))
    assert allocator.next_sequence == 100


def test_structural_faults_are_rejected_with_a_reason_not_normalised():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    bad = observation(0, 1.0, {}, received_time_s=1.0)
    output = pipeline.ingest(bad)
    assert output.normalised == ()
    assert output.rejected[0].reason is RejectionReason.STRUCTURAL
    assert "fields" in output.rejected[0].detail
    assert output.raw[0].packet_id


def test_out_of_bounds_value_is_invalid_not_clamped():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    output = pipeline.ingest_all([observation(0, 1.0, {"speed_mps": 400.0}, received_time_s=1.0)])
    record = _speed_records(output.normalised)[0]
    assert record.event.quality is Quality.INVALID
    assert record.event.value == pytest.approx(400.0)
    assert "above the registered bound" in (record.reason or "")


def test_provenance_and_session_identity_come_from_the_configuration():
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0))
    output = pipeline.ingest_all([observation(0, 1.0, {"speed_mps": 70.0}, received_time_s=1.0)])
    event = _speed_records(output.normalised)[0].event
    assert event.provenance is Provenance.SIMULATED
    assert event.session_id == SESSION_ID
    assert event.car_id == CAR_ID


@requires_parquet
def test_an_interrupted_import_leaves_no_partially_visible_chunk(tmp_path):
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all(
        [observation(i, i * 0.05, {"speed_mps": 70.0 + i}, received_time_s=i * 0.05) for i in range(4)]
    )

    recorder = TelemetryRecorder(tmp_path, SESSION_ID, mapping_revision="sim-observation-map-1")
    for record in sink.normalised:
        recorder.append_normalised(record)
    pending = recorder.stage()
    assert pending

    reader = ChunkReader(tmp_path, SESSION_ID)
    assert reader.manifest() == ()
    assert reader.read_canonical_rows() == []

    recorder.discard(pending)
    assert reader.read_normalised() == ()

    for record in sink.normalised:
        recorder.append_normalised(record)
    recorder.flush()
    assert len(reader.read_normalised()) == len(sink.normalised)
    assert reader.verify() == ()
