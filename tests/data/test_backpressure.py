"""Display data may be coalesced; raw observations and decisions may not."""

from __future__ import annotations

import pytest

from afterlap_core.data import (
    BackpressurePolicy,
    BackpressureReport,
    CoalescingBuffer,
    LosslessBuffer,
    RecordingFaultError,
)


def test_display_buffer_coalesces_by_key_and_reports_that_it_did():
    buffer = CoalescingBuffer(capacity=8, key=lambda item: item["channel"], name="telemetry_view")
    for index in range(10):
        buffer.push({"channel": "speed_mps", "value": 70.0 + index}, sequence=index)
    assert len(buffer) == 1
    assert buffer.coalesced_from_sequence == 1
    assert buffer.coalesced_to_sequence == 9

    drained = buffer.drain()
    assert drained[0]["value"] == pytest.approx(79.0)
    assert buffer.stats().coalesced == 9
    assert buffer.coalesced_from_sequence is None


def test_display_buffer_keeps_one_frame_per_channel():
    buffer = CoalescingBuffer(capacity=8, key=lambda item: item["channel"])
    for index in range(6):
        buffer.push({"channel": f"c{index % 3}", "value": index})
    assert len(buffer) == 3


def test_lossless_buffer_never_drops_and_raises_a_visible_recording_fault():
    buffer = LosslessBuffer(capacity=3, name="raw_observations")
    assert buffer.policy is BackpressurePolicy.PRESERVE
    for index in range(3):
        assert buffer.push({"packet": index}, at_s=float(index))

    with pytest.raises(RecordingFaultError) as excinfo:
        buffer.push({"packet": 3}, at_s=3.0)
    assert "recording has stopped rather than dropping" in str(excinfo.value)

    assert buffer.faulted
    fault = buffer.faults()[0]
    assert fault.visible is True
    assert fault.kind == "recording_overflow"
    assert fault.capacity == 3
    assert fault.as_dict()["buffer"] == "raw_observations"

    assert buffer.accepted == 3
    assert [item["packet"] for item in buffer.drain()] == [0, 1, 2]


def test_a_faulted_lossless_buffer_refuses_further_writes_until_cleared():
    buffer = LosslessBuffer(capacity=1, raise_on_overflow=False)
    buffer.push("a")
    assert buffer.push("b") is False
    assert buffer.faulted
    with pytest.raises(RecordingFaultError):
        buffer.push("c")
    assert buffer.clear_fault()
    assert not buffer.faulted
    buffer.drain()
    assert buffer.push("c") is True


def test_partial_drain_preserves_order():
    buffer = LosslessBuffer(capacity=10)
    for index in range(5):
        buffer.push(index)
    assert list(buffer.drain(2)) == [0, 1]
    assert list(buffer.drain()) == [2, 3, 4]


def test_report_is_unhealthy_while_a_fault_stands():
    display = CoalescingBuffer(capacity=4, key=lambda item: item)
    raw = LosslessBuffer(capacity=1, raise_on_overflow=False)
    raw.push("a")
    raw.push("b")
    report = BackpressureReport(
        display=display.stats(),
        raw_pending=len(raw),
        decision_pending=0,
        faults=raw.faults(),
    )
    assert report.healthy is False
    assert report.faults[0].visible


def test_buffers_reject_a_non_positive_capacity():
    with pytest.raises(ValueError):
        LosslessBuffer(capacity=0)
    with pytest.raises(ValueError):
        CoalescingBuffer(capacity=0, key=lambda item: item)
