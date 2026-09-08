"""The independent checker.

The checker's declared reintegration model is:

* deployment power follows the ceiling shape, ``P_dep(s) = k_d * C_reg(v(s))``,
  with ``k_d`` chosen so the time integral of ``P_dep`` equals the segment's
  ``requested_budget_j``;
* battery-gain harvest follows speed, ``P_har(s) = k_h * v(s)``, with ``k_h``
  chosen so the time integral equals ``harvest_target_j``;
* the recharge ledger is the battery gain divided by the charge-bus efficiency.

Every expected number below is derived from that model with pen-and-paper
arithmetic written out in the test. The v1 season curve gives 350 kW at 50 m/s
(the flat leg up to 80 m/s) and 100 kW at 100 m/s (one third along the
95 -> 110 m/s leg: 150 kW - 50 kW).
"""

from __future__ import annotations

import pytest

from afterlap_contracts import (
    ActionCode,
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    ProfileSegment,
)
from afterlap_core.rules import CarState, build_trace, check_plan, resolve_pack_context

from .conftest import (
    checker_state,
    checks_by_id,
    constant_speed,
    make_plan,
    two_phase_speed,
)

CEILING_AT_50_W = 350_000.0
CEILING_AT_100_W = 100_000.0


def context_for(
    pack,
    *,
    speed_mps,
    battery_energy_j,
    temperature_k=300.0,
    progress_m=1_000.0,
    session_time_s=10.0,
    recharge_used_this_lap_j=0.0,
    eligibility=EligibilityState.ACTIVE,
):
    car = CarState(
        speed_mps=speed_mps,
        battery_energy_j=battery_energy_j,
        temperature_k=temperature_k,
        recharge_used_this_lap_j=recharge_used_this_lap_j,
        eligibility=eligibility,
        eligibility_observed_at_s=session_time_s - 1.0,
    )
    return resolve_pack_context(pack, progress_m, session_time_s, car, session_id="checker-session")


def test_interior_energy_minimum_is_rejected_though_endpoints_are_legal(pack_v1):
    """The key test: legal endpoints, illegal interior minimum.

    One PUSH segment from 1000 m to 3000 m. The car holds 50 m/s to 2000 m and
    100 m/s after it, so

        phase 1: 1000 m at 50 m/s  -> 20.0 s, ceiling 350 kW
        phase 2: 1000 m at 100 m/s -> 10.0 s, ceiling 100 kW

    ceiling-time integral = 350000 * 20 + 100000 * 10 = 8.0e6 J
    requested budget 800000 J  ->  k_d = 0.1
        deploy = 35 kW in phase 1, 10 kW in phase 2
    speed-time integral = 50 * 20 + 100 * 10 = 2000 m
    harvest target 600000 J    ->  k_h = 300
        harvest = 15 kW in phase 1, 30 kW in phase 2

    net power = -20 kW for 20 s, then +20 kW for 10 s. From 380000 J the
    trajectory therefore reaches -20000 J at 2000 m and recovers to 180000 J.
    Both endpoints sit inside the 0 .. 4 MJ window; the interior minimum does
    not.
    """
    start_energy_j = 380_000.0
    phase_one_s = 1_000.0 / 50.0
    phase_two_s = 1_000.0 / 100.0
    assert (phase_one_s, phase_two_s) == (20.0, 10.0)

    ceiling_integral = CEILING_AT_50_W * phase_one_s + CEILING_AT_100_W * phase_two_s
    assert ceiling_integral == 8_000_000.0
    deploy_scale = 800_000.0 / ceiling_integral
    assert deploy_scale == pytest.approx(0.1, abs=1e-15)

    speed_integral = 50.0 * phase_one_s + 100.0 * phase_two_s
    assert speed_integral == 2_000.0
    harvest_scale = 600_000.0 / speed_integral
    assert harvest_scale == pytest.approx(300.0, abs=1e-12)

    net_phase_one_w = harvest_scale * 50.0 - deploy_scale * CEILING_AT_50_W
    net_phase_two_w = harvest_scale * 100.0 - deploy_scale * CEILING_AT_100_W
    assert net_phase_one_w == pytest.approx(-20_000.0, abs=1e-9)
    assert net_phase_two_w == pytest.approx(+20_000.0, abs=1e-9)

    energy_at_break_j = start_energy_j + net_phase_one_w * phase_one_s
    energy_at_end_j = energy_at_break_j + net_phase_two_w * phase_two_s
    assert energy_at_break_j == pytest.approx(-20_000.0, abs=1e-6)
    assert energy_at_end_j == pytest.approx(180_000.0, abs=1e-6)

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=3_000.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=800_000.0,
                harvest_target_j=600_000.0,
                execution_window_s=2.0,
            )
        ],
        declared_status=CheckStatus.PASS,
    )
    state = checker_state(
        session_time_s=10.0,
        progress_m=900.0,
        battery_energy_j=start_energy_j,
        speed_profile=two_phase_speed(50.0, 2_000.0, 100.0),
        current_power_w=deploy_scale * CEILING_AT_50_W,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=start_energy_j, progress_m=900.0)

    trace = build_trace(plan, state, context, manifest=pack_v1.manifest)
    assert trace.points[0].battery_energy_j == pytest.approx(start_energy_j, abs=1e-6)
    assert trace.points[-1].battery_energy_j == pytest.approx(energy_at_end_j, abs=1e-6)

    floor_j = pack_v1.manifest.battery_energy_min_j
    # An endpoint-only check would have accepted this plan.
    endpoint_only_margin = min(trace.points[0].battery_energy_j, trace.points[-1].battery_energy_j) - floor_j
    assert endpoint_only_margin == pytest.approx(180_000.0, abs=1e-6)
    assert endpoint_only_margin > 0.0

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    energy_check = checks_by_id(result)["battery_energy_window"]
    assert energy_check.status is CheckStatus.FAIL
    assert energy_check.margin == pytest.approx(energy_at_break_j - floor_j, abs=1e-6)
    assert energy_check.margin == pytest.approx(-20_000.0, abs=1e-6)
    assert energy_check.at_progress_m == pytest.approx(2_000.0, abs=1e-9)
    assert result.status is CheckStatus.FAIL
    # The plan declared itself feasible; the checker did not take its word.
    assert plan.constraint_result.status is CheckStatus.PASS


