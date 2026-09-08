"""WebSocket fan-out with a bounded reconnect buffer.

Rules from ``contracts/API.md``:

- a client resumes from ``after_sequence``; a cursor older than the retained
  window gets ``resync_required`` rather than a silent gap
- decision, quality and operator events are lossless; only telemetry views and
  heartbeats may be coalesced or dropped
- a slow client receives a snapshot instruction, never an unbounded queue
- a heartbeat proves the connection exists, and nothing about data freshness
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from afterlap_contracts import SCHEMA_VERSION, StreamEnvelope, StreamEventType
from afterlap_contracts.events import HeartbeatPayload, ResyncRequiredPayload

DEFAULT_BUFFER = 512
DEFAULT_CLIENT_QUEUE = 64

LOSSLESS_EVENTS = frozenset(
    {
        StreamEventType.SNAPSHOT,
        StreamEventType.ESTIMATE_UPDATED,
        StreamEventType.RECOMMENDATION_UPDATED,
        StreamEventType.EXECUTION_OBSERVED,
        StreamEventType.RULE_CONTEXT_CHANGED,
        StreamEventType.QUALITY_CHANGED,
        StreamEventType.EXPERIMENT_PROGRESS,
        StreamEventType.RESYNC_REQUIRED,
    }
)


@dataclass(slots=True)
class Subscriber:
    """One connected client."""

    session_id: str
    queue: asyncio.Queue[StreamEnvelope]
    last_sent_sequence: int = 0
    dropped_telemetry: int = 0
    needs_resync: bool = False


@dataclass(slots=True)
class SessionChannel:
    """Retained history and subscribers for one session."""

    session_id: str
    buffer: deque[StreamEnvelope] = field(default_factory=lambda: deque(maxlen=DEFAULT_BUFFER))
    subscribers: list[Subscriber] = field(default_factory=list)

    @property
    def earliest_sequence(self) -> int:
        return self.buffer[0].sequence if self.buffer else 0

    @property
    def latest_sequence(self) -> int:
        return self.buffer[-1].sequence if self.buffer else 0

    def replay_from(self, after_sequence: int) -> list[StreamEnvelope]:
        return [e for e in self.buffer if e.sequence > after_sequence]

    def can_replay(self, after_sequence: int) -> bool:
        """True when the retained window still covers the client's cursor."""
        if not self.buffer:
            return after_sequence == 0
        if after_sequence >= self.latest_sequence:
            return True
        return after_sequence >= self.earliest_sequence - 1


class StreamHub:
    """Publishes envelopes to subscribers of one session at a time."""

    def __init__(
        self, *, buffer_size: int = DEFAULT_BUFFER, client_queue: int = DEFAULT_CLIENT_QUEUE
    ) -> None:
        self._channels: dict[str, SessionChannel] = {}
        self._buffer_size = buffer_size
        self._client_queue = client_queue
        self._lock = asyncio.Lock()
        self._resyncs = 0

    def channel(self, session_id: str) -> SessionChannel:
        channel = self._channels.get(session_id)
        if channel is None:
            channel = SessionChannel(session_id=session_id, buffer=deque(maxlen=self._buffer_size))
            self._channels[session_id] = channel
        return channel

    async def subscribe(self, session_id: str, after_sequence: int = 0) -> tuple[Subscriber, bool]:
        """Attach a client. Returns the subscriber and whether it must resync."""
        async with self._lock:
            channel = self.channel(session_id)
            subscriber = Subscriber(
                session_id=session_id,
                queue=asyncio.Queue(maxsize=self._client_queue),
                last_sent_sequence=after_sequence,
            )
            channel.subscribers.append(subscriber)

            if not channel.can_replay(after_sequence):
                subscriber.needs_resync = True
                await subscriber.queue.put(
                    self._resync_envelope(session_id, channel, "cursor older than the retained buffer")
                )
                return subscriber, True

            for envelope in channel.replay_from(after_sequence):
                subscriber.queue.put_nowait(envelope)
                subscriber.last_sent_sequence = envelope.sequence
            return subscriber, False

    async def unsubscribe(self, subscriber: Subscriber) -> None:
        async with self._lock:
            channel = self._channels.get(subscriber.session_id)
            if channel and subscriber in channel.subscribers:
                channel.subscribers.remove(subscriber)

    async def publish(self, envelope: StreamEnvelope) -> None:
        """Fan out one envelope, retaining it for reconnects."""
        async with self._lock:
            channel = self.channel(envelope.session_id)
            channel.buffer.append(envelope)
            for subscriber in list(channel.subscribers):
                self._deliver(channel, subscriber, envelope)

    def _deliver(self, channel: SessionChannel, subscriber: Subscriber, envelope: StreamEnvelope) -> None:
        try:
            subscriber.queue.put_nowait(envelope)
            subscriber.last_sent_sequence = envelope.sequence
            return
        except asyncio.QueueFull:
            pass

        if envelope.event_type not in LOSSLESS_EVENTS:
            subscriber.dropped_telemetry += 1
            return

        subscriber.needs_resync = True
        with contextlib.suppress(asyncio.QueueFull):
            _drain_one(subscriber.queue)
            subscriber.queue.put_nowait(
                self._resync_envelope(channel.session_id, channel, "client too slow for a lossless event")
            )

    @property
    def resync_count(self) -> int:
        """How many resync instructions this process has issued.

        Counted at the point the envelope is built, so a cursor outside the
        retained window and a client too slow for a lossless event both land
        here: to an operator they are the same failure to keep up.
        """
        return self._resyncs

    def _resync_envelope(self, session_id: str, channel: SessionChannel, reason: str) -> StreamEnvelope:
        self._resyncs += 1
        return StreamEnvelope(
            schema_version=SCHEMA_VERSION,
            session_id=session_id,
            sequence=channel.latest_sequence,
            event_type=StreamEventType.RESYNC_REQUIRED,
            session_time_s=0.0,
            payload=ResyncRequiredPayload(
                reason=reason, earliest_available_sequence=channel.earliest_sequence
            ),
        )

    def heartbeat(self, session_id: str, uptime_s: float) -> StreamEnvelope:
        channel = self.channel(session_id)
        return StreamEnvelope(
            schema_version=SCHEMA_VERSION,
            session_id=session_id,
            sequence=channel.latest_sequence,
            event_type=StreamEventType.HEARTBEAT,
            session_time_s=0.0,
            payload=HeartbeatPayload(server_uptime_s=uptime_s),
        )

    def subscriber_count(self, session_id: str) -> int:
        channel = self._channels.get(session_id)
        return len(channel.subscribers) if channel else 0

    def close_session(self, session_id: str) -> None:
        self._channels.pop(session_id, None)


def _drain_one(queue: asyncio.Queue[Any]) -> None:
    with contextlib.suppress(asyncio.QueueEmpty):
        queue.get_nowait()


def envelope_from_outbox(record: Any) -> StreamEnvelope:
    """Rebuild a typed envelope from a stored outbox row.

    Validation happens here, so a malformed stored payload fails at publish
    time rather than reaching a client.
    """
    return StreamEnvelope.model_validate(record.envelope)


__all__ = [
    "DEFAULT_BUFFER",
    "DEFAULT_CLIENT_QUEUE",
    "LOSSLESS_EVENTS",
    "SessionChannel",
    "StreamHub",
    "Subscriber",
    "envelope_from_outbox",
]
