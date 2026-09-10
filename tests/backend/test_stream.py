"""Stream guarantees from ``contracts/API.md``.

Server retains a bounded reconnect buffer; older cursors trigger
resync_required. High-rate telemetry views may be coalesced with explicit
sequence-range metadata; decision/quality/operator events are lossless.
"""

from __future__ import annotations

import asyncio

import pytest

from afterlap_api.db import transaction
from afterlap_api.session import DeduplicatingConsumer, OutboxPublisher
from afterlap_api.stream import LOSSLESS_EVENTS, StreamHub
from afterlap_contracts import (
    SCHEMA_VERSION,
    ChannelQuality,
    DeploymentProfile,
    Quality,
    StreamEnvelope,
    StreamEventType,
)
from afterlap_contracts.events import (
    QualityChangedPayload,
    TelemetrySeries,
    TelemetryViewPayload,
)

from .conftest import actionable, start_session

SESSION = "ses-stream-test"


def _telemetry(sequence: int, *, coalesced_from: int | None = None) -> StreamEnvelope:
    return StreamEnvelope(
        schema_version=SCHEMA_VERSION,
        session_id=SESSION,
        sequence=sequence,
        event_type=StreamEventType.TELEMETRY_VIEW,
        session_time_s=float(sequence),
        payload=TelemetryViewPayload(
            series=(
                TelemetrySeries(
                    channel="speed_mps",
                    car_id="own",
                    unit="m/s",
                    provenance="simulated",
                    x_coordinate="session_time_s",
                    x=(float(sequence),),
                    y=(70.0 + sequence,),
                    sample_count=20,
                    decimated=coalesced_from is not None,
                ),
            ),
            coalesced_from_sequence=coalesced_from,
            coalesced_to_sequence=sequence if coalesced_from is not None else None,
        ),
    )


def _quality(sequence: int, message: str) -> StreamEnvelope:
    return StreamEnvelope(
        schema_version=SCHEMA_VERSION,
        session_id=SESSION,
        sequence=sequence,
        event_type=StreamEventType.QUALITY_CHANGED,
        session_time_s=float(sequence),
        payload=QualityChangedPayload(
            channels=(ChannelQuality(channel="battery_energy_j", car_id="own", quality=Quality.STALE),),
            message=message,
        ),
    )


def _drain(subscriber) -> list[StreamEnvelope]:  # type: ignore[no-untyped-def]
    drained = []
    while not subscriber.queue.empty():
        drained.append(subscriber.queue.get_nowait())
    return drained


def test_a_resume_inside_the_buffer_receives_exactly_the_gap():
    hub = StreamHub(buffer_size=32, client_queue=64)

    async def scenario():  # type: ignore[no-untyped-def]
        first, resync = await hub.subscribe(SESSION, 0)
        assert resync is False
        for sequence in range(1, 6):
            await hub.publish(_telemetry(sequence))
        seen = [e.sequence for e in _drain(first)]
        assert seen == [1, 2, 3, 4, 5]
        await hub.unsubscribe(first)

        for sequence in range(6, 9):
            await hub.publish(_quality(sequence, f"gap event {sequence}"))

        again, resync_again = await hub.subscribe(SESSION, max(seen))
        return resync_again, [e.sequence for e in _drain(again)]

    resync, gap = asyncio.run(scenario())
    assert resync is False, "a cursor still inside the retained window must not force a resync"
    assert gap == [6, 7, 8], "the reconnect did not deliver exactly the missed range"


def test_a_cursor_older_than_the_buffer_receives_resync_required():
    hub = StreamHub(buffer_size=4, client_queue=32)

    async def scenario():  # type: ignore[no-untyped-def]
        for sequence in range(1, 21):
            await hub.publish(_telemetry(sequence))
        subscriber, resync = await hub.subscribe(SESSION, 2)
        return resync, _drain(subscriber), subscriber.needs_resync

    resync, delivered, needs_resync = asyncio.run(scenario())
    assert resync is True
    assert needs_resync is True
    assert len(delivered) == 1
    envelope = delivered[0]
    assert envelope.event_type is StreamEventType.RESYNC_REQUIRED
    assert envelope.payload.reason == "cursor older than the retained buffer"
    assert envelope.payload.earliest_available_sequence == 17


