"""Inputs the rules module consumes.

These are deliberately *not* wire contracts. They are the small, explicit
argument records that :mod:`afterlap_core.rules.context` and
:mod:`afterlap_core.rules.checker` need, so that no caller has to pass a bag of
positional floats and no unit can be silently swapped.

Every energy is joules, every power watts, every speed m/s, every temperature
kelvin, every distance metres and every time seconds (``01_contracts/UNITS_TIME.md``).
A missing value is ``None`` with a reason, never zero.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise

from afterlap_contracts import DeploymentProfile, EligibilityState, FlagState

from ..timebase import EventPriority

__all__ = [
    "CarState",
    "CheckerState",
    "RaceEvent",
    "RaceEventKind",
    "SpeedProfile",
    "SpeedSample",
    "sorted_race_events",
]


class RaceEventKind(StrEnum):
    """Race-control inputs the rules module folds into a :class:`RuleContext`."""

    FLAG = "flag"
    """A new flag state is in force from ``at_session_time_s``."""

    INVALIDATION = "invalidation"
    """A race-control instruction that invalidates an outstanding permission."""

    LAP_RESET = "lap_reset"
    """A lap counter rolled over; only lap-scoped state resets."""

    UNKNOWN_CONDITION = "unknown_condition"
    """A referenced document or condition that could not be resolved."""


_EVENT_PRIORITY: dict[RaceEventKind, EventPriority] = {
    # UNITS_TIME.md, "Events crossing a step": safety/rule invalidations first,
    # physical line events second.
    RaceEventKind.INVALIDATION: EventPriority.SAFETY_OR_RULE_INVALIDATION,
    RaceEventKind.UNKNOWN_CONDITION: EventPriority.SAFETY_OR_RULE_INVALIDATION,
    RaceEventKind.FLAG: EventPriority.SAFETY_OR_RULE_INVALIDATION,
    RaceEventKind.LAP_RESET: EventPriority.PHYSICAL_LINE_EVENT,
}


@dataclass(frozen=True, slots=True)
class RaceEvent:
    """One timestamped race-control fact.

    The rules module never invents these. They arrive from the session owner
    (simulation, replay or race-control ingestion) and are folded in
    deterministic contract order.
    """

    at_session_time_s: float
    kind: RaceEventKind
    flags: tuple[FlagState, ...] = ()
    reason: str | None = None
    condition: str | None = None
    lap_index: int | None = None

    @property
    def priority(self) -> EventPriority:
        return _EVENT_PRIORITY[self.kind]

    @property
    def order_key(self) -> tuple[float, int]:
        return (self.at_session_time_s, int(self.priority))


@dataclass(frozen=True, slots=True)
class CarState:
    """Own-car state as far as the rules module needs it.

    ``eligibility`` is supplied by the caller's
    :class:`~afterlap_core.rules.eligibility.EligibilityMachine`; the rules
    module may downgrade it (a safety state invalidates a permission) but it
    never upgrades it.
    """

    speed_mps: float
    battery_energy_j: float
    current_power_w: float = 0.0
    temperature_k: float | None = None
    recharge_used_this_lap_j: float = 0.0
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    eligibility_observed_at_s: float | None = None
    sector_id: str | None = None
    lap_index: int = 0

    def __post_init__(self) -> None:
        if self.speed_mps < 0.0:
            raise ValueError("speed_mps must be non-negative")
        if self.battery_energy_j < 0.0:
            raise ValueError("battery_energy_j must be non-negative")


@dataclass(frozen=True, slots=True)
class SpeedSample:
    """One breakpoint of the speed profile the checker reintegrates along."""

    progress_m: float
    speed_mps: float

    def __post_init__(self) -> None:
        if self.speed_mps <= 0.0:
            raise ValueError("speed samples must be strictly positive; a stopped car has no travel time")


@dataclass(frozen=True, slots=True)
class SpeedProfile:
    """Speed as a function of unwrapped progress.

    ``step=False`` interpolates linearly between samples; ``step=True`` holds
    each sample's speed until the next sample. Outside the sampled range the
    first/last sample is held flat, which is stated rather than extrapolated.
    """

    samples: tuple[SpeedSample, ...]
    step: bool = False
    _progress: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError("a speed profile needs at least one sample")
        progress = tuple(s.progress_m for s in self.samples)
        if list(progress) != sorted(progress) or len(set(progress)) != len(progress):
            raise ValueError("speed samples must have strictly increasing progress")
        object.__setattr__(self, "_progress", progress)

    def speed_at(self, progress_m: float) -> float:
        """Speed at one point, using the profile's declared interpolation."""
        samples = self.samples
        if progress_m <= samples[0].progress_m:
            return samples[0].speed_mps
        if progress_m >= samples[-1].progress_m:
            return samples[-1].speed_mps
        index = bisect_right(self._progress, progress_m) - 1
        low = samples[index]
        high = samples[index + 1]
        if self.step:
            return low.speed_mps
        span = high.progress_m - low.progress_m
        frac = (progress_m - low.progress_m) / span
        return low.speed_mps + frac * (high.speed_mps - low.speed_mps)

    def breakpoints_within(self, start_m: float, end_m: float) -> tuple[float, ...]:
        """Sample progresses strictly inside ``(start_m, end_m)``."""
        return tuple(p for p in self._progress if start_m < p < end_m)

    def sub_intervals(self, start_m: float, end_m: float) -> Iterator[tuple[float, float, float, float]]:
        """Yield ``(a, b, speed_at_a, speed_at_b)`` pieces with no interior breakpoint."""
        if end_m <= start_m:
            return
        edges = [start_m, *self.breakpoints_within(start_m, end_m), end_m]
        for a, b in pairwise(edges):
            if b <= a:
                continue
            if self.step:
                # Held value: evaluate strictly inside so the interval is constant.
                held = self.speed_at(0.5 * (a + b))
                yield a, b, held, held
            else:
                yield a, b, self.speed_at(a), self.speed_at(b)

    def travel_time_s(self, start_m: float, end_m: float, *, substeps: int = 32) -> float:
        """Time to cover ``[start_m, end_m]``. Exact for a piecewise-constant profile."""
        if end_m <= start_m:
            return 0.0
        total = 0.0
        for a, b, va, vb in self.sub_intervals(start_m, end_m):
            width = (b - a) / substeps
            for index in range(substeps):
                sa = a + index * width
                sb = sa + width
                # Linear speed over the piece; midpoint speed integrates ds/v exactly
                # for the constant case and to second order otherwise.
                fa = (sa - a) / (b - a)
                fb = (sb - a) / (b - a)
                speed_a = va + fa * (vb - va)
                speed_b = va + fb * (vb - va)
                total += width / (0.5 * (speed_a + speed_b))
        return total


