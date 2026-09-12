"""Instruction lifecycle: chatter suppression, invalidation and horizon honesty."""

from __future__ import annotations

from dataclasses import replace

import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CheckStatus,
    ConstraintCheck,
    ConstraintResult,
    DeploymentProfile,
    ObjectiveTerms,
    PlanningStatus,
    ReasonCode,
    RivalIntention,
)
from afterlap_core.planning import (
    ActivePlan,
    InvalidationCause,
    LearnedOutcome,
    ScoredCandidate,
    build_weights,
    plan,
    scenario_losses,
    select_instruction,
    switch_count_for,
    to_profile_segments,
)

from .conftest import context_with, estimate_with, scenario, single_segment_frame


def _passing_result() -> ConstraintResult:
    return ConstraintResult(
        schema_version=SCHEMA_VERSION,
        status=CheckStatus.PASS,
        checks=(ConstraintCheck(check_id="power_ceiling", status=CheckStatus.PASS, margin=1.0, unit="W"),),
        ruleset_hash="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        checked_at_s=12.0,
        checker_version="test",
    )


def _candidate(
    candidate_id: str,
    action_code: ActionCode,
    score: float,
    frame,
    objective,
) -> ScoredCandidate:
    terms = ObjectiveTerms(
        objective_version=objective.objective_id,
        expected_utility=score,
        tail_alpha=objective.tail_alpha,
        cvar_loss=score,
        lambda_tail=objective.lambda_tail,
        switch_count=1,
        lambda_switch=objective.lambda_switch,
        generation_score=score,
        final_score=score,
    )
    return ScoredCandidate(
        candidate_id=candidate_id,
        action_code=action_code,
        frame=frame,
        segments=to_profile_segments(frame, (0.0,), (0.0,)),
        solution=None,  # type: ignore[arg-type]
        scenario_outcomes=(),
        probabilities=(),
        constraint_result=_passing_result(),
        objective=terms,
        reason_codes=(),
        learned=LearnedOutcome(enabled=False, bundle_id=None, reason_codes=(), disagreement=0.0),
    )


