"""Replay clock and archive replay over the canonical session clock.

Two properties are load-bearing.

**Speed is pacing only.** ``ReplayClock.speed`` divides the wall-clock time a
given simulated interval takes to play. It never scales simulated timestamps,
never changes which samples fall inside a step, and therefore never changes an
integration result. ``wall_clock_duration_for`` is the only place the speed is
allowed to appear.

**Seek never looks forward.** Seeking loads the newest estimator snapshot at or
before the target, rewinds the cursor to that snapshot, and replays forward.
The cursor is bounded by the current cutoff, so no sample after the cutoff can
be evaluated at the cutoff.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from afterlap_contracts import SessionMode
from afterlap_core.timebase import SessionClock

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from .pipeline import NormalisedRecord


@dataclass(frozen=True, slots=True)
class ModeBadge:
    """How a session's provenance is announced in the interface."""

    mode: SessionMode
    counterfactual: bool
    label: str
    token: str
    detail: str


LIVE_BADGE = ModeBadge(
    mode=SessionMode.LIVE_TEAM,
    counterfactual=False,
    label="Live acquisition",
    token="--badge-live",
    detail="Observations are arriving from an authorised feed in real time.",
)
REPLAY_BADGE = ModeBadge(
    mode=SessionMode.REPLAY,
    counterfactual=False,
    label="Archive replay",
    token="--badge-replay",
    detail="Recorded observations are being replayed from an archive; nothing is live.",
)
SIMULATION_BADGE = ModeBadge(
    mode=SessionMode.SIMULATION,
    counterfactual=False,
    label="Simulation",
    token="--badge-simulation",
    detail="Observations come from the simulator. Not a measured car.",
)
COUNTERFACTUAL_BADGE = ModeBadge(
    mode=SessionMode.SIMULATION,
    counterfactual=True,
    label="Counterfactual simulation",
    token="--badge-counterfactual",
    detail="A what-if run over changed inputs. Its outcome is not what happened.",
)


def badge_for(mode: SessionMode, *, counterfactual: bool = False) -> ModeBadge:
    """One badge per provenance; a counterfactual is never shown as a replay."""
    if counterfactual:
        if mode is not SessionMode.SIMULATION:
            raise ValueError("only a simulation session can be counterfactual")
        return COUNTERFACTUAL_BADGE
    return {
        SessionMode.LIVE_TEAM: LIVE_BADGE,
        SessionMode.REPLAY: REPLAY_BADGE,
        SessionMode.SIMULATION: SIMULATION_BADGE,
    }[mode]


@dataclass(frozen=True, slots=True)
class EstimatorSnapshot:
    """A checkpoint a seek can restart from."""

    session_time_s: float
    revision: int
    payload: Mapping[str, Any] = field(default_factory=dict)


class SnapshotStore:
    """Ordered estimator snapshots, searched by 'newest at or before'."""

    def __init__(self, snapshots: Iterable[EstimatorSnapshot] = ()) -> None:
        self._snapshots: list[EstimatorSnapshot] = sorted(snapshots, key=lambda s: s.session_time_s)

    def add(self, snapshot: EstimatorSnapshot) -> None:
        self._snapshots.append(snapshot)
        self._snapshots.sort(key=lambda s: s.session_time_s)

    def at_or_before(self, session_time_s: float) -> EstimatorSnapshot | None:
        times = [s.session_time_s for s in self._snapshots]
        index = bisect_right(times, session_time_s)
        return self._snapshots[index - 1] if index else None

    def __len__(self) -> int:
        return len(self._snapshots)

    def all(self) -> tuple[EstimatorSnapshot, ...]:
        return tuple(self._snapshots)


class ReplayClock:
    """Pause / step / seek / speed over the canonical :class:`SessionClock`."""

    def __init__(
        self,
        *,
        mode: SessionMode = SessionMode.REPLAY,
        counterfactual: bool = False,
        speed: float = 1.0,
        start_time_s: float = 0.0,
        clock_error_s: float = 0.0,
    ) -> None:
        self.clock = SessionClock(session_time_s=start_time_s, clock_error_s=clock_error_s)
        self.clock.set_speed(speed)
        self.mode = mode
        self.counterfactual = counterfactual
        self.wall_clock_elapsed_s = 0.0
        self._steps = 0

    @property
    def session_time_s(self) -> float:
        return self.clock.session_time_s

    @property
    def speed(self) -> float:
        return self.clock.speed

    @property
    def paused(self) -> bool:
        return self.clock.paused

    @property
    def badge(self) -> ModeBadge:
        return badge_for(self.mode, counterfactual=self.counterfactual)

    @property
    def step_count(self) -> int:
        return self._steps

    def pause(self) -> None:
        self.clock.pause()

    def resume(self) -> None:
        self.clock.resume()

    def set_speed(self, speed: float) -> None:
        """Change pacing only.

        Simulated time is untouched, so this cannot alter an integration result.
        """
        self.clock.set_speed(speed)

    def wall_clock_duration_for(self, simulated_dt_s: float) -> float:
        """Wall-clock seconds one simulated interval takes at the current speed."""
        if simulated_dt_s < 0.0:
            raise ValueError("a replay interval cannot be negative")
        return simulated_dt_s / self.clock.speed

    def step(self, simulated_dt_s: float) -> float:
        """Advance simulated time by exactly ``simulated_dt_s``.

        A paused clock does not advance, and wall time never advances it either.
        """
        if simulated_dt_s < 0.0:
            raise ValueError("replay steps forward; use seek to move backwards")
        before = self.clock.session_time_s
        self.clock.advance(simulated_dt_s)
        advanced = self.clock.session_time_s - before
        self.wall_clock_elapsed_s += self.wall_clock_duration_for(advanced)
        self._steps += 1
        return self.clock.session_time_s

    def seek(self, session_time_s: float) -> float:
        """Set simulated time directly. Pacing is unaffected."""
        if session_time_s < 0.0:
            raise ValueError("session time cannot be negative")
        self.clock.session_time_s = session_time_s
        return self.clock.session_time_s


