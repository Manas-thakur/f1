"""Power-curve evaluation.

Expected values are computed here from the declared breakpoints by hand, not by
calling the implementation's interpolation a second time. The v1 season curve is

    (0 m/s, 350 kW) (80 m/s, 350 kW) (95 m/s, 150 kW) (110 m/s, 0 kW)

so the two sloped legs have gradients

    (150000 - 350000) / (95 - 80) = -200000 / 15 W per m/s
    (0 - 150000)      / (110 - 95) = -150000 / 15 W per m/s
"""

from __future__ import annotations

import pytest

from afterlap_core.rules import CarState, resolve_pack_context

LEG_A_SLOPE_W_PER_MPS = -200_000.0 / 15.0
LEG_B_SLOPE_W_PER_MPS = -150_000.0 / 15.0


def season_curve(pack):
    curve = pack.manifest.curve("baseline-speed-curve")
    assert curve is not None
    return curve


def test_ceiling_at_exact_threshold(pack_v1):
    curve = season_curve(pack_v1)
    assert curve.ceiling_w(0.0) == 350_000.0
    assert curve.ceiling_w(80.0) == 350_000.0
    assert curve.ceiling_w(95.0) == 150_000.0
    assert curve.ceiling_w(110.0) == 0.0


def test_ceiling_epsilon_below_and_above_threshold(pack_v1):
    curve = season_curve(pack_v1)
    delta = 1.0e-3

    expected_below = 150_000.0 - delta * LEG_A_SLOPE_W_PER_MPS
    assert curve.ceiling_w(95.0 - delta) == pytest.approx(expected_below, abs=1e-6)
    assert expected_below > 150_000.0

    expected_above = 150_000.0 + delta * LEG_B_SLOPE_W_PER_MPS
    assert curve.ceiling_w(95.0 + delta) == pytest.approx(expected_above, abs=1e-6)
    assert expected_above < 150_000.0

    assert expected_below - 150_000.0 == pytest.approx(200_000.0 / 15.0 * delta, abs=1e-9)
    assert 150_000.0 - expected_above == pytest.approx(150_000.0 / 15.0 * delta, abs=1e-9)


def test_ceiling_interpolates_between_breakpoints(pack_v1):
    curve = season_curve(pack_v1)

    assert curve.ceiling_w(87.5) == pytest.approx(250_000.0, abs=1e-9)
    assert curve.ceiling_w(100.0) == pytest.approx(100_000.0, abs=1e-9)
    assert curve.ceiling_w(102.5) == pytest.approx(75_000.0, abs=1e-9)
    assert curve.ceiling_w(83.0) == pytest.approx(350_000.0 + 3.0 * LEG_A_SLOPE_W_PER_MPS, abs=1e-9)


def test_ceiling_extrapolates_flat_outside_range(pack_v1):
    curve = season_curve(pack_v1)
    assert curve.ceiling_w(0.0) == 350_000.0
    assert curve.ceiling_w(110.0) == 0.0
    assert curve.ceiling_w(130.0) == 0.0
    assert curve.ceiling_w(1_000.0) == 0.0


def test_ceiling_is_continuous_at_every_breakpoint(pack_v1):
    curve = season_curve(pack_v1)
    delta = 1.0e-6
    steepest = max(
        abs(high.max_power_w - low.max_power_w) / (high.speed_mps - low.speed_mps)
        for low, high in zip(curve.points, curve.points[1:], strict=False)
    )
    assert steepest == pytest.approx(200_000.0 / 15.0, abs=1e-9)

    for point in curve.points:
        value = curve.ceiling_w(point.speed_mps)
        assert value == point.max_power_w
        for probe in (point.speed_mps - delta, point.speed_mps + delta):
            if probe < 0.0:
                continue
            assert abs(curve.ceiling_w(probe) - value) <= steepest * delta + 1e-9


def test_absolute_ceiling_and_curve_intersect_at_declared_bus(pack_v1):
    manifest = pack_v1.manifest
    curve = season_curve(pack_v1)
    assert curve.measurement_bus == "ers_k_dc"
    assert manifest.recharge_measurement_bus == "cu_k_dc"
    assert manifest.recharge_measurement_bus != curve.measurement_bus

    for speed_mps, expected_w in ((50.0, 350_000.0), (100.0, 100_000.0), (110.0, 0.0)):
        car = CarState(
            speed_mps=speed_mps,
            battery_energy_j=2_000_000.0,
            temperature_k=300.0,
        )
        context = resolve_pack_context(pack_v1, 1_000.0, 5.0, car, session_id="curve-session")
        assert context.applicable_limits.deployment_ceiling_w == pytest.approx(expected_w, abs=1e-9)
        assert context.applicable_limits.thermal_derate_factor == 1.0
        assert min(manifest.absolute_power_ceiling_w, curve.ceiling_w(speed_mps)) == pytest.approx(
            expected_w, abs=1e-9
        )


def test_event_sector_curve_overrides_the_season_curve(pack_v1):
    car_in_sector = CarState(
        speed_mps=82.5, battery_energy_j=2_000_000.0, temperature_k=300.0, sector_id="sector-2"
    )
    context = resolve_pack_context(pack_v1, 1_000.0, 5.0, car_in_sector, session_id="curve-session")
    assert context.active_curve_id == "synthetic-event-sector-2-curve"
    assert context.applicable_limits.deployment_ceiling_w == pytest.approx(210_000.0, abs=1e-9)

    car_outside = CarState(
        speed_mps=82.5, battery_energy_j=2_000_000.0, temperature_k=300.0, sector_id="sector-1"
    )
    season_context = resolve_pack_context(pack_v1, 1_000.0, 5.0, car_outside, session_id="curve-session")
    assert season_context.active_curve_id == "baseline-speed-curve"
    assert season_context.applicable_limits.deployment_ceiling_w == pytest.approx(
        350_000.0 + 2.5 * LEG_A_SLOPE_W_PER_MPS, abs=1e-9
    )
