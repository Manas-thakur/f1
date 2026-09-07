"""Contract vector 3: a late event is archived but cannot alter a finalised decision.

An event at source time 12.0 arriving after a published cutoff 12.2 remains
archived but cannot alter that decision record.
"""

from __future__ import annotations

import pytest
from .conftest import SESSION_ID, observation, simulator_config

from afterlap_core.data import (
    LABEL_EXCLUDED_FROM_FINALISED,
    LABEL_OUT_OF_ORDER,
    ChunkReader,
    IngestionPipeline,
    MemorySink,
    ReplaySession,
    TelemetryRecorder,
    sort_normalised,
)

CUTOFF_S = 12.2


def _pipeline_with_history(sink: MemorySink | None = None) -> IngestionPipeline:
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.1), sink=sink)
    for index, source_time in enumerate((12.0, 12.1, 12.2)):
        pipeline.ingest(
            observation(index, source_time, {"speed_mps": 70.0 + index}, received_time_s=source_time),
            now_s=source_time,
        )
    pipeline.flush(12.5)
    return pipeline


def test_a_late_event_is_archived_but_excluded_from_the_finalised_decision_state():
    sink = MemorySink()
    pipeline = _pipeline_with_history(sink)

    # A decision is published with observation_cutoff_s = 12.2.
    observed_at_publication = sort_normalised(sink.normalised)
    pipeline.finalise(CUTOFF_S)
    assert pipeline.finalised_before_s == CUTOFF_S

    # A packet for source time 12.0 now arrives, long after the cutoff.
    late = pipeline.ingest(
        observation(9, 12.0, {"speed_mps": 70.5}, received_time_s=12.9),
        now_s=12.9,
    )
    published = pipeline.flush(13.5)
    late_records = [*late.normalised, *published.normalised]
    assert len(late_records) == 1
    record = late_records[0]

    # Archived, with its value intact and honest labels.
    assert record.event.source_time_s == pytest.approx(12.0)
    assert record.event.value == pytest.approx(70.5)
    assert LABEL_OUT_OF_ORDER in record.labels
    assert LABEL_EXCLUDED_FROM_FINALISED in record.labels
    assert record.finalised_before_s == CUTOFF_S
    assert "after the decision cutoff" in (record.reason or "")

    # It is not usable for decisions, and the state that decision observed is
    # byte-for-byte what it was at publication time.
    assert record.usable_for_decisions is False
    assert late.decision_visible() == ()
    still_visible = sort_normalised(r for r in sink.normalised if r.usable_for_decisions)
    assert still_visible == observed_at_publication
    assert pipeline.stats().excluded_from_finalised == 1


def test_the_late_event_reaches_the_archive_on_disk(tmp_path):
    sink = MemorySink()
    pipeline = _pipeline_with_history(sink)
    pipeline.finalise(CUTOFF_S)
    pipeline.ingest(observation(9, 12.0, {"speed_mps": 70.5}, received_time_s=12.9), now_s=12.9)
    pipeline.flush(13.5)

    recorder = TelemetryRecorder(tmp_path, SESSION_ID, mapping_revision="sim-observation-map-1")
    for record in sink.normalised:
        recorder.append_normalised(record)
    recorder.flush()

    stored = ChunkReader(tmp_path, SESSION_ID).read_normalised()
    assert len(stored) == len(sink.normalised)
    excluded = [r for r in stored if not r.usable_for_decisions]
    assert len(excluded) == 1
    assert excluded[0].event.source_time_s == pytest.approx(12.0)
    assert excluded[0].finalised_before_s == CUTOFF_S


def test_replay_can_exclude_or_include_the_late_event_explicitly():
    sink = MemorySink()
    pipeline = _pipeline_with_history(sink)
    pipeline.finalise(CUTOFF_S)
    pipeline.ingest(observation(9, 12.0, {"speed_mps": 70.5}, received_time_s=12.9), now_s=12.9)
    pipeline.flush(13.5)

    full = ReplaySession(sink.normalised)
    decisions = ReplaySession(sink.normalised, decisions_only=True)
    assert len(full.records) == len(decisions.records) + 1
    assert all(r.usable_for_decisions for r in decisions.records)


def test_a_decision_cutoff_never_moves_backwards():
    pipeline = _pipeline_with_history()
    pipeline.finalise(CUTOFF_S)
    pipeline.finalise(CUTOFF_S + 1.0)
    with pytest.raises(ValueError):
        pipeline.finalise(CUTOFF_S)


def test_an_event_after_the_cutoff_stays_usable():
    sink = MemorySink()
    pipeline = _pipeline_with_history(sink)
    pipeline.finalise(CUTOFF_S)
    output = pipeline.ingest(observation(10, 12.4, {"speed_mps": 74.0}, received_time_s=12.4), now_s=12.4)
    output = output + pipeline.flush(12.8)
    fresh = [r for r in output.normalised if r.event.source_time_s > CUTOFF_S]
    assert len(fresh) == 1
    assert fresh[0].usable_for_decisions is True
    assert LABEL_EXCLUDED_FROM_FINALISED not in fresh[0].labels