@dataclass(frozen=True, slots=True)
class SeekResult:
    """What a seek restarted from and what it replayed."""

    target_s: float
    snapshot: EstimatorSnapshot | None
    resumed_from_s: float
    replayed: tuple[NormalisedRecord, ...]
    evaluated_future_samples: int = 0


class ReplaySession:
    """Deterministic replay over an ordered, immutable record list.

    Records are sorted once by ``(session_time_s, sequence)``. Every read is a
    bisect against that order, so the cursor structurally cannot reach a sample
    beyond the requested cutoff.
    """

    def __init__(
        self,
        records: Sequence[NormalisedRecord],
        *,
        clock: ReplayClock | None = None,
        snapshots: SnapshotStore | None = None,
        mode: SessionMode = SessionMode.REPLAY,
        counterfactual: bool = False,
        decisions_only: bool = False,
    ) -> None:
        selected = [r for r in records if r.usable_for_decisions] if decisions_only else list(records)
        self._records: tuple[NormalisedRecord, ...] = tuple(
            sorted(selected, key=lambda item: (item.session_time_s, item.event.sequence))
        )
        self._times = [record.session_time_s for record in self._records]
        self.clock = clock or ReplayClock(mode=mode, counterfactual=counterfactual)
        self.snapshots = snapshots or SnapshotStore()
        self._cursor = 0

    @property
    def records(self) -> tuple[NormalisedRecord, ...]:
        return self._records

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def session_time_s(self) -> float:
        return self.clock.session_time_s

    @property
    def badge(self) -> ModeBadge:
        return self.clock.badge

    @property
    def duration_s(self) -> float:
        return self._times[-1] if self._times else 0.0

    def records_at_cutoff(self, cutoff_s: float) -> tuple[NormalisedRecord, ...]:
        """Every record at or before ``cutoff_s``; never one after it."""
        return self._records[: bisect_right(self._times, cutoff_s)]

    def advance_to(self, cutoff_s: float) -> tuple[NormalisedRecord, ...]:
        """Deliver records in ``(current cursor, cutoff_s]`` and move the clock."""
        end = bisect_right(self._times, cutoff_s)
        if end < self._cursor:
            raise ValueError("advance_to moves forward; use seek to move backwards")
        delivered = self._records[self._cursor : end]
        self._cursor = end
        if cutoff_s > self.clock.session_time_s:
            self.clock.step(cutoff_s - self.clock.session_time_s)
        return delivered

    def step(self, simulated_dt_s: float) -> tuple[NormalisedRecord, ...]:
        return self.advance_to(self.clock.session_time_s + simulated_dt_s)

    def seek(self, target_s: float) -> SeekResult:
        """Load the preceding snapshot and replay forward to ``target_s``."""
        snapshot = self.snapshots.at_or_before(target_s)
        resume_from = snapshot.session_time_s if snapshot is not None else 0.0
        self._cursor = bisect_right(self._times, resume_from) if snapshot is not None else 0
        self.clock.seek(resume_from)
        replayed = self.advance_to(target_s)
        beyond = sum(1 for record in replayed if record.session_time_s > target_s)
        return SeekResult(
            target_s=target_s,
            snapshot=snapshot,
            resumed_from_s=resume_from,
            replayed=replayed,
            evaluated_future_samples=beyond,
        )

    def run(self, *, step_s: float) -> Iterator[tuple[float, tuple[NormalisedRecord, ...]]]:
        """Play the whole archive in fixed simulated steps.

        The yielded sequence is identical at any replay speed; only
        ``clock.wall_clock_elapsed_s`` differs.
        """
        if step_s <= 0.0:
            raise ValueError("replay step must be positive")
        while self._cursor < len(self._records):
            batch = self.step(step_s)
            yield self.clock.session_time_s, batch

    def reset(self) -> None:
        self._cursor = 0
        self.clock.seek(0.0)
        self.clock.wall_clock_elapsed_s = 0.0


def normalised_signature(records: Iterable[NormalisedRecord]) -> tuple[tuple[Any, ...], ...]:
    """Comparable identity of a normalised stream, used by round-trip tests."""
    return tuple(
        (
            record.event.sequence,
            record.event.event_id,
            record.event.car_id,
            record.event.channel,
            record.event.value,
            record.event.unit,
            record.event.provenance.value,
            record.event.quality.value,
            record.session_time_s,
            record.event.source_time_s,
            record.labels,
        )
        for record in records
    )


__all__ = [
    "COUNTERFACTUAL_BADGE",
    "LIVE_BADGE",
    "REPLAY_BADGE",
    "SIMULATION_BADGE",
    "EstimatorSnapshot",
    "ModeBadge",
    "ReplayClock",
    "ReplaySession",
    "SeekResult",
    "SnapshotStore",
    "badge_for",
    "normalised_signature",
]
