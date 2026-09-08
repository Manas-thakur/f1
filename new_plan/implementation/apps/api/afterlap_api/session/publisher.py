"""Transactional-outbox publisher.

The database write and the outbox row are one transaction (``db/repository.py``),
so a crash between commit and WebSocket publish loses the *notification*, never
the record. This publisher closes that gap: it re-reads unpublished rows and
delivers them.

Ordering is deliberate: **publish, then mark published**. A crash in between
republishes the envelope, which is why delivery is at-least-once and consumers
deduplicate on ``(session_id, sequence)``. The alternative ordering would
silently lose an event, which the contract forbids for decision and quality
events. :class:`DeduplicatingConsumer` is the reference consumer-side filter.

Undeliverable rows
------------------
An outbox row whose ``event_type`` is not a ``StreamEventType`` cannot be
represented on the stream contract. ``apply_operator_action`` writes such a row
(``operator_action``). It is **not** marked published and **not** invented into
some other event type; it is quarantined, counted, and reported. The lifecycle
change it accompanies is delivered anyway, because ``_transition`` writes its own
``recommendation_updated`` row in the same transaction.

A row whose payload is missing the discriminator that ``StreamEnvelope`` needs —
``store_decision`` and ``record_execution`` write the body without it — is
repaired by *labelling* it with the row's own ``event_type`` and nothing else. No
value is added, changed or guessed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from afterlap_contracts import StreamEnvelope, StreamEventType

from ..db.engine import transaction
from ..db.repository import mark_published, unpublished_outbox
from ..stream import StreamHub, envelope_from_outbox

logger = logging.getLogger("afterlap.session.publisher")


@dataclass(frozen=True, slots=True)
class PublisherFault:
    """An outbox row that cannot be turned into a stream envelope."""

    outbox_id: str
    session_id: str
    sequence: int
    event_type: str
    reason: str


@dataclass(frozen=True, slots=True)
class PublishReport:
    """What one drain pass did."""

    published: int = 0
    repaired: int = 0
    undeliverable: tuple[PublisherFault, ...] = ()

    def __add__(self, other: PublishReport) -> PublishReport:
        return PublishReport(
            published=self.published + other.published,
            repaired=self.repaired + other.repaired,
            undeliverable=self.undeliverable + other.undeliverable,
        )


class OutboxPublisher:
    """Drains the transactional outbox onto the stream hub."""

    def __init__(
        self,
        factory: sessionmaker[OrmSession],
        hub: StreamHub,
        *,
        batch_size: int = 200,
    ) -> None:
        self._factory = factory
        self._hub = hub
        self._batch_size = batch_size
        self._faults: dict[str, PublisherFault] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def undeliverable(self) -> tuple[PublisherFault, ...]:
        return tuple(self._faults.values())

    async def drain_once(self) -> PublishReport:
        """Publish every unpublished row, oldest first."""
        report = PublishReport()
        with transaction(self._factory) as db:
            rows = unpublished_outbox(db, limit=self._batch_size)
            for row in rows:
                if row.id in self._faults:
                    continue
                envelope, repaired, reason = _envelope_for(row)
                if envelope is None:
                    fault = PublisherFault(
                        outbox_id=row.id,
                        session_id=row.session_id,
                        sequence=row.sequence,
                        event_type=row.event_type,
                        reason=reason or "unrepresentable outbox row",
                    )
                    self._faults[row.id] = fault
                    logger.warning(
                        "outbox row %s (%s seq %d) is not representable on the stream contract: %s",
                        row.id,
                        row.event_type,
                        row.sequence,
                        fault.reason,
                    )
                    report = report + PublishReport(undeliverable=(fault,))
                    continue
                # Publish first, mark second: an at-least-once delivery is
                # recoverable by the consumer, a lost lossless event is not.
                await self._hub.publish(envelope)
                mark_published(db, row)
                report = report + PublishReport(published=1, repaired=1 if repaired else 0)
        return report

    async def run(self, *, interval_s: float = 0.05, stop: asyncio.Event | None = None) -> None:
        """Background drain loop."""
        while stop is None or not stop.is_set():
            try:
                await self.drain_once()
            except Exception:
                logger.exception("outbox drain failed; retrying")
            await asyncio.sleep(interval_s)

    def start(self, *, interval_s: float = 0.05) -> asyncio.Task[None]:
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self.run(interval_s=interval_s, stop=self._stop))
        return self._task

    async def stop_running(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None


@dataclass(slots=True)
class DeduplicatingConsumer:
    """Reference consumer-side filter for at-least-once delivery.

    Delivery is at least once, so the client deduplicates on
    ``(session_id, sequence)``. This is the exact rule the frontend stream
    reducer must implement; it is here so a test can assert the guarantee rather
    than assume it.
    """

    seen: set[tuple[str, int]] = field(default_factory=set)
    accepted: list[StreamEnvelope] = field(default_factory=list)
    duplicates: int = 0

    def offer(self, envelope: StreamEnvelope) -> bool:
        key = (envelope.session_id, envelope.sequence)
        if key in self.seen:
            self.duplicates += 1
            return False
        self.seen.add(key)
        self.accepted.append(envelope)
        return True

    def of_type(self, event_type: StreamEventType) -> tuple[StreamEnvelope, ...]:
        return tuple(e for e in self.accepted if e.event_type is event_type)


def _envelope_for(row: Any) -> tuple[StreamEnvelope | None, bool, str | None]:
    """Build an envelope from an outbox row, repairing only a missing tag."""
    try:
        return envelope_from_outbox(row), False, None
    except Exception as error:
        first = f"{type(error).__name__}: {error}"

    if row.event_type not in set(StreamEventType):
        return (
            None,
            False,
            (
                f"event type {row.event_type!r} has no StreamEventType; it cannot be published "
                "without inventing a different event"
            ),
        )

    envelope = dict(row.envelope)
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or "event_type" in payload:
        return None, False, f"payload cannot be labelled: {first}"
    repaired = dict(envelope)
    repaired["payload"] = {"event_type": row.event_type, **payload}
    try:
        return StreamEnvelope.model_validate(repaired), True, None
    except Exception as second:
        return None, False, f"payload is invalid even once labelled: {second}"


__all__ = [
    "DeduplicatingConsumer",
    "OutboxPublisher",
    "PublishReport",
    "PublisherFault",
]
