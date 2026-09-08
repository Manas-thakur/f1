"""Energy allocation: the closed form, symmetry and dominance.

The expected values here are worked out in the tests themselves from the
physical model stated in ``afterlap_core.planning.surrogate``. None of them is
copied from a solver run.
"""

from __future__ import annotations

import math

import pytest

from afterlap_contracts import DeploymentProfile, RivalIntention
from afterlap_core.planning import (
    build_weights,
    scenario_losses,
    solve_allocation,
)

from .conftest import scenario, single_segment_frame, solo_estimate


def _closed_form_deploy_j(
    *,
    speed_mps: float,
    length_m: float,
    drag_kg_per_m: float,
    drivetrain_efficiency: float,
    gamma: float,
    horizon_s: float,
    availability: float,
) -> float:
    """Stationary point of the one-segment loss, derived from scratch.

    With no rival there is no position term, so for a single segment the loss is

        L(e) = w_time * L / (v^3 + b e)^(1/3)  -  v_rate * (E0 - e)

    with ``b = eta_drive * v / (k L)`` and, because the continuation values a
    stored joule at the marginal rate it would buy time at the same reference
    speed,

        v_rate = gamma^H * w_time * eta_drive / (3 k v^3) * availability.

    Differentiating,

        dL/de = -w_time * (1/3) * L * b * (v^3 + b e)^(-4/3) + v_rate
              = -w_time * eta_drive * v / (3 k) * (v^3 + b e)^(-4/3) + v_rate

    (the segment length cancels). Setting it to zero and substituting ``v_rate``:

        v^4 * (v^3 + b e)^(-4/3) = gamma^H * availability
        v^3 + b e = v^3 * (gamma^H * availability)^(-3/4)

    so

        e* = v^3 * ((gamma^H * availability)^(-3/4) - 1) / b.

    ``w_time`` cancels entirely, which is the sanity check that this is a
    physical trade and not an artefact of the objective's scale.
    """
    b = drivetrain_efficiency * speed_mps / (drag_kg_per_m * length_m)
    discount = gamma**horizon_s
    return speed_mps**3 * ((discount * availability) ** (-0.75) - 1.0) / b


def test_hand_computed_single_segment_allocation(config, objective):
    """The optimiser reproduces the analytic stationary point.

    Numbers for this case, all visible here:

    * segment 300 m at a held 75 m/s, so the horizon is exactly 4.0 s;
    * ``k = 0.5 * 1.2 * 1.0 = 0.6`` kg/m and ``eta_drive = 0.95``, so
      ``b = 0.95 * 75 / (0.6 * 300) = 0.3958333...``;
    * ``v^3 = 421875``;
    * ``gamma = exp(-1/300)``, so ``gamma^4 = exp(-4/300) = 0.986755...``;
    * remaining race distance 16 000 m against a 20 000 m continuation scale
      gives ``availability = 0.8``;
    * ``0.986755 * 0.8 = 0.7894042`` and ``0.7894042^(-3/4) = 1.1940610``, so
      ``e* = 421875 * 0.1940610 / 0.3958333 = 206 825 J`` (to the nearest joule).
    """
    estimate = solo_estimate(remaining_distance_m=16_000.0)
    frame = single_segment_frame(
        config,
        length_m=300.0,
        speed_mps=75.0,
        continuation_availability=0.8,
        max_deploy_j=700_000.0,
        max_harvest_j=0.0,
    )
    assert frame.horizon_s == pytest.approx(4.0)
    assert config.surrogate.drag_constant_kg_per_m == pytest.approx(0.6)

    weights = build_weights(frame, estimate, objective, config)
    assert weights.position_penalty == 0.0, "a solo car has no position to contest"

    expected_j = _closed_form_deploy_j(
        speed_mps=75.0,
        length_m=300.0,
        drag_kg_per_m=0.6,
        drivetrain_efficiency=0.95,
        gamma=objective.gamma,
        horizon_s=4.0,
        availability=0.8,
    )
    manual = 421875.0 * ((math.exp(-4.0 / 300.0) * 0.8) ** -0.75 - 1.0) / (0.95 * 75.0 / (0.6 * 300.0))
    assert expected_j == pytest.approx(manual, rel=1e-12)
    assert round(manual) == 206_825

    solution = solve_allocation(
        frame,
        (scenario("solo"),),
        weights,
        objective,
        config,
        remaining_deadline_s=5.0,
    )
    assert solution.converged, solution.solver_status
    assert solution.deploy_j[0] == pytest.approx(expected_j, rel=1e-5)
    assert solution.harvest_j[0] == pytest.approx(0.0, abs=1e-6)
    assert solution.terminal_energy_j == pytest.approx(2_400_000.0 - solution.deploy_j[0], rel=1e-15)
    assert solution.terminal_energy_j == pytest.approx(2_400_000.0 - expected_j, abs=1.0)