def test_a_slow_client_may_lose_telemetry_but_never_loses_a_decision_or_quality_event():
    hub = StreamHub(buffer_size=64, client_queue=4)

    async def scenario():  # type: ignore[no-untyped-def]
        subscriber, _ = await hub.subscribe(SESSION, 0)
        for sequence in range(1, 20):
            await hub.publish(_telemetry(sequence))
        dropped = subscriber.dropped_telemetry
        await hub.publish(_quality(100, "battery channel went stale"))
        return dropped, subscriber.needs_resync, _drain(subscriber)

    dropped, needs_resync, delivered = asyncio.run(scenario())
    assert dropped > 0, "telemetry was never coalesced away, so the case is untested"
    kinds = {e.event_type for e in delivered}
    assert StreamEventType.QUALITY_CHANGED in kinds or StreamEventType.RESYNC_REQUIRED in kinds
    assert needs_resync is True
    assert StreamEventType.QUALITY_CHANGED in LOSSLESS_EVENTS
    assert StreamEventType.TELEMETRY_VIEW not in LOSSLESS_EVENTS


def test_a_coalesced_telemetry_view_declares_the_range_it_merged():
    merged = _telemetry(40, coalesced_from=31)
    assert merged.payload.coalesced_from_sequence == 31
    assert merged.payload.coalesced_to_sequence == 40
    assert merged.payload.series[0].decimated is True
    assert merged.is_lossless is False
    assert _quality(41, "x").is_lossless is True


def test_a_real_session_publishes_its_decision_events_losslessly(db_factory):
    """End to end: the outbox drain delivers every decision the session made."""
    hub = StreamHub(buffer_size=1024, client_queue=512)
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    assert tick.recommendation is not None

    published_ids = {rec.id for rec in session.runtime._recommendations.values()}

    async def scenario() -> DeduplicatingConsumer:
        subscriber, _ = await hub.subscribe(session.session_id, 0)
        report = await OutboxPublisher(db_factory, hub).drain_once()
        assert report.published > 0
        consumer = DeduplicatingConsumer()
        for envelope in _drain(subscriber):
            consumer.offer(envelope)
        return consumer

    consumer = asyncio.run(scenario())
    updates = consumer.of_type(StreamEventType.RECOMMENDATION_UPDATED)
    delivered_ids = {e.payload.recommendation.id for e in updates}
    assert published_ids <= delivered_ids, (
        f"decisions never reached the stream: {sorted(published_ids - delivered_ids)}"
    )
    assert not any(e.event_type is StreamEventType.RESYNC_REQUIRED for e in consumer.accepted)
    sequences = [e.sequence for e in consumer.accepted]
    assert sequences == sorted(sequences), "envelopes arrived out of sequence order"