def test_a_marginal_improvement_does_not_switch_the_instruction(config, objective):
    """0.30 of improvement against a declared threshold of 0.75 is not a switch.

    The improvement is real but smaller than the value ``objective-v1.yaml``
    declares worth interrupting the driver for, so the instruction in force
    stays, and the decision says so with ``small_expected_improvement``.
    """
    frame = single_segment_frame(config)
    incumbent = _candidate("plan-maintain", ActionCode.MAINTAIN, 10.00, frame, objective)
    challenger = _candidate("plan-defend", ActionCode.DEFEND, 9.70, frame, objective)
    current = ActivePlan(
        plan_id="plan-maintain",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=0.0,
        expires_at_s=100.0,
        ruleset_hash="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        final_score=10.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )

    assert objective.improvement_threshold == pytest.approx(0.75)
    assert objective.minimum_dwell_s == pytest.approx(3.0)

    selection = select_instruction([incumbent, challenger], objective, current=current, now_s=30.0)
    assert selection.switched is False
    assert selection.chosen is incumbent
    assert selection.improvement == pytest.approx(0.30)
    assert ReasonCode.SMALL_EXPECTED_IMPROVEMENT in selection.reason_codes


def test_a_clear_improvement_after_the_dwell_does_switch(config, objective):
    """1.50 of improvement clears the 0.75 threshold once the dwell has elapsed."""
    frame = single_segment_frame(config)
    incumbent = _candidate("plan-maintain", ActionCode.MAINTAIN, 10.0, frame, objective)
    challenger = _candidate("plan-defend", ActionCode.DEFEND, 8.5, frame, objective)
    current = ActivePlan(
        plan_id="plan-maintain",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=0.0,
        expires_at_s=100.0,
        ruleset_hash="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        final_score=10.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    selection = select_instruction([incumbent, challenger], objective, current=current, now_s=30.0)
    assert selection.switched is True
    assert selection.chosen is challenger
    assert selection.improvement == pytest.approx(1.5)


def test_minimum_dwell_holds_a_clear_improvement(config, objective):
    """Inside the 3 s dwell even a large improvement waits."""
    frame = single_segment_frame(config)
    incumbent = _candidate("plan-maintain", ActionCode.MAINTAIN, 10.0, frame, objective)
    challenger = _candidate("plan-defend", ActionCode.DEFEND, 1.0, frame, objective)
    current = ActivePlan(
        plan_id="plan-maintain",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=10.0,
        expires_at_s=100.0,
        ruleset_hash="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        final_score=10.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    selection = select_instruction([incumbent, challenger], objective, current=current, now_s=11.0)
    assert selection.switched is False
    assert ReasonCode.SWITCH_COST_DOMINATES in selection.reason_codes


def test_invalidation_overrides_the_minimum_dwell(config, objective):
    """A rule change switches immediately, inside the dwell and inside the threshold.

    The improvement here is 0.05, far below the declared threshold, and only one
    second of a three-second dwell has passed. Hysteresis must not survive an
    invalidation.
    """
    frame = single_segment_frame(config)
    incumbent = _candidate("plan-maintain", ActionCode.MAINTAIN, 10.00, frame, objective)
    challenger = _candidate("plan-defend", ActionCode.DEFEND, 9.95, frame, objective)
    current = ActivePlan(
        plan_id="plan-maintain",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=10.0,
        expires_at_s=100.0,
        ruleset_hash="sha256:ba1f901674fe78051274115463e06e9b2410eb4beb1a99039c1c17225dd7b586",
        final_score=10.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    held = select_instruction([incumbent, challenger], objective, current=current, now_s=11.0)
    assert held.switched is False

    invalidated = select_instruction(
        [incumbent, challenger],
        objective,
        current=current,
        now_s=11.0,
        invalidation=InvalidationCause.RULESET_CHANGED,
    )
    assert invalidated.switched is True
    assert invalidated.chosen is challenger
    assert invalidated.invalidation is InvalidationCause.RULESET_CHANGED


def test_a_rule_pack_change_switches_the_instruction_end_to_end(manifest, config, world):
    """The planner detects the hash change and replans inside the dwell."""
    estimate = estimate_with()
    context = context_with(
        ruleset_hash="sha256:330439706dad7fad552ad835a8509d6ecff101f7489e389e1da121e65b2bdf7c"
    )
    current = ActivePlan(
        plan_id="plan-maintain-r4",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=estimate.created_at_s - 0.5,
        expires_at_s=estimate.created_at_s + 100.0,
        ruleset_hash="sha256:5f4a17f8038c6a0f90d5ff3fd751d490c0c89a76a6754debdce211b49b6868a2",
        final_score=0.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    result = plan(
        estimate,
        context,
        None,
        5.0,
        manifest=manifest,
        config=config,
        world=world,
        current_plan=current,
    )
    assert result.status is PlanningStatus.OK
    assert "invalidation" in (result.detail or "")
    assert "ruleset_changed" in (result.detail or "")


def test_a_greedy_pass_is_not_credited_as_permanent_progress(config, objective):
    """A greedy pass is valued through the whole horizon, not banked at the line.

    Two schedules over a two-segment corridor against a rival holding 1.8 MJ:

    * ``greedy`` empties the battery — 600 kJ in each segment — and really is
      quicker to the near checkpoint;
    * ``reserved`` spends 200 kJ in each and is slower there.

    The comparison the specification asks for is between *scoring rules*, not
    between horizons. The naive rule — credit the position won at the near
    checkpoint and stop counting — is written out here explicitly by zeroing the
    continuation and counterattack terms, and under it greedy wins comfortably.
    The planner's actual rule scores the full defined horizon, and under it the
    reserve deficit greedy created hands the rival a counterattack worth more
    than the time it bought, so greedy loses.

    Note what this test does **not** do. Simply truncating the frame to the near
    checkpoint does not reproduce the naive rule, because the continuation and
    counterattack terms attach to the end of whatever corridor is evaluated: on
    the truncated frame greedy already loses, 14.62 to 13.94. That is the model
    behaving correctly — there is no horizon at which it credits a pass as
    permanent — so the naive rule has to be constructed deliberately to have
    something to compare against.
    """
    estimate = estimate_with()
    full = replace(
        single_segment_frame(config, length_m=300.0, max_deploy_j=700_000.0),
        initial_energy_j=2_000_000.0,
        continuation_availability=1.0,
    )
    first = full.segments[0]
    second = replace(
        first,
        index=1,
        start_progress_m=first.end_progress_m,
        end_progress_m=first.end_progress_m + 300.0,
    )
    full = replace(full, segments=(first, second), end_progress_m=second.end_progress_m, horizon_s=8.0)
    near = replace(full, segments=(first,), end_progress_m=first.end_progress_m, horizon_s=4.0)

    weights = build_weights(full, estimate, objective, config)
    near_weights = build_weights(near, estimate, objective, config)
    permanent_progress_rule = replace(near_weights, energy_value_rate=0.0, counterattack_rate_s_per_j=0.0)
    rival = (scenario("counterattacking", reserve_j=1_800_000.0, intention=RivalIntention.ATTACK),)
    assert weights.position_penalty > 0.0
    assert weights.counterattack_rate_s_per_j > 0.0

    greedy = ((600_000.0, 600_000.0), (0.0, 0.0))
    reserved = ((200_000.0, 200_000.0), (0.0, 0.0))

    naive_greedy, greedy_near_time, greedy_near_energy = scenario_losses(
        near, rival, permanent_progress_rule, greedy[0][:1], greedy[1][:1]
    )
    naive_reserved, reserved_near_time, reserved_near_energy = scenario_losses(
        near, rival, permanent_progress_rule, reserved[0][:1], reserved[1][:1]
    )
    assert greedy_near_time < reserved_near_time, "greedy really is quicker to the near checkpoint"
    assert greedy_near_energy < reserved_near_energy, "and it paid 400 kJ for that"
    assert naive_greedy[0] < naive_reserved[0], (
        "under a rule that banks the near-checkpoint position, greedy wins - "
        "this is the valuation the planner must not use"
    )

    full_greedy, greedy_time, greedy_energy = scenario_losses(full, rival, weights, *greedy)
    full_reserved, reserved_time, reserved_energy = scenario_losses(full, rival, weights, *reserved)
    assert greedy_time < reserved_time, "greedy is still quicker over the corridor"
    assert greedy_energy < reserved_energy, "but it arrives with far less in the battery"
    assert full_greedy[0] > full_reserved[0], (
        "through the full defined horizon the counterattack takes the place back, "
        "so the greedy schedule must rank below the reserved one"
    )

    deficit_greedy = 1_800_000.0 - greedy_energy
    deficit_reserved = 1_800_000.0 - reserved_energy
    counter_swing_s = weights.counterattack_rate_s_per_j * (deficit_greedy - deficit_reserved)
    assert counter_swing_s > (reserved_time - greedy_time)

    assert (naive_greedy[0] < naive_reserved[0]) is not (full_greedy[0] < full_reserved[0])


def test_truncating_the_corridor_does_not_bank_the_position(config, objective):
    """There is no horizon at which the surrogate credits a pass as permanent.

    The continuation value and the counterattack response attach to the end of
    whatever corridor is scored, so shortening the corridor moves the accounting
    with it rather than dropping it. A planner that valued only the explicit
    corridor and ignored what follows it would rank greedy first here.
    """
    estimate = estimate_with()
    near = replace(
        single_segment_frame(config, length_m=300.0, max_deploy_j=700_000.0),
        initial_energy_j=2_000_000.0,
        continuation_availability=1.0,
    )
    weights = build_weights(near, estimate, objective, config)
    rival = (scenario("counterattacking", reserve_j=1_800_000.0, intention=RivalIntention.ATTACK),)

    greedy, _, _ = scenario_losses(near, rival, weights, (600_000.0,), (0.0,))
    reserved, _, _ = scenario_losses(near, rival, weights, (200_000.0,), (0.0,))
    assert greedy[0] > reserved[0]


def test_switch_count_charges_the_head_change_and_every_transition(config):
    """``lambda_switch`` is charged per instruction the engineer must call."""
    frame = single_segment_frame(config)
    first = frame.segments[0]
    second = replace(
        first,
        index=1,
        profile=DeploymentProfile.PUSH,
        start_progress_m=first.end_progress_m,
        end_progress_m=first.end_progress_m + 300.0,
    )
    frame = replace(frame, segments=(first, second))
    segments = to_profile_segments(frame, (0.0, 0.0), (0.0, 0.0))

    assert switch_count_for(segments, DeploymentProfile.NEUTRAL) == 1
    assert switch_count_for(segments, DeploymentProfile.HARVEST) == 2
    assert switch_count_for(segments, None) == 2
    assert switch_count_for((), DeploymentProfile.NEUTRAL) == 0