def test_solver_declared_pass_is_still_rejected(pack_v1):
    """A converged solver output carrying a PASS is re-derived, not trusted."""
    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=3_000.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=800_000.0,
                harvest_target_j=600_000.0,
                execution_window_s=2.0,
            )
        ],
        declared_status=CheckStatus.PASS,
    )
    state = checker_state(
        session_time_s=10.0,
        progress_m=900.0,
        battery_energy_j=380_000.0,
        speed_profile=two_phase_speed(50.0, 2_000.0, 100.0),
        current_power_w=35_000.0,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=380_000.0, progress_m=900.0)
    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    assert plan.solver_status == "converged"
    assert plan.constraint_result.status is CheckStatus.PASS
    assert result.status is CheckStatus.FAIL
    assert result.checker_version != plan.constraint_result.checker_version


def test_legal_plan_passes_every_check(pack_v1):
    """A plan that satisfies every constraint, with each margin worked out.

    Constant 50 m/s, so the ceiling is 350 kW throughout.

        segment 0: OVERTAKE 1900 -> 2100 m = 200 m = 4.0 s,
                   budget 700000 J -> 175 kW (= 700000 / 4)
        segment 1: CONSERVE 2100 -> 3500 m = 1400 m = 28.0 s,
                   budget 280000 J -> 10 kW, harvest 700000 J -> 25 kW
    """
    speed_mps = 50.0
    seg0_s = 200.0 / speed_mps
    seg1_s = 1_400.0 / speed_mps
    assert (seg0_s, seg1_s) == (4.0, 28.0)

    seg0_deploy_w = 700_000.0 / seg0_s
    seg1_deploy_w = 280_000.0 / seg1_s
    seg1_harvest_w = 700_000.0 / seg1_s
    assert seg0_deploy_w == 175_000.0
    assert seg1_deploy_w == 10_000.0
    assert seg1_harvest_w == 25_000.0

    start_energy_j = 1_000_000.0
    energy_at_2100_j = start_energy_j - seg0_deploy_w * seg0_s
    energy_at_3500_j = energy_at_2100_j + (seg1_harvest_w - seg1_deploy_w) * seg1_s
    assert energy_at_2100_j == 300_000.0
    assert energy_at_3500_j == 720_000.0

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_900.0,
                end_progress_m=2_100.0,
                profile_id=DeploymentProfile.OVERTAKE,
                requested_budget_j=700_000.0,
                harvest_target_j=0.0,
                execution_window_s=2.0,
            ),
            ProfileSegment(
                start_progress_m=2_100.0,
                end_progress_m=3_500.0,
                profile_id=DeploymentProfile.CONSERVE,
                requested_budget_j=280_000.0,
                harvest_target_j=700_000.0,
                execution_window_s=4.0,
            ),
        ]
    )
    state = checker_state(
        session_time_s=20.0,
        progress_m=1_850.0,
        battery_energy_j=start_energy_j,
        speed_profile=constant_speed(speed_mps),
        current_power_w=seg0_deploy_w,
    )
    context = context_for(pack_v1, speed_mps=speed_mps, battery_energy_j=start_energy_j, progress_m=1_850.0)
    assert DeploymentProfile.OVERTAKE in context.admissible_profiles

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert result.status is CheckStatus.PASS

    assert checks["power_ceiling"].margin == pytest.approx(CEILING_AT_50_W - seg0_deploy_w, abs=1e-6)
    assert checks["power_ceiling"].margin == pytest.approx(175_000.0, abs=1e-6)

    floor_j = pack_v1.manifest.battery_energy_min_j
    ceiling_j = pack_v1.manifest.battery_energy_max_j
    expected_energy_margin = min(energy_at_2100_j - floor_j, ceiling_j - start_energy_j)
    assert expected_energy_margin == 300_000.0
    assert checks["battery_energy_window"].margin == pytest.approx(300_000.0, abs=1e-6)

    # Charge-bus efficiency is 1.0 here, so the ledger equals the battery gain.
    assert checks["recharge_allowance"].margin == pytest.approx(8_500_000.0 - 700_000.0, abs=1e-6)

    # Entry transition is zero; the profile change is 175 kW -> 10 kW over 4.0 s.
    expected_rate = (seg0_deploy_w - seg1_deploy_w) / 4.0
    assert expected_rate == pytest.approx(41_250.0, abs=1e-9)
    assert checks["power_ramp"].margin == pytest.approx(700_000.0 - expected_rate, abs=1e-6)

    # Derate factor 1.0 at 300 K, so the derated ceiling equals the regulatory one.
    assert checks["thermal_derate"].margin == pytest.approx(175_000.0, abs=1e-6)

    # The overtake segment ends exactly on the attack-exit checkpoint that closes
    # the activation zone [1900, 2100]: zero metres of headroom, still legal.
    assert checks["overtake_eligibility"].margin == pytest.approx(0.0, abs=1e-9)
    assert checks["overtake_eligibility"].status is CheckStatus.PASS

    # Lead time: 50 m at 50 m/s = 1.0 s, minus the 0.6 s reaction time.
    assert checks["execution_lead_time"].margin == pytest.approx(0.4, abs=1e-9)


