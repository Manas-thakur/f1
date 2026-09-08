"""Weather, altitude, surface, tyre and race-control conditions (A16-4).

Physics coefficients live here with unit and provenance. Nothing in this
package imports learning, reward or planning code: a physical parameter is
never reinterpreted by a policy (``FACTOR_AND_INFLUENCE.md``).
"""

from __future__ import annotations

from .atmosphere import DensityMethod, DensityResult, air_density, isa_pressure_pa, moist_air_density_kgpm3
from .field import TapeEnvironment
from .grip import surface_grip_multiplier
from .loader import ConditionsConfig, ConditionsUnavailable, environment_for, load_conditions
from .race_control import FlagPhase, RaceControlInterval, RaceControlTape
from .tape import ConditionsProvenance, ConditionsSample, ConditionsTape, GustSpec
from .tyres import Compound, TyreState, tyre_grip_factor
from .wind import headwind_mps

__all__ = [
    "Compound",
    "ConditionsConfig",
    "ConditionsProvenance",
    "ConditionsSample",
    "ConditionsTape",
    "ConditionsUnavailable",
    "DensityMethod",
    "DensityResult",
    "FlagPhase",
    "GustSpec",
    "RaceControlInterval",
    "RaceControlTape",
    "TapeEnvironment",
    "TyreState",
    "air_density",
    "environment_for",
    "headwind_mps",
    "isa_pressure_pa",
    "load_conditions",
    "moist_air_density_kgpm3",
    "surface_grip_multiplier",
    "tyre_grip_factor",
]
