"""Bounded buffers with different overflow policies per data class.

Display traces may be coalesced: a chart that skips an intermediate frame is
still honest. Decisions and raw observations may not be coalesced or dropped,
because a missing raw observation is a hole in the archive and a missing
decision event is a lost audit trail.

So overflow on a lossless buffer raises a *visible recording fault* and stops
the buffer rather than quietly discarding the oldest item. A visible fault is
recoverable; silent data loss is not.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class BackpressurePolicy(StrEnum):
    COALESCE = "coalesce"
    PRESERVE = "preserve"


class RecordingFaultError(RuntimeError):
    """A lossless buffer overflowed. Recording must stop and be surfaced."""


@dataclass(frozen=True, slots=True)
class RecordingFault:
    """An operator-visible recording fault."""

    kind: str
    buffer_name: str
    message: str
    at_s: float
    capacity: int
    pending: int
    visible: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "buffer": self.buffer_name,
            "message": self.message,
            "at_s": self.at_s,
            "capacity": self.capacity,
            "pending": self.pending,
            "visible": self.visible,
        }


@dataclass(frozen=True, slots=True)
class CoalesceStats:
    accepted: int
    coalesced: int
    emitted: int


class CoalescingBuffer[T]:
    """Display path: newest value per key wins, older frames are merged away.

    Coalescing is recorded (``coalesced_from``/``coalesced_to``) so the client
    can tell it received a merged view rather than every frame.
    """

    def __init__(self, capacity: int, key: Callable[[T], object], name: str = "display") -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.name = name
        self._key = key
        self._items: dict[object, T] = {}
        self._accepted = 0
        self._coalesced = 0
        self._emitted = 0
        self.coalesced_from_sequence: int | None = None
        self.coalesced_to_sequence: int | None = None

    def push(self, item: T, *, sequence: int | None = None) -> bool:
        key = self._key(item)
        self._accepted += 1
        if key in self._items:
            self._coalesced += 1
            if sequence is not None:
                if self.coalesced_from_sequence is None:
                    self.coalesced_from_sequence = sequence
                self.coalesced_to_sequence = sequence
        elif len(self._items) >= self.capacity:
            oldest = next(iter(self._items))
            del self._items[oldest]
            self._coalesced += 1
        self._items[key] = item
        return True

    def drain(self) -> tuple[T, ...]:
        items = tuple(self._items.values())
        self._items.clear()
        self._emitted += len(items)
        self.coalesced_from_sequence = None
        self.coalesced_to_sequence = None
        return items

    def __len__(self) -> int:
        return len(self._items)

    def stats(self) -> CoalesceStats:
        return CoalesceStats(accepted=self._accepted, coalesced=self._coalesced, emitted=self._emitted)


class LosslessBuffer[T]:
    """Decision and raw-observation path: nothing is dropped or merged.

    On overflow the buffer records a :class:`RecordingFault` and refuses further
    writes. ``raise_on_overflow`` (the default) turns that into an exception so
    an ingestion loop cannot ignore it by accident.
    """

    def __init__(
        self,
        capacity: int,
        *,
        name: str = "lossless",
        raise_on_overflow: bool = True,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.name = name
        self.raise_on_overflow = raise_on_overflow
        self.policy = BackpressurePolicy.PRESERVE
        self._items: deque[T] = deque()
        self._faults: list[RecordingFault] = []
        self._accepted = 0

    @property
    def faulted(self) -> bool:
        return bool(self._faults)

    def faults(self) -> tuple[RecordingFault, ...]:
        return tuple(self._faults)

    def push(self, item: T, *, at_s: float = 0.0) -> bool:
        if self.faulted:
            raise RecordingFaultError(
                f"buffer {self.name!r} is in a recording fault; clear it before writing again"
            )
        if len(self._items) >= self.capacity:
            fault = RecordingFault(
                kind="recording_overflow",
                buffer_name=self.name,
                message=(
                    f"{self.name} buffer reached capacity {self.capacity}; "
                    "observations are preserved and recording has stopped rather than dropping them"
                ),
                at_s=at_s,
                capacity=self.capacity,
                pending=len(self._items),
            )
            self._faults.append(fault)
            if self.raise_on_overflow:
                raise RecordingFaultError(fault.message)
            return False
        self._items.append(item)
        self._accepted += 1
        return True

    def drain(self, limit: int | None = None) -> tuple[T, ...]:
        count = len(self._items) if limit is None else min(limit, len(self._items))
        return tuple(self._items.popleft() for _ in range(count))

    def clear_fault(self) -> tuple[RecordingFault, ...]:
        faults, self._faults = tuple(self._faults), []
        return faults

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    @property
    def accepted(self) -> int:
        return self._accepted


@dataclass(slots=True)
class BackpressureReport:
    """Combined health of one ingestion path."""

    display: CoalesceStats
    raw_pending: int
    decision_pending: int
    faults: tuple[RecordingFault, ...] = field(default_factory=tuple)

    @property
    def healthy(self) -> bool:
        return not self.faults


__all__ = [
    "BackpressurePolicy",
    "BackpressureReport",
    "CoalesceStats",
    "CoalescingBuffer",
    "LosslessBuffer",
    "RecordingFault",
    "RecordingFaultError",
]