@dataclass(frozen=True, slots=True)
class CheckerState:
    """Everything the independent checker needs to reintegrate a plan itself.

    The checker deliberately does not receive the planner's own integration
    result: it re-derives the power and energy ledgers from this state plus the
    immutable rule pack (``04_rules/TECHNICAL_SPEC.md``, "Checker").
    """

    session_time_s: float
    progress_m: float
    battery_energy_j: float
    speed_profile: SpeedProfile
    track_length_m: float
    current_power_w: float = 0.0
    recharge_used_this_lap_j: float = 0.0
    driver_reaction_time_s: float = 0.6
    charge_bus_efficiency: float = 1.0
    """Battery energy gain divided by charge-bus energy. 1.0 means "not modelled here"."""
    discharge_efficiency: float = 1.0
    """Deployed bus energy divided by battery energy drawn. 1.0 means "not modelled here"."""
    profile_order: tuple[DeploymentProfile, ...] = ()

    def __post_init__(self) -> None:
        if self.track_length_m <= 0.0:
            raise ValueError("track_length_m must be positive")
        if not (0.0 < self.charge_bus_efficiency <= 1.0):
            raise ValueError("charge_bus_efficiency must lie in (0, 1]")
        if not (0.0 < self.discharge_efficiency <= 1.0):
            raise ValueError("discharge_efficiency must lie in (0, 1]")
        if self.driver_reaction_time_s < 0.0:
            raise ValueError("driver_reaction_time_s must be non-negative")

    def lap_index_at(self, progress_m: float) -> int:
        return int(progress_m // self.track_length_m)

    def lap_boundaries_within(self, start_m: float, end_m: float) -> tuple[float, ...]:
        """Unwrapped progresses of lap rollovers strictly inside ``(start_m, end_m)``."""
        first = self.lap_index_at(start_m) + 1
        last = self.lap_index_at(end_m)
        return tuple(
            lap * self.track_length_m
            for lap in range(first, last + 1)
            if start_m < lap * self.track_length_m < end_m
        )


def sorted_race_events(events: Sequence[RaceEvent]) -> tuple[RaceEvent, ...]:
    """Stable contract order: session time, then event priority, then arrival."""
    return tuple(sorted(events, key=lambda e: e.order_key))
