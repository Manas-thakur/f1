"""Grip and tyre reduced models: reference value, monotonicity, bounds, provenance."""

from __future__ import annotations

import pytest

from afterlap_core.conditions import grip, tyres
from afterlap_core.config import Parameter, VerificationStatus


def test_dry_reference_is_exactly_one():
    assert grip.surface_grip_multiplier() == 1.0
    assert (
        grip.surface_grip_multiplier(rain_intensity=0.0, track_temperature_k=305.0, rubber_fraction=0.0)
        == 1.0
    )


def test_rainfall_strictly_lowers_grip_and_is_monotone():
    previous = grip.surface_grip_multiplier(rain_intensity=0.0)
    for rain in (0.1, 0.4, 0.7, 1.0):
        value = grip.surface_grip_multiplier(rain_intensity=rain)
        assert value < previous
        previous = value
    assert grip.surface_grip_multiplier(rain_intensity=1.0) == pytest.approx(grip.WET_FLOOR.value)


def test_temperature_plateau_and_symmetric_loss_outside():
    assert grip.temperature_factor(None) == 1.0
    assert grip.temperature_factor(grip.T_PLATEAU_LOW.value) == 1.0
    assert grip.temperature_factor(grip.T_PLATEAU_HIGH.value) == 1.0
    cold = grip.temperature_factor(grip.T_PLATEAU_LOW.value - 10.0)
    colder = grip.temperature_factor(grip.T_PLATEAU_LOW.value - 20.0)
    hot = grip.temperature_factor(grip.T_PLATEAU_HIGH.value + 10.0)
    assert colder < cold < 1.0
    assert hot == pytest.approx(cold)


def test_bounds_hold_over_the_whole_input_space():
    for rain in (0.0, 0.5, 1.0):
        for temp in (None, 200.0, 250.0, 300.0, 350.0, 380.0):
            for rubber in (0.0, 0.5, 1.0):
                value = grip.surface_grip_multiplier(
                    rain_intensity=rain, track_temperature_k=temp, rubber_fraction=rubber
                )
                assert grip.GRIP_FLOOR.value <= value <= grip.GRIP_CEILING.value
    assert grip.surface_grip_multiplier(rubber_fraction=1.0) == pytest.approx(grip.GRIP_CEILING.value)


def test_every_grip_coefficient_declares_units_and_provenance():
    for coefficient in grip.COEFFICIENTS:
        assert isinstance(coefficient, Parameter)
        assert coefficient.verification in (
            VerificationStatus.SYNTHETIC_ASSUMPTION,
            VerificationStatus.LITERATURE_DERIVED,
        )
        assert coefficient.note, "each coefficient says where it comes from"
        assert not coefficient.is_measured


def test_out_of_range_inputs_are_refused():
    with pytest.raises(ValueError):
        grip.surface_grip_multiplier(rain_intensity=1.5)
    with pytest.raises(ValueError):
        grip.surface_grip_multiplier(rubber_fraction=-0.1)


def test_tyres_are_labelled_synthetic_and_uncalibrated():
    assert tyres.calibration_status() == "unavailable"
    for table in (tyres.DRY_PEAK_GRIP, tyres.WET_SURFACE_ADJUSTMENT, tyres.DEGRADATION_PER_LAP):
        for parameter in table.values():
            assert parameter.verification is VerificationStatus.SYNTHETIC_ASSUMPTION
            assert "Synthetic" in (parameter.note or "")


def test_new_soft_slick_on_dry_is_the_reference_and_age_degrades_monotonically():
    new = tyres.TyreState(tyres.Compound.SOFT, 0.0)
    assert tyres.tyre_grip_factor(new) == 1.0
    previous = 1.0
    for age in (5.0, 10.0, 20.0, 40.0, 200.0):
        value = tyres.tyre_grip_factor(tyres.TyreState(tyres.Compound.SOFT, age))
        assert value <= previous
        previous = value
    assert previous >= tyres.TYRE_FLOOR


def test_treaded_tyres_beat_slicks_only_when_wet():
    slick = tyres.TyreState(tyres.Compound.MEDIUM, 0.0)
    inter = tyres.TyreState(tyres.Compound.INTERMEDIATE, 0.0)
    assert tyres.tyre_grip_factor(slick) > tyres.tyre_grip_factor(inter)
    assert tyres.tyre_grip_factor(inter, rain_intensity=1.0) > tyres.tyre_grip_factor(
        slick, rain_intensity=1.0
    )


def test_negative_age_is_refused():
    with pytest.raises(ValueError):
        tyres.TyreState(tyres.Compound.HARD, -1.0)