def test_power_above_speed_curve_fails_with_negative_margin(pack_v1):
    """At 100 m/s the curve allows 100 kW; the plan asks for 130 kW.

    One segment, 2000 -> 3000 m at a constant 100 m/s = 10.0 s.
    budget 1300000 J -> 130 kW, against a 100 kW ceiling: margin -30 kW.
    """
    speed_mps = 100.0
    duration_s = 1_000.0 / speed_mps
    assert duration_s == 10.0
    deploy_w = 1_300_000.0 / duration_s
    assert deploy_w == 130_000.0
    expected_margin_w = CEILING_AT_100_W - deploy_w
    assert expected_margin_w == -30_000.0

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=2_000.0,
                end_progress_m=3_000.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=1_300_000.0,
                harvest_target_j=0.0,
                execution_window_s=1.0,
            )
        ],
        intention=ActionCode.PREPARE_ATTACK,
    )
    state = checker_state(
        session_time_s=30.0,
        progress_m=1_990.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(speed_mps),
        current_power_w=deploy_w,
        driver_reaction_time_s=0.05,
    )
    context = context_for(pack_v1, speed_mps=speed_mps, battery_energy_j=2_000_000.0, progress_m=1_990.0)
    assert context.applicable_limits.deployment_ceiling_w == pytest.approx(CEILING_AT_100_W, abs=1e-9)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert checks["power_ceiling"].status is CheckStatus.FAIL
    assert checks["power_ceiling"].margin == pytest.approx(expected_margin_w, abs=1e-6)
    assert checks["power_ceiling"].limit == pytest.approx(CEILING_AT_100_W, abs=1e-6)
    assert checks["power_ceiling"].observed == pytest.approx(deploy_w, abs=1e-6)
    # 2 MJ - 1.3 MJ = 0.7 MJ, still inside the window, so energy is not the cause.
    assert checks["battery_energy_window"].status is CheckStatus.PASS
    assert result.status is CheckStatus.FAIL


