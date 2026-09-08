"""Tyre compound and age to grip and degradation factors.

**Every number in this module is a synthetic assumption.** No tyre telemetry,
manufacturer data or lap-time residual fitting stands behind it. The module
exists so that the simulator can carry a categorical compound plus a
continuous age (``RACE_CONDITION_MODEL.md``) through the same reduced
multiplicative structure as the surface model, and so that a later
calibration can replace these coefficients without changing call sites.
``calibration_status()`` reports ``"unavailable"`` and nothing here may be
described as calibrated.

The tyre factor is **per car** and therefore cannot flow through the
``EnvironmentField`` seam, which knows only lap position and time. Wiring it
into the engine's per-car ``mu`` is a coordinator decision (see
``handoffs/A16-4.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..config import Parameter, VerificationStatus

_SYNTHETIC = VerificationStatus.SYNTHETIC_ASSUMPTION
_SOURCE = "synthetic:afterlap-conditions-tyres-v1"


class Compound(StrEnum):
    SOFT = "soft"
    MEDIUM = "medium"
    HARD = "hard"
    INTERMEDIATE = "intermediate"
    WET = "wet"


def _param(value: float, unit: str, note: str, **bounds: float) -> Parameter:
    return Parameter(value=value, unit=unit, source=_SOURCE, verification=_SYNTHETIC, note=note, **bounds)


# Peak grip relative to the soft slick on a dry surface (synthetic ordering only).
DRY_PEAK_GRIP: dict[Compound, Parameter] = {
    Compound.SOFT: _param(1.00, "1", "Reference slick. Synthetic."),
    Compound.MEDIUM: _param(0.985, "1", "Slightly below soft. Synthetic ordering, not measured."),
    Compound.HARD: _param(0.97, "1", "Below medium. Synthetic ordering, not measured."),
    Compound.INTERMEDIATE: _param(0.90, "1", "Treaded; slower than slicks in the dry. Synthetic."),
    Compound.WET: _param(0.85, "1", "Full wet; slowest in the dry. Synthetic."),
}

# Additional wet-surface adjustment beyond the surface wetness factor
# (slicks aquaplane; treaded tyres recover part of the surface loss).
WET_SURFACE_ADJUSTMENT: dict[Compound, Parameter] = {
    Compound.SOFT: _param(0.80, "1", "Slick on a wet surface at full rain. Synthetic."),
    Compound.MEDIUM: _param(0.80, "1", "Slick on a wet surface at full rain. Synthetic."),
    Compound.HARD: _param(0.80, "1", "Slick on a wet surface at full rain. Synthetic."),
    Compound.INTERMEDIATE: _param(1.10, "1", "Treaded; recovers part of the wet-surface loss. Synthetic."),
    Compound.WET: _param(1.20, "1", "Full wet; recovers most of the wet-surface loss. Synthetic."),
}

# Linear grip loss per lap of age, and the floor the factor cannot cross.
DEGRADATION_PER_LAP: dict[Compound, Parameter] = {
    Compound.SOFT: _param(0.0040, "1/lap", "Fastest wearing. Synthetic."),
    Compound.MEDIUM: _param(0.0025, "1/lap", "Synthetic."),
    Compound.HARD: _param(0.0015, "1/lap", "Slowest wearing. Synthetic."),
    Compound.INTERMEDIATE: _param(0.0035, "1/lap", "Synthetic."),
    Compound.WET: _param(0.0030, "1/lap", "Synthetic."),
}
DEGRADATION_FLOOR = _param(0.70, "1", "Age factor never falls below this. Synthetic.", lower_bound=0.3)

TYRE_CEILING = 1.05
TYRE_FLOOR = 0.3


@dataclass(frozen=True, slots=True)
class TyreState:
    compound: Compound
    age_laps: float

    def __post_init__(self) -> None:
        if self.age_laps < 0.0:
            raise ValueError("tyre age cannot be negative")


def degradation_factor(state: TyreState) -> float:
    """1.0 new, decreasing linearly with age, floored. Monotone non-increasing."""
    loss = DEGRADATION_PER_LAP[state.compound].value * state.age_laps
    return max(DEGRADATION_FLOOR.value, 1.0 - loss)


def tyre_grip_factor(state: TyreState, *, rain_intensity: float = 0.0) -> float:
    """Compound peak grip x wet-surface adjustment (blended by rain) x age degradation.

    Multiplies the surface multiplier from :mod:`grip`; both are relative to
    the dry reference so a new soft slick on a dry surface returns 1.0.
    """
    if not (0.0 <= rain_intensity <= 1.0):
        raise ValueError("rain_intensity must lie in [0, 1]")
    peak = DRY_PEAK_GRIP[state.compound].value
    wet_adjust = 1.0 + (WET_SURFACE_ADJUSTMENT[state.compound].value - 1.0) * rain_intensity
    raw = peak * wet_adjust * degradation_factor(state)
    return min(TYRE_CEILING, max(TYRE_FLOOR, raw))


def calibration_status() -> str:
    """The honest answer: no tyre calibration exists in this project."""
    return "unavailable"


__all__ = [
    "DEGRADATION_FLOOR",
    "DEGRADATION_PER_LAP",
    "DRY_PEAK_GRIP",
    "TYRE_CEILING",
    "TYRE_FLOOR",
    "WET_SURFACE_ADJUSTMENT",
    "Compound",
    "TyreState",
    "calibration_status",
    "degradation_factor",
    "tyre_grip_factor",
]
