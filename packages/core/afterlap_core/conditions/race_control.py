"""Race-control phases as a time-ranged tape.

Yellow, double yellow, VSC, SC and red-flag periods are recorded as closed
intervals of session time. The tape answers "which phase applies at ``t``",
choosing the most restrictive phase when intervals overlap (a sector yellow
inside a safety-car period is still a safety-car period). It carries no rule
semantics: what a phase permits (deployment, Overtake eligibility, pace) is
the rules checker's decision, not this module's.

Intervals here are either synthetic scenario inputs or transcriptions of
published race-control messages; the provenance says which. Nothing is
inferred from telemetry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from ..paths import sha256_json


class FlagPhase(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    DOUBLE_YELLOW = "double_yellow"
    VSC = "virtual_safety_car"
    SC = "safety_car"
    RED = "red"


PHASE_SEVERITY: dict[FlagPhase, int] = {
    FlagPhase.GREEN: 0,
    FlagPhase.YELLOW: 1,
    FlagPhase.DOUBLE_YELLOW: 2,
    FlagPhase.VSC: 3,
    FlagPhase.SC: 4,
    FlagPhase.RED: 5,
}


@dataclass(frozen=True, slots=True)
class RaceControlInterval:
    """One phase active on ``[start_s, end_s)``; ``sector`` is None when track-wide."""

    start_s: float
    end_s: float
    phase: FlagPhase
    sector: int | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.end_s <= self.start_s:
            raise ValueError(f"interval end {self.end_s} must exceed start {self.start_s}")
        if self.phase is FlagPhase.GREEN:
            raise ValueError("green is the absence of an interval; do not record it")
        if self.sector is not None and self.sector < 1:
            raise ValueError("sector numbers start at 1")

    def contains(self, session_time_s: float) -> bool:
        return self.start_s <= session_time_s < self.end_s


class RaceControlTape:
    """Ordered intervals with provenance and a content hash."""

    def __init__(
        self,
        tape_id: str,
        intervals: tuple[RaceControlInterval, ...] | list[RaceControlInterval],
        *,
        source: str,
        synthetic: bool,
    ) -> None:
        self.tape_id = tape_id
        self.intervals = tuple(sorted(intervals, key=lambda i: (i.start_s, -PHASE_SEVERITY[i.phase])))
        self.source = source
        self.synthetic = synthetic

    def active_at(self, session_time_s: float) -> tuple[RaceControlInterval, ...]:
        return tuple(i for i in self.intervals if i.contains(session_time_s))

    def phase_at(self, session_time_s: float, *, sector: int | None = None) -> FlagPhase:
        """Most restrictive phase at ``t``; sector-local intervals apply only to that sector.

        With ``sector=None`` every interval counts, which is the conservative
        (track-wide) reading.
        """
        phase = FlagPhase.GREEN
        for interval in self.active_at(session_time_s):
            if sector is not None and interval.sector is not None and interval.sector != sector:
                continue
            if PHASE_SEVERITY[interval.phase] > PHASE_SEVERITY[phase]:
                phase = interval.phase
        return phase

    def seconds_in(self, phase: FlagPhase) -> float:
        """Total time any interval of ``phase`` is active (overlaps of the same phase merged)."""
        spans = sorted((i.start_s, i.end_s) for i in self.intervals if i.phase is phase)
        total = 0.0
        current: tuple[float, float] | None = None
        for start, end in spans:
            if current is None or start > current[1]:
                if current is not None:
                    total += current[1] - current[0]
                current = (start, end)
            else:
                current = (current[0], max(current[1], end))
        if current is not None:
            total += current[1] - current[0]
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "tape_id": self.tape_id,
            "source": self.source,
            "synthetic": self.synthetic,
            "intervals": [asdict(i) for i in self.intervals],
        }

    @property
    def content_hash(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RaceControlTape:
        return cls(
            payload["tape_id"],
            [
                RaceControlInterval(
                    start_s=float(i["start_s"]),
                    end_s=float(i["end_s"]),
                    phase=FlagPhase(i["phase"]),
                    sector=i.get("sector"),
                    note=i.get("note"),
                )
                for i in payload["intervals"]
            ],
            source=payload["source"],
            synthetic=bool(payload["synthetic"]),
        )


__all__ = ["PHASE_SEVERITY", "FlagPhase", "RaceControlInterval", "RaceControlTape"]