def test_impossible_ramp_is_rejected(pack_v1):
    """20 kW -> 350 kW inside a 0.3 s execution window is 1.1 MW/s.

    Constant 50 m/s, ceiling 350 kW.
        segment 0: CONSERVE 1000 -> 1500 m = 10.0 s, budget 200000 J ->  20 kW
        segment 1: PUSH     1500 -> 2000 m = 10.0 s, budget 3.5e6 J  -> 350 kW
    The demanded change is 330 kW over 0.3 s = 1100000 W/s against a
    700000 W/s limit: margin -400000 W/s.
    """
    speed_mps = 50.0
    duration_s = 500.0 / speed_mps
    assert duration_s == 10.0
    seg0_deploy_w = 200_000.0 / duration_s
    seg1_deploy_w = 3_500_000.0 / duration_s
    assert (seg0_deploy_w, seg1_deploy_w) == (20_000.0, 350_000.0)

    window_s = 0.3
    demanded_rate = (seg1_deploy_w - seg0_deploy_w) / window_s
    assert demanded_rate == pytest.approx(1_100_000.0, abs=1e-9)
    expected_margin = 700_000.0 - demanded_rate
    assert expected_margin == pytest.approx(-400_000.0, abs=1e-9)

    start_energy_j = 3_900_000.0
    energy_at_1500_j = start_energy_j - 200_000.0
    energy_at_2000_j = energy_at_1500_j - 3_500_000.0
    assert (energy_at_1500_j, energy_at_2000_j) == (3_700_000.0, 200_000.0)

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=1_500.0,
                profile_id=DeploymentProfile.CONSERVE,
                requested_budget_j=200_000.0,
                harvest_target_j=0.0,
                execution_window_s=1.0,
            ),
            ProfileSegment(
                start_progress_m=1_500.0,
                end_progress_m=2_000.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=3_500_000.0,
                harvest_target_j=0.0,
                execution_window_s=window_s,
            ),
        ]
    )
    state = checker_state(
        session_time_s=40.0,
        progress_m=900.0,
        battery_energy_j=start_energy_j,
        speed_profile=constant_speed(speed_mps),
        current_power_w=seg0_deploy_w,
        driver_reaction_time_s=0.2,
    )
    context = context_for(pack_v1, speed_mps=speed_mps, battery_energy_j=start_energy_j, progress_m=900.0)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert checks["power_ramp"].status is CheckStatus.FAIL
    assert checks["power_ramp"].margin == pytest.approx(expected_margin, abs=1e-6)
    assert checks["power_ramp"].observed == pytest.approx(demanded_rate, abs=1e-6)
    # The second segment sits exactly on the 350 kW ceiling, so the ramp is the
    # only violation.
    assert checks["power_ceiling"].status is CheckStatus.PASS
    assert checks["power_ceiling"].margin == pytest.approx(0.0, abs=1e-6)
    assert checks["battery_energy_window"].status is CheckStatus.PASS
    assert result.status is CheckStatus.FAIL


def test_recharge_allowance_is_measured_on_the_charge_bus(pack_v1):
    """The ledger is a CU-K DC figure; the battery-gain figure would have passed.

    600000 J of battery gain at a charge-bus efficiency of 0.8 costs
    600000 / 0.8 = 750000 J on the bus. With 7900000 J already used this lap:

        battery-gain reading: 7900000 + 600000 = 8500000 J -> margin exactly 0
        charge-bus reading:   7900000 + 750000 = 8650000 J -> margin -150000 J
    """
    allowance_j = pack_v1.manifest.recharge_allowance_per_lap_j
    assert allowance_j == 8_500_000.0
    assert pack_v1.manifest.recharge_measurement_bus == "cu_k_dc"

    used_j = 7_900_000.0
    battery_gain_j = 600_000.0
    efficiency = 0.8
    bus_energy_j = battery_gain_j / efficiency
    assert bus_energy_j == 750_000.0

    wrong_bus_margin = allowance_j - (used_j + battery_gain_j)
    right_bus_margin = allowance_j - (used_j + bus_energy_j)
    assert wrong_bus_margin == 0.0
    assert right_bus_margin == -150_000.0

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=2_000.0,
                profile_id=DeploymentProfile.HARVEST,
                requested_budget_j=0.0,
                harvest_target_j=battery_gain_j,
                execution_window_s=2.0,
            )
        ],
        intention=ActionCode.RECOVER,
    )
    state = checker_state(
        session_time_s=50.0,
        progress_m=900.0,
        battery_energy_j=1_000_000.0,
        speed_profile=constant_speed(50.0),
        recharge_used_this_lap_j=used_j,
        charge_bus_efficiency=efficiency,
    )
    context = context_for(
        pack_v1,
        speed_mps=50.0,
        battery_energy_j=1_000_000.0,
        progress_m=900.0,
        recharge_used_this_lap_j=used_j,
    )

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    check = checks_by_id(result)["recharge_allowance"]
    assert check.status is CheckStatus.FAIL
    assert check.margin == pytest.approx(right_bus_margin, abs=1e-6)
    assert check.observed == pytest.approx(used_j + bus_energy_j, abs=1e-6)
    assert "cu_k_dc" in (check.detail or "")


