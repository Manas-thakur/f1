from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum

import numpy as np


class TyreCompound(StrEnum):
    HARD = "hard"
    MEDIUM = "medium"
    SOFT = "soft"


@dataclass(frozen=True, slots=True)
class TyreSpec:
    grip: float
    life_m: float
    sidewall: str


TYRE_SPECS = {
    TyreCompound.HARD: TyreSpec(0.97, 90000, "#f2f2ed"),
    TyreCompound.MEDIUM: TyreSpec(1.0, 60000, "#f0c438"),
    TyreCompound.SOFT: TyreSpec(1.035, 35000, "#e33b35"),
}


@dataclass(slots=True)
class TyreState:
    compound: TyreCompound
    condition: float
    change_threshold: float
    last_progress_m: float
    next_compound: TyreCompound
    phase: str = "track"
    requested: bool = False
    service_duration_s: float = 0
    service_remaining_s: float = 0
    box_progress_m: float = 0
    exit_after_progress_m: float = 0
    release_waiting: bool = False
    stops: int = 0
    used_compounds: list[TyreCompound] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.used_compounds:
            self.used_compounds.append(self.compound)

    @property
    def grip(self) -> float:
        return TYRE_SPECS[self.compound].grip * (0.82 + 0.18 * self.condition)

    def wear(self, distance_m: float, utilisation: float, scale: float) -> None:
        stress = 0.8 + 0.4 * min(1.5, max(0, utilisation))
        self.condition = max(
            0,
            self.condition - max(0, distance_m) * stress * scale / TYRE_SPECS[self.compound].life_m,
        )

    def payload(self, visual_lateral_m: float) -> dict[str, object]:
        payload = {
            **asdict(self),
            "compound": self.compound.value,
            "next_compound": self.next_compound.value,
            "grip": self.grip,
            "sidewall": TYRE_SPECS[self.compound].sidewall,
            "visual_lateral_m": visual_lateral_m,
        }
        payload["used_compounds"] = [compound.value for compound in self.used_compounds]
        return payload


def sample_compound(rng: np.random.Generator, excluding: TyreCompound | None = None) -> TyreCompound:
    choices = [compound for compound in TyreCompound if compound != excluding]
    return choices[int(rng.integers(0, len(choices)))]
