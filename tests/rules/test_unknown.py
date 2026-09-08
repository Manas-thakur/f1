"""Unknown is a first-class result and it suppresses advice.

An unresolved *applicable* condition must empty ``admissible_profiles``, make
the affected check ``unknown`` with ``margin=None``, and drag the aggregate
verdict to ``unknown`` rather than to ``pass``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from afterlap_contracts import (
    CheckStatus,
    ConstraintCheck,
    DeploymentProfile,
    EligibilityState,
    ProfileSegment,
)
from afterlap_core.rules import (
    THERMAL_TEMPERATURE_UNKNOWN,
    CarState,
    check_plan,
    resolve_pack_context,
)

from .conftest import checker_state, checks_by_id, constant_speed, make_plan

CRITICAL_CONDITION = "overtake_gap_threshold_from_unresolved_event_document"
ADVISORY_CONDITION = "event_supporting_document_referenced_but_not_resolved"


def unknown_context(pack_unknown):
    car = CarState(
        speed_mps=50.0,
        battery_energy_j=1_000_000.0,
        temperature_k=300.0,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=19.0,
    )
    return resolve_pack_context(pack_unknown, 1_850.0, 20.0, car, session_id="unknown-session")


def overtake_plan():
    return make_plan(
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


def overtake_state():
    return checker_state(
        session_time_s=20.0,
        progress_m=1_850.0,
        battery_energy_j=1_000_000.0,
        speed_profile=constant_speed(50.0),
        current_power_w=175_000.0,
    )


def test_unknown_pack_yields_no_admissible_profiles(pack_unknown):
    context = unknown_context(pack_unknown)

    assert context.unknown_conditions == (CRITICAL_CONDITION,)
    assert context.has_unknown_critical_condition is True
    assert context.admissible_profiles == ()
    assert context.permits(DeploymentProfile.NEUTRAL) is False

    assert ADVISORY_CONDITION in pack_unknown.manifest.unknown_conditions
    assert CRITICAL_CONDITION in pack_unknown.manifest.unknown_conditions
    assert {spec.condition for spec in pack_unknown.critical_unknown_conditions} == {CRITICAL_CONDITION}


def test_unknown_pack_admits_no_overtake_plan(pack_unknown):
    context = unknown_context(pack_unknown)
    result = check_plan(overtake_plan(), overtake_state(), context, manifest=pack_unknown.manifest)
    check = checks_by_id(result)["overtake_eligibility"]

    assert DeploymentProfile.OVERTAKE not in context.admissible_profiles
    assert check.status is CheckStatus.UNKNOWN
    assert check.margin is None
    assert CRITICAL_CONDITION in (check.detail or "")
    assert check.status is not CheckStatus.PASS


def test_unknown_check_has_no_margin(pack_unknown):
    context = unknown_context(pack_unknown)
    result = check_plan(overtake_plan(), overtake_state(), context, manifest=pack_unknown.manifest)

    unknown_checks = [c for c in result.checks if c.status is CheckStatus.UNKNOWN]
    assert unknown_checks
    for check in unknown_checks:
        assert check.margin is None

    with pytest.raises(ValidationError):
        ConstraintCheck(check_id="overtake_eligibility", status=CheckStatus.UNKNOWN, margin=0.0)


def test_aggregate_is_unknown_when_any_check_is_unknown(pack_unknown):
    context = unknown_context(pack_unknown)
    result = check_plan(overtake_plan(), overtake_state(), context, manifest=pack_unknown.manifest)

    statuses = {check.check_id: check.status for check in result.checks}
    assert statuses["overtake_eligibility"] is CheckStatus.UNKNOWN
    assert CheckStatus.FAIL not in statuses.values()
    assert result.status is CheckStatus.UNKNOWN
    assert result.status is not CheckStatus.PASS
    assert set(result.unresolved_conditions) == {CRITICAL_CONDITION, ADVISORY_CONDITION}


def test_unknown_pack_still_reports_numeric_power_margins(pack_unknown):
    """Suppressing advice does not erase the arithmetic that was possible.

    The first segment deploys 700000 J over 200 m at 50 m/s = 4.0 s, i.e.
    175 kW against the 350 kW ceiling: a +175 kW margin.
    """
    context = unknown_context(pack_unknown)
    result = check_plan(overtake_plan(), overtake_state(), context, manifest=pack_unknown.manifest)
    checks = checks_by_id(result)

    expected_deploy_w = 700_000.0 / (200.0 / 50.0)
    assert expected_deploy_w == 175_000.0
    assert checks["power_ceiling"].status is CheckStatus.PASS
    assert checks["power_ceiling"].margin == pytest.approx(350_000.0 - expected_deploy_w, abs=1e-6)

    assert checks["battery_energy_window"].margin == pytest.approx(300_000.0, abs=1e-6)
    assert checks["recharge_allowance"].margin == pytest.approx(8_500_000.0 - 700_000.0, abs=1e-6)
    assert checks["power_ramp"].status is CheckStatus.PASS
    assert checks["execution_lead_time"].status is CheckStatus.PASS


def test_missing_temperature_makes_thermal_derate_unknown(pack_v1):
    """A configured derate model plus no temperature is unknown, not 1.0."""
    car = CarState(
        speed_mps=50.0,
        battery_energy_j=1_000_000.0,
        temperature_k=None,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=19.0,
    )
    context = resolve_pack_context(pack_v1, 1_850.0, 20.0, car, session_id="unknown-session")

    assert THERMAL_TEMPERATURE_UNKNOWN in context.unknown_conditions
    assert context.applicable_limits.thermal_derate_factor is None
    assert context.applicable_limits.deployment_ceiling_w is None
    assert context.admissible_profiles == ()

    result = check_plan(overtake_plan(), overtake_state(), context, manifest=pack_v1.manifest)
    checks = checks_by_id(result)
    assert checks["thermal_derate"].status is CheckStatus.UNKNOWN
    assert checks["thermal_derate"].margin is None
    assert result.status is CheckStatus.UNKNOWN


def test_omitting_the_pack_scoping_fails_closed(pack_v1):
    """resolve_context without the pack's scoping treats every condition as applicable."""
    from afterlap_core.rules import resolve_context

    car = CarState(
        speed_mps=50.0,
        battery_energy_j=1_000_000.0,
        temperature_k=300.0,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=19.0,
    )
    scoped = resolve_pack_context(pack_v1, 1_850.0, 20.0, car, session_id="s")
    assert scoped.unknown_conditions == ()
    assert scoped.admissible_profiles != ()

    unscoped = resolve_context(
        pack_v1.manifest,
        pack_v1.race_events_until(20.0),
        1_850.0,
        20.0,
        car,
        session_id="s",
        thermal_derate=pack_v1.thermal_derate,
    )
    assert unscoped.unknown_conditions == pack_v1.manifest.unknown_conditions
    assert unscoped.admissible_profiles == ()
