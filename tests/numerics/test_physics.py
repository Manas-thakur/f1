from __future__ import annotations

import math

import pytest

from afterlap_core.simulation import physics


class TestResistanceForces:
    def test_drag_force_matches_hand_calculation(self) -> None:
        rho, cda, speed = 1.225, 1.20, 50.0
        expected = 0.5 * 1.225 * 1.20 * 2500.0
        assert expected == pytest.approx(1837.5, abs=1e-9)
        assert physics.drag_force(rho, cda, speed) == pytest.approx(expected, rel=1e-12)

    def test_drag_scales_with_the_square_of_speed(self) -> None:
        single = physics.drag_force(1.2, 1.0, 30.0)
        double = physics.drag_force(1.2, 1.0, 60.0)
        assert double == pytest.approx(4.0 * single, rel=1e-12)

    def test_rolling_force_uses_the_slope_normal_load(self) -> None:
        mass, g, crr, grade = 800.0, 9.80665, 0.0120, 0.050
        expected = 0.0120 * 800.0 * 9.80665 * math.cos(0.050)
        assert expected == pytest.approx(94.0264, abs=1e-3)
        assert physics.rolling_force(mass, g, crr, grade) == pytest.approx(expected, rel=1e-12)

    def test_grade_force_is_signed(self) -> None:
        mass, g = 800.0, 9.80665
        expected_up = 800.0 * 9.80665 * math.sin(0.050)
        assert expected_up == pytest.approx(392.0, abs=0.5)
        assert physics.grade_force(mass, g, 0.050) == pytest.approx(expected_up, rel=1e-12)
        assert physics.grade_force(mass, g, -0.050) == pytest.approx(-expected_up, rel=1e-12)

    def test_downforce_and_traction_envelope(self) -> None:
        rho, cla, speed = 1.20, 4.00, 75.0
        expected_down = 0.5 * 1.20 * 4.00 * 75.0 * 75.0
        assert expected_down == pytest.approx(13500.0, abs=1e-9)
        assert physics.downforce(rho, cla, speed) == pytest.approx(expected_down, rel=1e-12)

        mass, g, mu = 798.0, 9.80665, 1.50
        expected_envelope = 1.50 * (798.0 * 9.80665 + expected_down)
        assert physics.traction_limit(mass, g, mu, expected_down) == pytest.approx(
            expected_envelope, rel=1e-12
        )


class TestTractionLimiting:
    def test_traction_limit_binds_before_the_velocity_integration(self) -> None:

        mass = 800.0
        limit = 12000.0
        drag, roll, grade = 1837.5, 94.0, 0.0
        acceleration, applied = physics.longitudinal_acceleration(mass, 40000.0, drag, roll, grade, limit)
        assert applied == pytest.approx(limit, rel=1e-12)
        expected = (12000.0 - 1837.5 - 94.0 - 0.0) / 800.0
        assert expected == pytest.approx(12.585625, abs=1e-9)
        assert acceleration == pytest.approx(expected, rel=1e-12)

    def test_a_feasible_force_is_passed_through_unchanged(self) -> None:
        acceleration, applied = physics.longitudinal_acceleration(800.0, 5000.0, 1000.0, 100.0, 50.0, 12000.0)
        assert applied == pytest.approx(5000.0, rel=1e-12)
        assert acceleration == pytest.approx((5000.0 - 1000.0 - 100.0 - 50.0) / 800.0, rel=1e-12)

    def test_braking_is_limited_by_the_same_envelope(self) -> None:
        _, applied = physics.longitudinal_acceleration(800.0, -40000.0, 0.0, 0.0, 0.0, 12000.0)
        assert applied == pytest.approx(-12000.0, rel=1e-12)

    def test_friction_ellipse_splits_the_envelope(self) -> None:
        envelope, lateral = 20000.0, 12000.0
        expected = math.sqrt(20000.0**2 - 12000.0**2)
        assert expected == pytest.approx(16000.0, abs=1e-9)
        assert physics.longitudinal_envelope(envelope, lateral) == pytest.approx(expected, rel=1e-12)

    def test_a_saturated_corner_leaves_no_longitudinal_budget(self) -> None:
        assert physics.longitudinal_envelope(10000.0, 12000.0) == 0.0


class TestLowSpeedTorqueBranch:
    def test_no_singularity_as_speed_approaches_zero(self) -> None:
        power, max_force = 400.0e3, 18000.0
        for speed in (0.0, 1e-12, 1e-9, 1e-6, 1e-3, 0.1, 1.0):
            force = physics.tractive_force(power, speed, max_force)
            assert math.isfinite(force)
            assert force <= max_force + 1e-9

    def test_the_branch_is_continuous_at_the_breakpoint(self) -> None:
        power, max_force = 400.0e3, 18000.0
        breakpoint_speed = 400.0e3 / 18000.0
        assert physics.breakpoint_speed(power, max_force) == pytest.approx(breakpoint_speed, rel=1e-12)
        just_below = physics.tractive_force(power, breakpoint_speed - 1e-6, max_force)
        just_above = physics.tractive_force(power, breakpoint_speed + 1e-6, max_force)
        assert just_below == pytest.approx(max_force, rel=1e-9)
        assert just_above == pytest.approx(just_below, rel=1e-6)

    def test_above_the_breakpoint_force_follows_power_over_speed(self) -> None:
        power, max_force, speed = 400.0e3, 18000.0, 50.0
        assert physics.tractive_force(power, speed, max_force) == pytest.approx(8000.0, rel=1e-12)


