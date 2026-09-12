"""Air density from pressure, temperature and humidity, with an altitude fallback.

Equations
---------
Moist air is treated as an ideal mixture of dry air and water vapour (Dalton's
law), each obeying the ideal-gas law::

    rho = p_d / (R_d * T) + p_v / (R_v * T),     p_d = p - p_v,   p_v = RH * e_s(T)

with ``R_d = 287.058 J/(kg K)`` and ``R_v = 461.495 J/(kg K)`` (Picard, Davis,
Glaeser and Fujii, "Revised formula for the density of moist air (CIPM-2007)",
Metrologia 45 (2008) 149-155, give the fuller virial form; the two-gas form
above is its ideal-gas limit and is the standard moist-air formula used in
motorsport and meteorology). Adding water vapour at fixed ``p`` and ``T``
*lowers* density because a vapour molecule (18 g/mol) displaces a heavier dry
air molecule (28.96 g/mol).

Saturation vapour pressure uses the Magnus form with the Alduchov and Eskridge
(1996, J. Appl. Meteor. 35, 601-609) coefficients over water::

    e_s(t) = 610.94 Pa * exp(17.625 t / (t + 243.04)),   t in degrees Celsius

Where pressure is unknown but altitude is, the ISA troposphere barometric
formula (ISO 2533:1975 / ICAO Doc 7488) supplies a *fallback* pressure::

    p(h) = p0 * (1 - L h / T0) ** (g M / (R L))

with ``p0 = 101325 Pa``, ``T0 = 288.15 K``, ``L = 0.0065 K/m``,
``g = 9.80665 m/s^2``, ``M = 0.0289644 kg/mol``, ``R = 8.31446 J/(mol K)``.
That is a climatological standard, not a measurement, and the result says so.

Every function is pure and SI. Unknown inputs are ``None``, never zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from ..config import Parameter, VerificationStatus

R_DRY_AIR_JPKGK = 287.058
R_WATER_VAPOUR_JPKGK = 461.495

ISA_SEA_LEVEL_PRESSURE_PA = 101325.0
ISA_SEA_LEVEL_TEMPERATURE_K = 288.15
ISA_LAPSE_RATE_KPM = 0.0065
STANDARD_GRAVITY_MPS2 = 9.80665
MOLAR_MASS_DRY_AIR_KGPMOL = 0.0289644
UNIVERSAL_GAS_CONSTANT_JPMOLK = 8.31446
ISA_TROPOPAUSE_M = 11000.0

_MAGNUS_A_PA = 610.94
_MAGNUS_B = 17.625
_MAGNUS_C_C = 243.04

CELSIUS_OFFSET_K = 273.15

PRESSURE_SUPPORT_PA = (30000.0, 110000.0)
TEMPERATURE_SUPPORT_K = (200.0, 350.0)

R_DRY_AIR = Parameter(
    value=R_DRY_AIR_JPKGK,
    unit="J/(kg K)",
    source="Picard et al. 2008, Metrologia 45:149 (CIPM-2007), ideal-gas limit",
    verification=VerificationStatus.LITERATURE_DERIVED,
)
R_WATER_VAPOUR = Parameter(
    value=R_WATER_VAPOUR_JPKGK,
    unit="J/(kg K)",
    source="Picard et al. 2008, Metrologia 45:149 (CIPM-2007), ideal-gas limit",
    verification=VerificationStatus.LITERATURE_DERIVED,
)


class DensityMethod(StrEnum):
    """Which inputs produced a density value."""

    MEASURED_PRESSURE_MOIST = "measured_pressure_moist_air"
    MEASURED_PRESSURE_DRY = "measured_pressure_dry_air"
    ISA_ALTITUDE_FALLBACK = "isa_altitude_fallback"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DensityResult:
    """A density value together with how it was obtained."""

    value_kgpm3: float | None
    method: DensityMethod
    pressure_pa: float | None
    vapour_pressure_pa: float | None
    note: str

    @property
    def available(self) -> bool:
        return self.value_kgpm3 is not None


def _check_temperature(temperature_k: float) -> None:
    lo, hi = TEMPERATURE_SUPPORT_K
    if not (lo <= temperature_k <= hi):
        raise ValueError(f"temperature {temperature_k} K is outside physical support [{lo}, {hi}] K")


def _check_pressure(pressure_pa: float) -> None:
    lo, hi = PRESSURE_SUPPORT_PA
    if not (lo <= pressure_pa <= hi):
        raise ValueError(f"pressure {pressure_pa} Pa is outside physical support [{lo}, {hi}] Pa")


def saturation_vapour_pressure_pa(temperature_k: float) -> float:
    """Magnus formula over water, Alduchov and Eskridge (1996) coefficients."""
    _check_temperature(temperature_k)
    t_c = temperature_k - CELSIUS_OFFSET_K
    return _MAGNUS_A_PA * math.exp(_MAGNUS_B * t_c / (t_c + _MAGNUS_C_C))


def vapour_pressure_pa(temperature_k: float, humidity_fraction: float) -> float:
    if not (0.0 <= humidity_fraction <= 1.0):
        raise ValueError(f"relative humidity {humidity_fraction} must be a fraction in [0, 1]")
    return humidity_fraction * saturation_vapour_pressure_pa(temperature_k)


def dry_air_density_kgpm3(pressure_pa: float, temperature_k: float) -> float:
    """Ideal-gas dry air: rho = p / (R_d T)."""
    _check_pressure(pressure_pa)
    _check_temperature(temperature_k)
    return pressure_pa / (R_DRY_AIR_JPKGK * temperature_k)


def moist_air_density_kgpm3(pressure_pa: float, temperature_k: float, humidity_fraction: float) -> float:
    """Two-gas ideal mixture; see the module docstring for the equation and sources."""
    _check_pressure(pressure_pa)
    _check_temperature(temperature_k)
    p_v = vapour_pressure_pa(temperature_k, humidity_fraction)
    p_d = pressure_pa - p_v
    if p_d <= 0.0:
        raise ValueError("vapour pressure exceeds total pressure; inputs are inconsistent")
    return p_d / (R_DRY_AIR_JPKGK * temperature_k) + p_v / (R_WATER_VAPOUR_JPKGK * temperature_k)


def isa_pressure_pa(altitude_m: float) -> float:
    """ISA troposphere pressure at geopotential altitude (ISO 2533:1975)."""
    if not (-500.0 <= altitude_m <= ISA_TROPOPAUSE_M):
        raise ValueError(f"altitude {altitude_m} m is outside the ISA troposphere formula's range")
    exponent = (STANDARD_GRAVITY_MPS2 * MOLAR_MASS_DRY_AIR_KGPMOL) / (
        UNIVERSAL_GAS_CONSTANT_JPMOLK * ISA_LAPSE_RATE_KPM
    )
    base = 1.0 - ISA_LAPSE_RATE_KPM * altitude_m / ISA_SEA_LEVEL_TEMPERATURE_K
    return float(ISA_SEA_LEVEL_PRESSURE_PA * base**exponent)


def isa_temperature_k(altitude_m: float) -> float:
    """ISA troposphere temperature: T0 - L h."""
    return ISA_SEA_LEVEL_TEMPERATURE_K - ISA_LAPSE_RATE_KPM * altitude_m


def air_density(
    *,
    temperature_k: float | None,
    pressure_pa: float | None,
    humidity_fraction: float | None,
    altitude_m: float | None,
) -> DensityResult:
    """Best honest density from whatever is known.

    Preference order: measured pressure with humidity, measured pressure dry,
    ISA pressure from altitude (with humidity if known), otherwise unavailable.
    A missing temperature makes density unavailable; it is never assumed.
    """
    if temperature_k is None:
        return DensityResult(None, DensityMethod.UNAVAILABLE, None, None, "air temperature unknown")
    if pressure_pa is not None:
        if humidity_fraction is not None:
            p_v = vapour_pressure_pa(temperature_k, humidity_fraction)
            return DensityResult(
                moist_air_density_kgpm3(pressure_pa, temperature_k, humidity_fraction),
                DensityMethod.MEASURED_PRESSURE_MOIST,
                pressure_pa,
                p_v,
                "two-gas ideal mixture from measured pressure, temperature and humidity",
            )
        return DensityResult(
            dry_air_density_kgpm3(pressure_pa, temperature_k),
            DensityMethod.MEASURED_PRESSURE_DRY,
            pressure_pa,
            None,
            "dry-air ideal gas from measured pressure and temperature; humidity unknown",
        )
    if altitude_m is not None:
        p_isa = isa_pressure_pa(altitude_m)
        humidity = 0.0 if humidity_fraction is None else humidity_fraction
        p_v = vapour_pressure_pa(temperature_k, humidity)
        return DensityResult(
            moist_air_density_kgpm3(p_isa, temperature_k, humidity),
            DensityMethod.ISA_ALTITUDE_FALLBACK,
            p_isa,
            p_v,
            "pressure unknown: ISA barometric fallback from altitude (climatological, not measured)",
        )
    return DensityResult(None, DensityMethod.UNAVAILABLE, None, None, "neither pressure nor altitude known")


__all__ = [
    "CELSIUS_OFFSET_K",
    "ISA_LAPSE_RATE_KPM",
    "ISA_SEA_LEVEL_PRESSURE_PA",
    "ISA_SEA_LEVEL_TEMPERATURE_K",
    "PRESSURE_SUPPORT_PA",
    "R_DRY_AIR",
    "R_DRY_AIR_JPKGK",
    "R_WATER_VAPOUR",
    "R_WATER_VAPOUR_JPKGK",
    "TEMPERATURE_SUPPORT_K",
    "DensityMethod",
    "DensityResult",
    "air_density",
    "dry_air_density_kgpm3",
    "isa_pressure_pa",
    "isa_temperature_k",
    "moist_air_density_kgpm3",
    "saturation_vapour_pressure_pa",
    "vapour_pressure_pa",
]
