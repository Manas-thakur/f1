"""Density physics: monotonicity, an independent reference and honest unavailability."""

from __future__ import annotations

import math

import pytest

from afterlap_core.conditions.atmosphere import (
    ISA_SEA_LEVEL_PRESSURE_PA,
    ISA_SEA_LEVEL_TEMPERATURE_K,
    R_DRY_AIR_JPKGK,
    R_WATER_VAPOUR_JPKGK,
    DensityMethod,
    air_density,
    dry_air_density_kgpm3,
    isa_pressure_pa,
    moist_air_density_kgpm3,
    saturation_vapour_pressure_pa,
    vapour_pressure_pa,
)


def _reference_density_virtual_temperature(p_pa: float, t_k: float, rh: float) -> float:
    """Independent formulation: dry-air gas law at the virtual temperature.

    ``T_v = T / (1 - (p_v / p) (1 - epsilon))`` with ``epsilon = R_d / R_v``.
    Algebraically equivalent to the two-gas sum but coded differently, so a
    slip in either implementation shows up as a disagreement.
    """
    p_v = rh * saturation_vapour_pressure_pa(t_k)
    epsilon = R_DRY_AIR_JPKGK / R_WATER_VAPOUR_JPKGK
    t_v = t_k / (1.0 - (p_v / p_pa) * (1.0 - epsilon))
    return p_pa / (R_DRY_AIR_JPKGK * t_v)


def test_isa_sea_level_density_is_the_textbook_value():
    rho = dry_air_density_kgpm3(ISA_SEA_LEVEL_PRESSURE_PA, ISA_SEA_LEVEL_TEMPERATURE_K)
    assert rho == pytest.approx(1.2250, abs=5e-4)


def test_saturation_vapour_pressure_at_20c_matches_tables():
    # Standard tables give about 2.34 kPa at 20 C.
    assert saturation_vapour_pressure_pa(293.15) == pytest.approx(2339.0, rel=5e-3)


def test_moist_density_matches_an_independent_reference():
    for p, t, rh in ((101325.0, 293.15, 0.5), (78000.0, 300.0, 0.25), (96500.0, 288.0, 0.95)):
        assert moist_air_density_kgpm3(p, t, rh) == pytest.approx(
            _reference_density_virtual_temperature(p, t, rh), rel=1e-9
        )


def test_hand_computed_case():
    # 101325 Pa, 20 C, 50 % RH: e_s = 2333.4 Pa (Magnus), p_v = 1166.7 Pa,
    # rho = 100158.3/(287.058*293.15) + 1166.7/(461.495*293.15) = 1.1988 kg/m^3.
    assert moist_air_density_kgpm3(101325.0, 293.15, 0.5) == pytest.approx(1.1988, abs=2e-4)


def test_density_decreases_with_humidity_at_fixed_pressure_and_temperature():
    previous = math.inf
    for rh in (0.0, 0.25, 0.5, 0.75, 1.0):
        rho = moist_air_density_kgpm3(100000.0, 300.0, rh)
        assert rho < previous
        previous = rho


def test_density_decreases_with_altitude_through_the_isa_fallback():
    previous = math.inf
    for altitude in (0.0, 162.0, 400.0, 1000.0, 2285.0):
        result = air_density(
            temperature_k=298.15, pressure_pa=None, humidity_fraction=0.3, altitude_m=altitude
        )
        assert result.method is DensityMethod.ISA_ALTITUDE_FALLBACK
        assert result.value_kgpm3 is not None and result.value_kgpm3 < previous
        previous = result.value_kgpm3


def test_isa_pressure_at_mexico_city_altitude():
    # 1 - 0.0065*2285/288.15 = 0.948456; ^5.2559 = 0.7572; x 101325 = 76.7 kPa.
    assert isa_pressure_pa(2285.0) == pytest.approx(76720.0, rel=2e-3)
    assert isa_pressure_pa(0.0) == ISA_SEA_LEVEL_PRESSURE_PA


def test_measured_pressure_is_preferred_over_altitude():
    result = air_density(temperature_k=300.0, pressure_pa=78000.0, humidity_fraction=0.2, altitude_m=2285.0)
    assert result.method is DensityMethod.MEASURED_PRESSURE_MOIST
    assert result.pressure_pa == 78000.0


def test_missing_humidity_falls_back_to_dry_air_and_says_so():
    result = air_density(temperature_k=300.0, pressure_pa=100000.0, humidity_fraction=None, altitude_m=None)
    assert result.method is DensityMethod.MEASURED_PRESSURE_DRY
    assert result.value_kgpm3 == pytest.approx(dry_air_density_kgpm3(100000.0, 300.0))


def test_unknown_inputs_are_unavailable_not_zero():
    assert (
        air_density(
            temperature_k=None, pressure_pa=100000.0, humidity_fraction=0.5, altitude_m=0.0
        ).value_kgpm3
        is None
    )
    result = air_density(temperature_k=300.0, pressure_pa=None, humidity_fraction=None, altitude_m=None)
    assert result.value_kgpm3 is None
    assert result.method is DensityMethod.UNAVAILABLE


def test_unit_errors_are_refused():
    with pytest.raises(ValueError):
        dry_air_density_kgpm3(1013.25, 293.15)  # mbar passed as Pa
    with pytest.raises(ValueError):
        dry_air_density_kgpm3(101325.0, 20.0)  # Celsius passed as Kelvin
    with pytest.raises(ValueError):
        vapour_pressure_pa(293.15, 55.0)  # percent passed as fraction