def test_recharge_ledger_resets_at_a_lap_rollover(pack_v1):
    """Only the lap-scoped ledger resets at the line; no energy is created.

    One HARVEST segment 4500 -> 5500 m on a 5000 m track at 50 m/s, so 10.0 s
    each side of the rollover, harvesting 800000 J in total at 40 kW.

        peak of lap N   = 8000000 + 400000 = 8400000 J  (margin +100000 J)
        without a reset = 8000000 + 800000 = 8800000 J  (would have failed)
        after the reset the new lap's ledger reaches 400000 J
    """
    allowance_j = pack_v1.manifest.recharge_allowance_per_lap_j
    used_j = 8_000_000.0
    battery_gain_j = 800_000.0
    half_j = battery_gain_j / 2.0

    peak_this_lap_j = used_j + half_j
    would_be_without_reset_j = used_j + battery_gain_j
    assert peak_this_lap_j == 8_400_000.0
    assert would_be_without_reset_j == 8_800_000.0
    assert allowance_j - peak_this_lap_j == 100_000.0
    assert allowance_j - would_be_without_reset_j == -300_000.0

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=4_500.0,
                end_progress_m=5_500.0,
                profile_id=DeploymentProfile.HARVEST,
                requested_budget_j=0.0,
                harvest_target_j=battery_gain_j,
                execution_window_s=2.0,
            )
        ],
        intention=ActionCode.RECOVER,
    )
    state = checker_state(
        session_time_s=60.0,
        progress_m=4_400.0,
        battery_energy_j=1_000_000.0,
        speed_profile=constant_speed(50.0),
        recharge_used_this_lap_j=used_j,
    )
    context = context_for(
        pack_v1,
        speed_mps=50.0,
        battery_energy_j=1_000_000.0,
        progress_m=4_400.0,
        recharge_used_this_lap_j=used_j,
    )

    trace = build_trace(plan, state, context, manifest=pack_v1.manifest)
    assert max(p.recharge_ledger_j for p in trace.points) == pytest.approx(peak_this_lap_j, abs=1e-6)
    assert trace.points[-1].recharge_ledger_j == pytest.approx(half_j, abs=1e-6)
    assert trace.points[-1].lap_index == 1
    # Energy is not created by the reset: the battery still gained exactly once.
    assert trace.points[-1].battery_energy_j == pytest.approx(1_800_000.0, abs=1e-6)

    check = checks_by_id(check_plan(plan, state, context, manifest=pack_v1.manifest))["recharge_allowance"]
    assert check.status is CheckStatus.PASS
    assert check.margin == pytest.approx(100_000.0, abs=1e-6)