class TestElectricalConversion:
    def test_deployment_costs_more_at_the_battery_than_it_delivers(self) -> None:
        expected = 200.0e3 / 0.95
        assert expected == pytest.approx(210526.3157894737, rel=1e-12)
        assert physics.battery_out_power(200.0e3, 0.95) == pytest.approx(expected, rel=1e-12)

    def test_harvest_delivers_less_to_the_battery_than_the_bus_carries(self) -> None:
        expected = 0.94 * 150.0e3
        assert expected == pytest.approx(141000.0, rel=1e-12)
        assert physics.battery_in_power(150.0e3, 0.94) == pytest.approx(expected, rel=1e-12)

    def test_efficiencies_outside_the_unit_interval_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            physics.battery_out_power(1.0, 0.0)
        with pytest.raises(ValueError):
            physics.battery_in_power(1.0, 1.5)


class TestThermalStep:
    def test_matches_the_analytic_solution_of_the_linear_ode(self) -> None:

        temperature, c_th, loss, h, ambient, dt = 320.0, 80000.0, 18000.0, 900.0, 303.15, 0.50
        steady_state = 303.15 + 18000.0 / 900.0
        assert steady_state == pytest.approx(323.15, abs=1e-9)
        decay = math.exp(-900.0 * 0.50 / 80000.0)
        expected = steady_state + (320.0 - steady_state) * decay
        assert physics.thermal_step(temperature, c_th, loss, h, ambient, dt) == pytest.approx(
            expected, rel=1e-12
        )

    def test_repeated_steps_agree_with_one_long_step(self) -> None:

        args = (80000.0, 18000.0, 900.0, 303.15)
        one_shot = physics.thermal_step(320.0, *args, 1.0)
        stepwise = 320.0
        for _ in range(100):
            stepwise = physics.thermal_step(stepwise, *args, 0.01)
        assert stepwise == pytest.approx(one_shot, rel=1e-12)

    def test_it_relaxes_towards_ambient_without_a_loss_source(self) -> None:
        cooled = physics.thermal_step(350.0, 80000.0, 0.0, 900.0, 303.15, 10.0)
        expected = 303.15 + (350.0 - 303.15) * math.exp(-900.0 * 10.0 / 80000.0)
        assert cooled == pytest.approx(expected, rel=1e-12)
        assert 303.15 < cooled < 350.0

    def test_zero_heat_transfer_degenerates_to_accumulation(self) -> None:
        assert physics.thermal_step(320.0, 80000.0, 8000.0, 0.0, 303.15, 2.0) == pytest.approx(
            320.0 + 8000.0 * 2.0 / 80000.0, rel=1e-12
        )

    def test_invalid_parameters_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            physics.thermal_step(320.0, 0.0, 1.0, 1.0, 300.0, 1.0)
        with pytest.raises(ValueError):
            physics.thermal_step(320.0, 1.0, 1.0, -1.0, 300.0, 1.0)


class TestCorneringEnvelope:
    def test_corner_speed_matches_the_hand_solved_balance(self) -> None:

        curvature, mu, g = 0.01250, 1.50, 9.80665
        downforce_factor = 0.5 * 1.20 * 4.00 / 798.0
        denominator = 0.01250 - 1.50 * downforce_factor
        expected = math.sqrt(1.50 * 9.80665 / denominator)
        assert expected == pytest.approx(42.9, abs=0.2)
        assert physics.max_lateral_speed(curvature, mu, g, downforce_factor) == pytest.approx(
            expected, rel=1e-12
        )

    def test_a_corner_downforce_alone_can_hold_is_not_speed_limiting(self) -> None:
        downforce_factor = 0.5 * 1.20 * 4.00 / 798.0
        assert physics.max_lateral_speed(0.001, 1.50, 9.80665, downforce_factor) == math.inf

    def test_sign_of_curvature_does_not_change_the_limit(self) -> None:
        factor = 0.003
        assert physics.max_lateral_speed(0.0125, 1.5, 9.80665, factor) == physics.max_lateral_speed(
            -0.0125, 1.5, 9.80665, factor
        )


class TestDerate:
    def test_ramp_endpoints_and_midpoint(self) -> None:
        assert physics.derate_factor(320.0, 328.15, 343.15) == 1.0
        assert physics.derate_factor(343.15, 328.15, 343.15) == 0.0
        assert physics.derate_factor(400.0, 328.15, 343.15) == 0.0
        midpoint = physics.derate_factor(335.65, 328.15, 343.15)
        assert midpoint == pytest.approx(0.5, rel=1e-12)

    def test_an_inverted_ramp_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            physics.derate_factor(330.0, 343.15, 328.15)
