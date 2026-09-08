"""Constraints, pruning and the independent checker's authority."""

from __future__ import annotations

from dataclasses import replace

import pytest

from afterlap_contracts import (
    ActionCode,
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    PlanningStatus,
    ReasonCode,
)
from afterlap_core.planning import (
    build_recommendation,
    build_weights,
    enumerate_intentions,
    plan,
    solve_allocation,
)
from afterlap_core.rules import (
    THERMAL_TEMPERATURE_UNKNOWN,
    CarState,
    SpeedProfile,
    SpeedSample,
    admissible_profiles,
)

from .conftest import context_with, estimate_with, scenario, single_segment_frame, solo_estimate

_DEPLOYING = (ActionCode.ATTACK, ActionCode.PREPARE_ATTACK, ActionCode.DEFEND)


def test_unavailable_profile_prunes_the_candidate_before_optimisation(estimate, manifest, config):
    """Without Overtake permission the attack candidate never reaches the solver.

    The enumerator is asked for candidates with the profile removed from the
    admissible set, and the intention disappears with a reason code. Running the
    whole planner then shows that no attack plan exists in either the accepted or
    the rejected list: a rejected record only exists for something that *was*
    optimised, so its absence is evidence the pruning happened first.
    """
    context = context_with(eligibility=EligibilityState.INELIGIBLE)
    admissible = tuple(p for p in context.admissible_profiles if p is not DeploymentProfile.OVERTAKE)
    assert DeploymentProfile.OVERTAKE not in admissible

    result = enumerate_intentions(estimate, context, manifest, config, admissible=admissible)
    assert ActionCode.ATTACK not in {c.template.action_code for c in result.candidates}
    suppressed = {s.action_code: s for s in result.suppressed}
    assert ActionCode.ATTACK in suppressed
    assert ReasonCode.ELIGIBILITY_UNKNOWN in suppressed[ActionCode.ATTACK].reason_codes
    assert "overtake" in suppressed[ActionCode.ATTACK].detail

    planned = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    everything = list(planned.accepted) + list(planned.rejected)
    assert everything, "the other intentions should still be planned"
    assert ActionCode.ATTACK not in {candidate.intention for candidate in everything}


def test_raising_the_terminal_energy_target_reduces_the_deployed_budget(config, objective):
    """A higher checkpoint energy target buys less deployment now.

    With no continuation value the unconstrained optimum sits on the 500 kJ
    deployment bound. Requiring 2.2 MJ at the end of the corridor from a 2.4 MJ
    start caps the schedule at 200 kJ, and the solver must land exactly there.
    """
    estimate = solo_estimate(remaining_distance_m=0.0)
    scenarios = (scenario("solo"),)

    loose = single_segment_frame(config, continuation_availability=0.0, max_deploy_j=500_000.0)
    weights = build_weights(loose, estimate, objective, config)
    unconstrained = solve_allocation(loose, scenarios, weights, objective, config, remaining_deadline_s=5.0)
    assert unconstrained.converged
    assert unconstrained.deploy_j[0] == pytest.approx(500_000.0, rel=1e-6)

    tight = single_segment_frame(
        config,
        continuation_availability=0.0,
        max_deploy_j=500_000.0,
        terminal_target_energy_j=2_200_000.0,
    )
    constrained = solve_allocation(tight, scenarios, weights, objective, config, remaining_deadline_s=5.0)
    assert constrained.converged
    assert constrained.deploy_j[0] < unconstrained.deploy_j[0]
    assert constrained.deploy_j[0] == pytest.approx(200_000.0, rel=1e-5)
    assert constrained.terminal_energy_j >= 2_200_000.0 - 1.0


def test_depleted_energy_directs_no_energy_and_says_why(manifest, config):
    """At the operating floor the planner may not direct any deployment now.

    ``ENERGY_FLOOR`` is reported, every tactical deploying intention is
    suppressed before optimisation, and the instruction that is actually
    published — the head segment, the only one that gets executed — carries a
    zero energy budget. A later segment may deploy, but only what an earlier one
    has already harvested: the floor is a hard bound at every interior point, not
    a preference the objective could trade away.
    """
    estimate = estimate_with(energy_j=0.0)
    context = context_with()
    legal = admissible_profiles(context, CarState(speed_mps=75.0, battery_energy_j=0.0))
    assert DeploymentProfile.PUSH not in legal and DeploymentProfile.OVERTAKE not in legal

    result = plan(
        estimate,
        context,
        None,
        5.0,
        manifest=manifest,
        config=config,
        admissible=legal,
        rollout_enabled=False,
    )
    assert ReasonCode.ENERGY_FLOOR in result.reason_codes
    assert result.status is PlanningStatus.OK
    assert all(candidate.intention not in _DEPLOYING for candidate in result.accepted)
    for candidate in result.accepted:
        assert candidate.profile_segments[0].requested_budget_j == 0.0
        running = 0.0
        for segment in candidate.profile_segments:
            assert segment.requested_budget_j <= running + 1.0, "spent energy it had not harvested"
            running += segment.harvest_target_j - segment.requested_budget_j

    recommendation = build_recommendation(result, estimate, context, config=config)
    assert recommendation is not None
    assert recommendation.action_code not in _DEPLOYING
    assert "0 kJ out" in recommendation.display_text