def test_thermal_derate_lowers_the_ceiling_and_rejects_the_plan(pack_v1):
    """At 363.15 K the derate factor is 0.8, so 350 kW becomes 280 kW.

    The derate model runs from 1.0 at 353.15 K to 0.6 at 373.15 K, and 363.15 K
    is exactly half way: 1.0 + 0.5 * (0.6 - 1.0) = 0.8.

    One 1000 -> 1100 m segment at 50 m/s = 2.0 s, budget 600000 J -> 300 kW.
        regulatory margin: 350000 - 300000 = +50000 W  (passes)
        derated margin:    280000 - 300000 = -20000 W  (fails)
    """
    temperature_k = 363.15
    expected_factor = 1.0 + 0.5 * (0.6 - 1.0)
    assert expected_factor == pytest.approx(0.8, abs=1e-12)

    duration_s = 100.0 / 50.0
    deploy_w = 600_000.0 / duration_s
    assert (duration_s, deploy_w) == (2.0, 300_000.0)

    derated_ceiling_w = CEILING_AT_50_W * expected_factor
    assert derated_ceiling_w == pytest.approx(280_000.0, abs=1e-9)

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=1_100.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=600_000.0,
                harvest_target_j=0.0,
                execution_window_s=1.0,
            )
        ]
    )
    state = checker_state(
        session_time_s=70.0,
        progress_m=950.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=deploy_w,
        driver_reaction_time_s=0.3,
    )
    context = context_for(
        pack_v1,
        speed_mps=50.0,
        battery_energy_j=2_000_000.0,
        progress_m=950.0,
        temperature_k=temperature_k,
    )
    assert context.applicable_limits.thermal_derate_factor == pytest.approx(expected_factor, abs=1e-12)
    assert context.applicable_limits.deployment_ceiling_w == pytest.approx(derated_ceiling_w, abs=1e-9)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert checks["power_ceiling"].status is CheckStatus.PASS
    assert checks["power_ceiling"].margin == pytest.approx(50_000.0, abs=1e-6)
    assert checks["thermal_derate"].status is CheckStatus.FAIL
    assert checks["thermal_derate"].margin == pytest.approx(-20_000.0, abs=1e-6)
    assert checks["thermal_derate"].limit == pytest.approx(derated_ceiling_w, abs=1e-6)
    assert result.status is CheckStatus.FAIL


def test_insufficient_execution_lead_time_fails(pack_v1):
    """20 m of run-up at 50 m/s is 0.4 s; the driver needs 0.9 s."""
    lead_time_s = 20.0 / 50.0
    reaction_s = 0.9
    expected_margin_s = lead_time_s - reaction_s
    assert lead_time_s == pytest.approx(0.4, abs=1e-12)
    assert expected_margin_s == pytest.approx(-0.5, abs=1e-12)

    duration_s = 500.0 / 50.0
    deploy_w = 350_000.0 / duration_s
    assert (duration_s, deploy_w) == (10.0, 35_000.0)

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=2_000.0,
                end_progress_m=2_500.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=350_000.0,
                harvest_target_j=0.0,
                execution_window_s=2.0,
            )
        ]
    )
    state = checker_state(
        session_time_s=80.0,
        progress_m=1_980.0,
        battery_energy_j=1_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=deploy_w,
        driver_reaction_time_s=reaction_s,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=1_000_000.0, progress_m=1_980.0)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert checks["execution_lead_time"].status is CheckStatus.FAIL
    assert checks["execution_lead_time"].margin == pytest.approx(expected_margin_s, abs=1e-9)
    assert checks["power_ceiling"].status is CheckStatus.PASS
    assert checks["battery_energy_window"].status is CheckStatus.PASS
    assert result.status is CheckStatus.FAIL


def test_overtake_outside_the_activation_zone_is_rejected(pack_v1):
    """The activation zone is [1900, 2100]; the plan runs 200 m past its end."""
    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_950.0,
                end_progress_m=2_300.0,
                profile_id=DeploymentProfile.OVERTAKE,
                requested_budget_j=350_000.0,
                harvest_target_j=0.0,
                execution_window_s=2.0,
            )
        ]
    )
    state = checker_state(
        session_time_s=90.0,
        progress_m=1_900.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=50_000.0,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=2_000_000.0, progress_m=1_900.0)
    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    check = checks_by_id(result)["overtake_eligibility"]
    assert check.status is CheckStatus.FAIL
    # 2100 (zone end) - 2300 (segment end) = -200 m.
    assert check.margin == pytest.approx(-200.0, abs=1e-9)


def test_ineligible_car_may_not_use_the_overtake_profile(pack_v1):
    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_950.0,
                end_progress_m=2_100.0,
                profile_id=DeploymentProfile.OVERTAKE,
                requested_budget_j=350_000.0,
                harvest_target_j=0.0,
                execution_window_s=2.0,
            )
        ]
    )
    state = checker_state(
        session_time_s=95.0,
        progress_m=1_900.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=50_000.0,
    )
    context = context_for(
        pack_v1,
        speed_mps=50.0,
        battery_energy_j=2_000_000.0,
        progress_m=1_900.0,
        eligibility=EligibilityState.INELIGIBLE,
    )
    assert DeploymentProfile.OVERTAKE not in context.admissible_profiles
    check = checks_by_id(check_plan(plan, state, context, manifest=pack_v1.manifest))["overtake_eligibility"]
    assert check.status is CheckStatus.FAIL
    # The whole 150 m request lies outside any permitted zone.
    assert check.margin == pytest.approx(-150.0, abs=1e-9)
