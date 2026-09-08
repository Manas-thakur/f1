"""The battery ledger must integrate exactly the requested battery energy.

Regression test for the defect A06 found. ``requested_budget_j`` is battery-side
by ``handoffs/decisions.md`` D-01, but the checker derived bus power from it
directly and then divided that bus power by the discharge efficiency again. The
two readings coincide only at ``eta = 1.0``, which every shipped fixture
happened to use, so the defect was latent.

These tests go through the public ``check_plan`` so the defect is observable in
a verdict rather than in an internal number, and the expected energies are
worked out arithmetically here rather than by calling the checker.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import CheckStatus, DeploymentProfile, ProfileSegment
from afterlap_core.rules import check_plan

from .conftest import checker_state, checks_by_id, constant_speed, make_plan
from .test_checker import context_for


def _plan(budget_j: float):
    """One 200 m PUSH segment. At 50 m/s that is exactly 4.0 s."""
    return make_plan(
        [
            ProfileSegment(
                start_progress_m=1_000.0,
                end_progress_m=1_200.0,
                profile_id=DeploymentProfile.PUSH,
                requested_budget_j=budget_j,
                harvest_target_j=0.0,
                execution_window_s=1.0,
            )
        ]
    )


@pytest.mark.parametrize("eta", [1.0, 0.95, 0.90, 0.80])
def test_the_battery_floor_binds_at_the_requested_budget_whatever_the_efficiency(pack_v1, eta):
    """A request for exactly the available battery energy must land on the floor.

    Starting energy is 700 kJ and the floor is 0 J, so a request for 700 kJ of
    *battery* energy drains the pack to exactly empty. That is legal at every
    discharge efficiency, because the request is denominated in battery joules.

    Under the old arithmetic the ledger drained ``700 kJ / eta`` instead, so at
    eta = 0.90 it reached -77.8 kJ and this plan was rejected as a floor
    violation that never existed.
    """
    budget_j = 700_000.0
    plan = _plan(budget_j)
    state = checker_state(
        session_time_s=0.0,
        progress_m=900.0,
        battery_energy_j=budget_j,
        speed_profile=constant_speed(50.0),
        discharge_efficiency=eta,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=budget_j, progress_m=900.0)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    window = checks_by_id(result)["battery_energy_window"]

    assert window.status is CheckStatus.PASS, (
        f"a request for exactly the available battery energy was rejected at eta={eta}; "
        "the ledger is not integrating battery joules"
    )
    assert window.margin == pytest.approx(0.0, abs=1.0)


@pytest.mark.parametrize("eta", [0.95, 0.90])
def test_over_requesting_still_fails_by_the_right_amount(pack_v1, eta):
    """The check must still bite, and by an amount that does not depend on eta."""
    available_j = 700_000.0
    overspend_j = 50_000.0
    plan = _plan(available_j + overspend_j)
    state = checker_state(
        session_time_s=0.0,
        progress_m=900.0,
        battery_energy_j=available_j,
        speed_profile=constant_speed(50.0),
        discharge_efficiency=eta,
    )
    context = context_for(pack_v1, speed_mps=50.0, battery_energy_j=available_j, progress_m=900.0)

    result = check_plan(plan, state, context, manifest=pack_v1.manifest)
    window = checks_by_id(result)["battery_energy_window"]

    assert window.status is CheckStatus.FAIL
    assert window.margin == pytest.approx(-overspend_j, abs=1.0), (
        "the shortfall must be the energy actually over-requested, not that figure inflated by 1/eta"
    )


def test_the_size_of_the_old_defect_is_pinned():
    """Record what the previous arithmetic did, so a regression is recognisable.

    It computed ``deploy_scale = budget / ceiling_integral`` — treating a
    battery-side number as bus-side — and then divided the resulting bus power
    by eta, giving ``budget / eta`` of battery drain.
    """
    budget_j = 700_000.0
    for eta, expected_over_drain in ((0.95, 0.0526316), (0.90, 0.1111111), (0.80, 0.25)):
        old_drain_j = budget_j / eta
        assert old_drain_j / budget_j - 1.0 == pytest.approx(expected_over_drain, rel=1e-5)