def test_unknown_battery_temperature_withdraws_advice(manifest, config, estimate):
    """A configured derate model with no temperature suppresses advice entirely.

    The rules module turns a missing temperature into an unresolved applicable
    condition rather than a derate factor of one. The planner must treat that as
    unknown coverage and withdraw, not carry on with the undated ceiling.
    """
    context = context_with(
        unknown_conditions=(THERMAL_TEMPERATURE_UNKNOWN,),
        thermal_derate_factor=None,
        deployment_ceiling_w=None,
    )
    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    assert result.status is PlanningStatus.RULES_UNKNOWN
    assert ReasonCode.THERMAL_DERATE in result.reason_codes
    assert result.accepted == ()

    recommendation = build_recommendation(result, estimate, context, config=config)
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    assert recommendation.plan_id is None


def test_impossibly_short_instruction_window_withdraws_advice(manifest, config, estimate, context):
    """No human could begin a 0.3 s instruction with a 0.6 s reaction time.

    Every corridor is then unexecutable, so every intention is suppressed with
    ``INSUFFICIENT_EXECUTION_LEAD`` and no directive is published.
    """
    execution = config.execution.model_copy(
        update={
            "instruction_execution_window_s": config.execution.instruction_execution_window_s.model_copy(
                update={"value": 0.3}
            )
        }
    )
    impossible = config.model_copy(update={"execution": execution})

    result = plan(estimate, context, None, 5.0, manifest=manifest, config=impossible, rollout_enabled=False)
    assert result.status is PlanningStatus.NO_FEASIBLE_CANDIDATE
    assert ReasonCode.INSUFFICIENT_EXECUTION_LEAD in result.reason_codes
    assert result.accepted == ()

    recommendation = build_recommendation(result, estimate, context, config=impossible)
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE


def test_solver_success_with_checker_failure_is_not_accepted(manifest, config, estimate, context):
    """A converged solve that the independent checker rejects stays rejected.

    The planner's own frame holds the observed 75 m/s, where the pack's speed
    curve allows the full 350 kW. The checker is handed a different — and
    better — speed forecast of 100 m/s, where the same curve allows only
    ``150 000 + (5/15) * (0 - 150 000) = 100 000`` W, and it reintegrates the
    plan over the shorter time that speed implies. The schedule the solver
    converged on therefore demands more power than the curve permits, and the
    candidate must not be accepted no matter how cleanly it solved.

    This is the test that the checker is genuinely in the loop: if the planner
    were reading its own solver status instead, the candidate would be accepted.
    """
    forecast = SpeedProfile(
        samples=(SpeedSample(progress_m=1_950.0, speed_mps=100.0),),
        step=True,
    )
    result = plan(
        estimate,
        context,
        None,
        5.0,
        manifest=manifest,
        config=config,
        speed_profile=forecast,
        rollout_enabled=False,
    )

    considered = list(result.accepted) + list(result.rejected)
    rejected_by_checker = [c for c in considered if c.constraint_result.status is CheckStatus.FAIL]
    assert rejected_by_checker, "the mismatched speed forecast should break at least one schedule"

    accepted_ids = {accepted.id for accepted in result.accepted}
    for candidate in rejected_by_checker:
        assert "Solve_Succeeded" in (candidate.solver_status or "")
        assert candidate.total_requested_energy_j > 1.0
        failed = {check.check_id for check in candidate.constraint_result.failed_checks}
        assert "power_ceiling" in failed
        assert candidate.id not in accepted_ids

    assert all(c.constraint_result.status is CheckStatus.PASS for c in result.accepted)


def test_unknown_check_is_not_treated_as_acceptance(manifest, config, estimate):
    """``unknown`` coverage suppresses advice; it never passes as permission."""
    context = context_with(unknown_conditions=("event_gap_threshold_unresolved",), admissible=())
    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    assert result.status is PlanningStatus.RULES_UNKNOWN
    assert result.accepted == ()
    assert ReasonCode.ELIGIBILITY_UNKNOWN in result.reason_codes


def test_recharge_ledger_is_converted_to_the_charge_bus(config, objective):
    """The per-lap allowance is spent in charge-bus joules, not battery joules.

    With 8.4 MJ of the 8.5 MJ allowance already used, only 100 kJ of bus energy
    remains, which is ``100 000 * 0.9 = 90 000`` J of battery gain. A planner
    that compared battery gain against the allowance directly would think it had
    100 kJ of gain available and overrun the ledger by 11 %.
    """
    estimate = solo_estimate(remaining_distance_m=40_000.0)
    frame = replace(
        single_segment_frame(config, max_harvest_j=400_000.0, continuation_availability=1.0),
        recharge_used_this_lap_j=8_400_000.0,
    )
    weights = build_weights(frame, estimate, objective, config)
    solution = solve_allocation(
        frame, (scenario("solo"),), weights, objective, config, remaining_deadline_s=5.0
    )
    assert solution.converged
    assert solution.harvest_j[0] == pytest.approx(90_000.0, rel=1e-5)