def test_terminal_energy_is_worth_nothing_at_the_true_finish(config, objective):
    """With no race left, stored energy has no continuation value at all.

    ``availability = 0`` makes ``v_rate`` zero, so the closed form has no
    stationary point and the allocation goes to its feasible bound. This is the
    property that stops a fixed reserve from rewarding unused energy at the flag.
    """
    estimate = solo_estimate(remaining_distance_m=0.0)
    frame = single_segment_frame(config, continuation_availability=0.0, max_deploy_j=500_000.0)
    weights = build_weights(frame, estimate, objective, config)
    assert weights.energy_value_rate == 0.0

    solution = solve_allocation(
        frame, (scenario("solo"),), weights, objective, config, remaining_deadline_s=5.0
    )
    assert solution.converged
    assert solution.deploy_j[0] == pytest.approx(500_000.0, rel=1e-6)


def test_duplicated_opponent_leaves_the_plan_unchanged(config, objective):
    """A symmetric ensemble produces the symmetric plan.

    Duplicating a scenario at half weight must not move the allocation, and the
    tail term must treat the identical pair identically: equal losses, equal
    auxiliary ``xi``.
    """
    estimate = solo_estimate()
    frame = single_segment_frame(config, continuation_availability=0.8)
    weights = build_weights(frame, estimate, objective, config)

    single = solve_allocation(
        frame, (scenario("a", weight=1.0),), weights, objective, config, remaining_deadline_s=5.0
    )
    doubled = solve_allocation(
        frame,
        (scenario("a", weight=0.5), scenario("a-copy", weight=0.5)),
        weights,
        objective,
        config,
        remaining_deadline_s=5.0,
    )
    assert single.converged and doubled.converged
    assert doubled.deploy_j[0] == pytest.approx(single.deploy_j[0], rel=1e-6)
    assert doubled.scenario_losses[0] == pytest.approx(doubled.scenario_losses[1], rel=1e-12)
    assert doubled.xi[0] == pytest.approx(doubled.xi[1], abs=1e-8)


def test_mirrored_opponents_give_a_permutation_invariant_plan(config, objective):
    """Two mirror-image hypotheses of equal weight give the same plan either way.

    The pair is symmetric about its mean in both reserve and pace bias, so no
    ordering of the ensemble may change the schedule. If it did, the CVaR
    auxiliary variables would be smuggling scenario order into the answer.
    """
    estimate = solo_estimate()
    frame = single_segment_frame(config, continuation_availability=0.8)
    weights = build_weights(frame, estimate, objective, config)

    low = scenario("low", weight=0.5, reserve_j=1_500_000.0, pace_gain_s=-0.2)
    high = scenario("high", weight=0.5, reserve_j=2_500_000.0, pace_gain_s=+0.2)

    forward = solve_allocation(frame, (low, high), weights, objective, config, remaining_deadline_s=5.0)
    reverse = solve_allocation(frame, (high, low), weights, objective, config, remaining_deadline_s=5.0)
    assert forward.converged and reverse.converged
    assert forward.deploy_j[0] == pytest.approx(reverse.deploy_j[0], rel=1e-7)
    assert forward.cvar_loss == pytest.approx(reverse.cvar_loss, rel=1e-9)
    assert forward.expected_utility == pytest.approx(reverse.expected_utility, rel=1e-9)


