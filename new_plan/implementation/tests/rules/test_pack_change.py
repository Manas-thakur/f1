"""A ruleset change invalidates an outstanding plan.

v2 differs from v1 in the speed curve (250 kW instead of 350 kW at 50 m/s) and
in the per-lap recharge allowance (5.0 MJ instead of 8.5 MJ), so the same plan
must produce different, visibly different, margins — and a different ruleset
hash, which is what lets the backend reject a stale selection.
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
from afterlap_core.rules import CarState, check_plan, load_rule_pack, resolve_pack_context

from .conftest import checker_state, checks_by_id, constant_speed, make_plan


def context_for(pack, *, progress_m, battery_energy_j, recharge_used_this_lap_j=0.0):
    car = CarState(
        speed_mps=50.0,
        battery_energy_j=battery_energy_j,
        temperature_k=300.0,
        recharge_used_this_lap_j=recharge_used_this_lap_j,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=9.0,
    )
    return resolve_pack_context(pack, progress_m, 10.0, car, session_id="pack-change-session")


def test_pack_change_changes_ruleset_hash(pack_v1, pack_v2):
    assert pack_v1.ruleset_hash != pack_v2.ruleset_hash
    assert pack_v1.ruleset_hash.startswith("sha256:")
    # The hash is a content hash, so reloading the same file reproduces it.
    assert load_rule_pack("synthetic-pack-v1").ruleset_hash == pack_v1.ruleset_hash
    assert load_rule_pack("synthetic-pack-v2-strict").ruleset_hash == pack_v2.ruleset_hash
    # Race control is an event stream, not part of the ruleset identity.
    assert pack_v1.ruleset_hash == pack_v1.manifest.content_hash()


def test_plan_legal_under_v1_is_reevaluated_under_v2(pack_v1, pack_v2):
    """600000 J over 1000 -> 1100 m at 50 m/s is 300 kW.

    v1 ceiling at 50 m/s = 350 kW  ->  margin +50 kW (pass)
    v2 ceiling at 50 m/s = 250 kW  ->  margin -50 kW (fail)
    """
    duration_s = 100.0 / 50.0
    deploy_w = 600_000.0 / duration_s
    assert (duration_s, deploy_w) == (2.0, 300_000.0)

    v1_ceiling_w = pack_v1.manifest.curve("baseline-speed-curve").ceiling_w(50.0)
    v2_ceiling_w = pack_v2.manifest.curve("baseline-speed-curve").ceiling_w(50.0)
    assert (v1_ceiling_w, v2_ceiling_w) == (350_000.0, 250_000.0)

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
        ],
        intention=ActionCode.PREPARE_ATTACK,
    )
    state = checker_state(
        session_time_s=10.0,
        progress_m=950.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=deploy_w,
        driver_reaction_time_s=0.3,
    )

    v1_result = check_plan(
        plan,
        state,
        context_for(pack_v1, progress_m=950.0, battery_energy_j=2_000_000.0),
        manifest=pack_v1.manifest,
    )
    v2_result = check_plan(
        plan,
        state,
        context_for(pack_v2, progress_m=950.0, battery_energy_j=2_000_000.0),
        manifest=pack_v2.manifest,
    )

    v1_check = checks_by_id(v1_result)["power_ceiling"]
    v2_check = checks_by_id(v2_result)["power_ceiling"]
    assert v1_check.status is CheckStatus.PASS
    assert v1_check.margin == pytest.approx(v1_ceiling_w - deploy_w, abs=1e-6)
    assert v1_check.margin == pytest.approx(50_000.0, abs=1e-6)
    assert v2_check.status is CheckStatus.FAIL
    assert v2_check.margin == pytest.approx(v2_ceiling_w - deploy_w, abs=1e-6)
    assert v2_check.margin == pytest.approx(-50_000.0, abs=1e-6)
    # The difference between the two verdicts is exactly the ceiling difference.
    assert v1_check.margin - v2_check.margin == pytest.approx(100_000.0, abs=1e-6)
    assert v1_result.status is CheckStatus.PASS
    assert v2_result.status is CheckStatus.FAIL


def test_lower_allowance_in_v2_changes_the_recharge_margin(pack_v1, pack_v2):
    """The same 600000 J of harvest is measured against two different allowances."""
    assert pack_v1.manifest.recharge_allowance_per_lap_j == 8_500_000.0
    assert pack_v2.manifest.recharge_allowance_per_lap_j == 5_000_000.0
    assert pack_v1.manifest.recharge_measurement_bus == pack_v2.manifest.recharge_measurement_bus

    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=2_000.0,
                profile_id=DeploymentProfile.HARVEST,
                requested_budget_j=0.0,
                harvest_target_j=600_000.0,
                execution_window_s=2.0,
            )
        ],
        intention=ActionCode.RECOVER,
    )
    state = checker_state(
        session_time_s=10.0,
        progress_m=900.0,
        battery_energy_j=1_000_000.0,
        speed_profile=constant_speed(50.0),
    )

    v1_margin = checks_by_id(
        check_plan(
            plan,
            state,
            context_for(pack_v1, progress_m=900.0, battery_energy_j=1_000_000.0),
            manifest=pack_v1.manifest,
        )
    )["recharge_allowance"].margin
    v2_margin = checks_by_id(
        check_plan(
            plan,
            state,
            context_for(pack_v2, progress_m=900.0, battery_energy_j=1_000_000.0),
            manifest=pack_v2.manifest,
        )
    )["recharge_allowance"].margin

    assert v1_margin == pytest.approx(8_500_000.0 - 600_000.0, abs=1e-6)
    assert v2_margin == pytest.approx(5_000_000.0 - 600_000.0, abs=1e-6)
    assert v1_margin - v2_margin == pytest.approx(3_500_000.0, abs=1e-6)


def test_checker_reports_the_new_hash_after_a_pack_update(pack_v1, pack_v2):
    """A pack update arriving during selection must be detectable downstream.

    The engineer selected a plan checked against v1. A new pack is promoted. The
    checker re-run reports v2's hash, so a backend comparing the stored hash on
    the selection against the current one rejects the stale selection instead of
    executing advice computed under superseded rules.
    """
    plan = make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=1_100.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=200_000.0,
                harvest_target_j=0.0,
                execution_window_s=1.0,
            )
        ],
        intention=ActionCode.PREPARE_ATTACK,
    )
    state = checker_state(
        session_time_s=10.0,
        progress_m=950.0,
        battery_energy_j=2_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=100_000.0,
        driver_reaction_time_s=0.3,
    )

    v1_context = context_for(pack_v1, progress_m=950.0, battery_energy_j=2_000_000.0)
    selected_result = check_plan(plan, state, v1_context, manifest=pack_v1.manifest)
    selection_ruleset_hash = selected_result.ruleset_hash
    assert selection_ruleset_hash == pack_v1.ruleset_hash

    # ... the coordinator promotes a new pack mid-selection ...
    v2_context = context_for(pack_v2, progress_m=950.0, battery_energy_j=2_000_000.0)
    rechecked = check_plan(plan, state, v2_context, manifest=pack_v2.manifest)

    assert rechecked.ruleset_hash == pack_v2.ruleset_hash
    assert rechecked.ruleset_hash != selection_ruleset_hash
    # This inequality is the backend's rejection criterion.
    assert selection_ruleset_hash != v2_context.ruleset_hash
    assert v1_context.season_revision != v2_context.season_revision
