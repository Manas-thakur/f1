from __future__ import annotations

from bisect import insort
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from afterlap_contracts import Quality

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class EventPriority(IntEnum):
    SAFETY_OR_RULE_INVALIDATION = 0
    PHYSICAL_LINE_EVENT = 1
    PLAN_VALIDATION = 2
    OPERATOR_COMMAND = 3
    UI_SNAPSHOT = 4


@dataclass(frozen=True, slots=True, order=True)
class ScheduledEvent[T]:
    time_s: float
    priority: EventPriority
    tiebreak: int
    payload: T = field(compare=False)


class EventQueue[T]:
    def __init__(self) -> None:
        self._events: list[ScheduledEvent[T]] = []
        self._counter = 0

    def push(self, time_s: float, priority: EventPriority, payload: T) -> None:
        insort(self._events, ScheduledEvent(time_s, priority, self._counter, payload))
        self._counter += 1

    def pop_until(self, time_s: float) -> Iterator[ScheduledEvent[T]]:

        while self._events and self._events[0].time_s <= time_s:
            yield self._events.pop(0)

    def peek_time(self) -> float | None:
        return self._events[0].time_s if self._events else None

    def __len__(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        self._events.clear()

    def snapshot(self) -> tuple[ScheduledEvent[T], ...]:
        return tuple(self._events)

    def restore(self, events: Iterable[ScheduledEvent[T]], counter: int) -> None:
        self._events = sorted(events)
        self._counter = counter

    @property
    def counter(self) -> int:
        return self._counter


@dataclass(slots=True)
class SessionClock:
    session_time_s: float = 0.0
    paused: bool = False
    clock_error_s: float = 0.0
    speed: float = 1.0

    def advance(self, dt_s: float) -> float:
        if dt_s < 0.0:
            raise ValueError("the session clock never runs backwards")
        if not self.paused:
            self.session_time_s += dt_s
        return self.session_time_s

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def set_speed(self, speed: float) -> None:

        if speed <= 0.0:
            raise ValueError("replay speed must be positive")
        self.speed = speed


@dataclass(frozen=True, slots=True)
class ClockMapping:
    source_id: str
    offset_s: float
    drift: float = 0.0
    uncertainty_s: float = 0.0

    def to_session_time(self, source_time_s: float) -> float:
        return source_time_s * (1.0 + self.drift) + self.offset_s

    def to_source_time(self, session_time_s: float) -> float:
        return (session_time_s - self.offset_s) / (1.0 + self.drift)


def crossing_time(
    start_time_s: float,
    end_time_s: float,
    start_value: float,
    end_value: float,
    threshold: float,
) -> float | None:

    if start_value == end_value:
        return None
    low, high = (start_value, end_value) if start_value < end_value else (end_value, start_value)
    if not (low <= threshold <= high):
        return None
    fraction = (threshold - start_value) / (end_value - start_value)
    if not (0.0 <= fraction <= 1.0):
        return None
    return start_time_s + fraction * (end_time_s - start_time_s)


def classify_freshness(
    age_s: float | None,
    expected_period_s: float | None,
    *,
    stale_periods: float = 4.0,
    degraded_periods: float = 2.0,
    missing_periods: float = 20.0,
) -> Quality:

    if age_s is None:
        return Quality.MISSING
    if age_s < 0.0:
        return Quality.INVALID
    if expected_period_s is None or expected_period_s <= 0.0:
        return Quality.DEGRADED
    if age_s >= missing_periods * expected_period_s:
        return Quality.MISSING
    if age_s >= stale_periods * expected_period_s:
        return Quality.STALE
    if age_s >= degraded_periods * expected_period_s:
        return Quality.DEGRADED
    return Quality.VALID


def wrap_s(s_m: float, track_length_m: float) -> float:

    if track_length_m <= 0.0:
        raise ValueError("track length must be positive")
    return s_m % track_length_m


def progress_of(completed_laps: int, s_m: float, track_length_m: float) -> float:

    return completed_laps * track_length_m + wrap_s(s_m, track_length_m)


def laps_and_s(progress_m: float, track_length_m: float) -> tuple[int, float]:

    if track_length_m <= 0.0:
        raise ValueError("track length must be positive")
    laps = int(progress_m // track_length_m)
    return laps, progress_m - laps * track_length_m


__all__ = [
    "ClockMapping",
    "EventPriority",
    "EventQueue",
    "ScheduledEvent",
    "SessionClock",
    "classify_freshness",
    "crossing_time",
    "laps_and_s",
    "progress_of",
    "wrap_s",
]