def test_more_energy_for_no_benefit_is_ranked_below_the_cheaper_plan(config, objective):
    """Spending past the point where it pays must score worse.

    The optimiser's answer is the point where the marginal second bought equals
    the marginal continuation value given up. Deploying more than that buys a
    strictly smaller time saving than it costs, so the expected loss and the tail
    term both rise. The test asserts the mechanism as well as the ordering: the
    extra 200 kJ buys less time than the first 200 kJ did.
    """
    estimate = solo_estimate(remaining_distance_m=16_000.0)
    frame = single_segment_frame(config, continuation_availability=0.8, max_deploy_j=900_000.0)
    weights = build_weights(frame, estimate, objective, config)
    scenarios = (scenario("solo"),)

    optimal = solve_allocation(frame, scenarios, weights, objective, config, remaining_deadline_s=5.0)
    assert optimal.converged
    best_j = optimal.deploy_j[0]

    def evaluate(deploy_j: float) -> tuple[float, float]:
        losses, time_s, _ = scenario_losses(frame, scenarios, weights, (deploy_j,), (0.0,))
        return float(losses[0]), float(time_s)

    cheap_loss, cheap_time = evaluate(best_j)
    wasteful_loss, wasteful_time = evaluate(best_j + 200_000.0)
    half_loss, half_time = evaluate(best_j - 200_000.0)

    assert wasteful_loss > cheap_loss, "spending past the optimum must rank below it"
    assert half_loss > cheap_loss, "spending less than the optimum must also rank below it"
    assert (cheap_time - wasteful_time) < (half_time - cheap_time)


def test_outcome_dominance_prefers_the_plan_that_kept_more_energy(config, objective):
    """Identical realised outcome, less energy spent, better score.

    Two re-simulated candidates that reach the same place at the same time are
    separated only by what is left in the battery, and the continuation term must
    order them the cheaper way round.
    """
    estimate = solo_estimate(remaining_distance_m=16_000.0)
    frame = single_segment_frame(config, continuation_availability=0.8)
    weights = build_weights(frame, estimate, objective, config)
    assert weights.energy_value_rate > 0.0

    def utility(final_energy_j: float) -> float:
        return (
            weights.elapsed_second_penalty * 42.0
            + weights.position_penalty * 0.0
            - weights.energy_value_rate * final_energy_j
        )

    frugal = utility(2_000_000.0)
    wasteful = utility(1_600_000.0)
    assert wasteful > frugal
    assert wasteful - frugal == pytest.approx(weights.energy_value_rate * 400_000.0, rel=1e-12)


def test_harvest_is_battery_gain_and_costs_time(config, objective):
    """``harvest_target_j`` is battery gain (D-01) and it is not free.

    Recovering energy takes a configured share of the propulsive energy off the
    wheels, so the corridor time rises with the harvest target. A model in which
    harvest were free would let the planner promise energy it never paid for.
    """
    estimate = solo_estimate()
    frame = single_segment_frame(config, max_harvest_j=200_000.0, continuation_availability=0.8)
    weights = build_weights(frame, estimate, objective, config)
    scenarios = (scenario("solo", intention=RivalIntention.NORMAL),)

    _, time_no_harvest, energy_no_harvest = scenario_losses(frame, scenarios, weights, (0.0,), (0.0,))
    _, time_harvest, energy_harvest = scenario_losses(frame, scenarios, weights, (0.0,), (200_000.0,))

    assert time_harvest > time_no_harvest
    assert energy_harvest - energy_no_harvest == pytest.approx(200_000.0, rel=1e-12)


def test_segment_profile_bounds_the_deployable_energy(config, objective):
    """A coarse profile cannot be asked for more than that profile delivers.

    ``CONSERVE`` asks for 20 % of the ceiling in the simulator's profile model,
    so a conserve instruction may not carry a budget that only ``OVERTAKE``
    could execute. Over 4.0 s at a 350 kW ceiling that is
    ``0.20 * 350 000 * 4.0 = 280 000 J``.
    """
    estimate = solo_estimate(remaining_distance_m=0.0)
    frame = single_segment_frame(
        config,
        profile=DeploymentProfile.CONSERVE,
        max_deploy_j=0.20 * 350_000.0 * 4.0,
        continuation_availability=0.0,
    )
    weights = build_weights(frame, estimate, objective, config)
    solution = solve_allocation(
        frame, (scenario("solo"),), weights, objective, config, remaining_deadline_s=5.0
    )
    assert solution.converged
    assert solution.deploy_j[0] <= 280_000.0 + 1e-6
    assert solution.deploy_j[0] == pytest.approx(280_000.0, rel=1e-6)