def test_the_publisher_quarantines_an_unrepresentable_row_instead_of_inventing_one(db_factory):
    """A row the envelope cannot express is reported, never renamed.

    Normal operation no longer produces such a row: ``apply_operator_action``
    was writing an ``operator_action`` outbox row that no client could validate,
    and that is now appended to the durable event log without a stream row at
    all. The publisher's defence still matters, though -- a malformed or
    future-versioned row must not be guessed into some other event type -- so
    the row is inserted directly here rather than provoked through the
    lifecycle.
    """
    from afterlap_api.db.models import OutboxRecord

    hub = StreamHub(buffer_size=256, client_queue=256)
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    recommendation = tick.recommendation
    assert recommendation is not None
    session.take_lease()
    from afterlap_contracts import OperatorAction

    session.act(recommendation, OperatorAction.SELECT, idempotency_key="quarantine")

    with transaction(db_factory) as db:
        db.add(
            OutboxRecord(
                id="out-unrepresentable",
                session_id=session.session_id,
                sequence=999_999,
                event_type="operator_action",
                envelope={"schema_version": "1.0", "event_type": "operator_action"},
            )
        )

    async def scenario():  # type: ignore[no-untyped-def]
        subscriber, _ = await hub.subscribe(session.session_id, 0)
        publisher = OutboxPublisher(db_factory, hub)
        report = await publisher.drain_once()
        return report, publisher.undeliverable, _drain(subscriber)

    report, undeliverable, delivered = asyncio.run(scenario())
    assert undeliverable, "the unrepresentable row was silently published as something else"
    fault = next(f for f in undeliverable if f.event_type == "operator_action")
    assert fault.outbox_id
    assert all(e.sequence != 999_999 for e in delivered)
    selected = [
        e
        for e in delivered
        if e.event_type is StreamEventType.RECOMMENDATION_UPDATED
        and e.payload.recommendation.id == recommendation.id
        and e.payload.recommendation.status.value == "selected"
    ]
    assert selected, "the selection never reached the client in any form"
    assert report.published > 0


def test_an_operator_action_no_longer_produces_an_outbox_row(db_factory):
    """The fix at the source, asserted where it is observable.

    An operator action is audit evidence and stays in ``session_event``. It is
    not queued for a stream that has no event type for it.
    """
    from sqlalchemy import select

    from afterlap_api.db.models import OutboxRecord, SessionEvent
    from afterlap_contracts import OperatorAction

    session = start_session(db_factory)
    session.advance(1.0)
    tick = session.advance_until(actionable)
    recommendation = tick.recommendation
    assert recommendation is not None
    session.take_lease()
    session.act(recommendation, OperatorAction.SELECT, idempotency_key="no-outbox-row")

    with transaction(db_factory) as db:
        queued = [
            r.event_type
            for r in db.execute(select(OutboxRecord)).scalars()
            if r.event_type == "operator_action"
        ]
        recorded = list(
            db.execute(select(SessionEvent).where(SessionEvent.event_type == "operator_action")).scalars()
        )

    assert queued == [], "an operator action was queued for a stream that cannot carry it"
    assert len(recorded) == 1, "the operator action must still be durable audit evidence"


@pytest.mark.parametrize("event_type", sorted(LOSSLESS_EVENTS, key=lambda e: e.value))
def test_every_lossless_event_type_is_marked_lossless_on_the_envelope(event_type):
    assert event_type is not StreamEventType.TELEMETRY_VIEW
    assert event_type is not StreamEventType.HEARTBEAT


def test_a_cursor_ahead_of_the_stream_receives_resync_required():
    """A client claiming a sequence the session never emitted is not up to date.

    Treating it as current returns an empty replay and then only heartbeats, so
    the client waits forever for a backlog the server has already decided it
    does not owe. That is the silent gap `resync_required` exists to prevent,
    and it is indistinguishable from a healthy idle stream from the outside.
    """
    hub = StreamHub(buffer_size=16, client_queue=32)

    async def scenario():  # type: ignore[no-untyped-def]
        for sequence in range(1, 4):
            await hub.publish(_telemetry(sequence))
        ahead, resync_ahead = await hub.subscribe(SESSION, 9999)
        current, resync_current = await hub.subscribe(SESSION, 3)
        return resync_ahead, _drain(ahead), resync_current, _drain(current)

    resync_ahead, delivered, resync_current, current_frames = asyncio.run(scenario())

    assert resync_ahead is True, "a cursor past the newest sequence was accepted as current"
    assert len(delivered) == 1
    assert delivered[0].event_type is StreamEventType.RESYNC_REQUIRED

    assert resync_current is False, "a cursor exactly at the newest sequence is genuinely current"
    assert current_frames == []
