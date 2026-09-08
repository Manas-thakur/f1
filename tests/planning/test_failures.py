"""Failure handling: missing inputs, unknown permission, deadlines and pack changes.

Every case here has to produce a *typed, published* failure. Silence is not an
acceptable outcome and neither is a downgraded instruction that an engineer would
read as the planner's considered advice.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from afterlap_contracts import (
    ActionCode,
    DeploymentProfile,
    EligibilityState,
    PlanningStatus,
    ReasonCode,
)
from afterlap_core.estimation import RivalParticleFilter, load_rival_config, sample_scenarios
from afterlap_core.planning import (
    ActivePlan,
    RivalScenarioView,
    ScenarioEnsembleView,
    build_recommendation,
    load_planner_config,
    optimiser as optimiser_module,
    plan,
    scenarios_from_estimate,
    scenarios_from_views,
)
from afterlap_core.planning.optimiser import SolverUnavailable

from .conftest import (
    context_with,
    estimate_with,
    interval_only_estimate,
    no_energy_capability_estimate,
    wide_energy_estimate,
)


def test_missing_battery_state_suppresses_precise_energy_advice(context, manifest, config):
    """No observable battery energy means no energy advice at all.

    Both gates are exercised: the estimate's ``own_energy_capability`` is false
    and ``battery_energy_j.value`` is ``None``. The planner reports
    ``input_unavailable`` with ``own_energy_unavailable`` and withdraws, rather
    than substituting the midpoint of the physical bounds and advising joules it
    cannot see.
    """
    estimate = no_energy_capability_estimate()
    assert estimate.own_car.battery_energy_j.value is None
    assert estimate.own_car.battery_energy_interval is not None

    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    assert result.status is PlanningStatus.INPUT_UNAVAILABLE
    assert ReasonCode.OWN_ENERGY_UNAVAILABLE in result.reason_codes
    assert result.accepted == ()
    assert result.selected_plan_id is None

    recommendation = build_recommendation(result, estimate, context, config=config)
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    assert ReasonCode.OWN_ENERGY_UNAVAILABLE in recommendation.reason_codes


def test_session_level_capability_flag_alone_suppresses_advice(context, manifest, config):
    """A false ``own_energy_capability`` closes the gate even with a value present.

    The session-level declaration is authoritative: A05 sets it when the energy
    channel cannot be trusted, and a stale-but-present number must not reopen
    precise energy advice.
    """
    base = estimate_with()
    quality = base.quality.model_copy(update={"own_energy_capability": False})
    estimate = base.model_copy(update={"quality": quality})
    assert estimate.own_car.battery_energy_j.value is not None

    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    assert result.status is PlanningStatus.INPUT_UNAVAILABLE
    assert ReasonCode.OWN_ENERGY_UNAVAILABLE in result.reason_codes


def test_unknown_overtake_eligibility_removes_the_attack_candidate(manifest, config):
    """Unknown permission is not permission.

    With the Overtake profile absent from the admissible set the attack intention
    is suppressed with ``eligibility_unknown`` before optimisation, and no attack
    plan exists anywhere in the result. The other intentions still plan normally,
    so this is a targeted suppression and not a blanket refusal.
    """
    estimate = estimate_with()
    context = context_with(eligibility=EligibilityState.UNKNOWN)
    assert DeploymentProfile.OVERTAKE not in context.admissible_profiles

    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    considered = list(result.accepted) + list(result.rejected)
    assert considered, "the non-overtake intentions should still be planned"
    assert ActionCode.ATTACK not in {candidate.intention for candidate in considered}
    assert ReasonCode.ELIGIBILITY_UNKNOWN in result.reason_codes


def test_deadline_expiry_withdraws_advice_instead_of_answering_late(estimate, context, manifest, config):
    """A late plan is not published.

    With a microsecond of budget the planner abandons the solve, returns
    ``deadline_exceeded`` with ``solver_timeout``, publishes nothing, and the
    recommendation is an explicit withdrawal.
    """
    result = plan(estimate, context, None, 1.0e-6, manifest=manifest, config=config)
    assert result.status is PlanningStatus.DEADLINE_EXCEEDED
    assert ReasonCode.SOLVER_TIMEOUT in result.reason_codes
    assert result.accepted == ()
    assert result.selected_plan_id is None
    assert "decision budget expired" in (result.detail or "")

    recommendation = build_recommendation(result, estimate, context, config=config)
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE


def test_deadline_expiry_keeps_a_still_valid_current_plan(estimate, context, manifest, config):
    """On expiry a revalidated instruction in force is kept, not replaced.

    ``build_recommendation`` returns ``None`` to mean "keep what you have". The
    instruction only survives while its ruleset hash still matches and it has not
    expired; both are rechecked here rather than assumed.
    """
    current = ActivePlan(
        plan_id="plan-maintain-r4",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=estimate.created_at_s - 1.0,
        expires_at_s=estimate.created_at_s + 5.0,
        ruleset_hash=context.ruleset_hash,
        final_score=0.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    result = plan(estimate, context, None, 1.0e-6, manifest=manifest, config=config)
    assert result.status is PlanningStatus.DEADLINE_EXCEEDED
    assert build_recommendation(result, estimate, context, config=config, current_plan=current) is None

    stale = replace(current, ruleset_hash="sha256:some-other-pack")
    withdrawn = build_recommendation(result, estimate, context, config=config, current_plan=stale)
    assert withdrawn is not None
    assert withdrawn.action_code is ActionCode.WITHDRAW_ADVICE

    expired = replace(current, expires_at_s=estimate.created_at_s - 0.1)
    lapsed = build_recommendation(result, estimate, context, config=config, current_plan=expired)
    assert lapsed is not None
    assert lapsed.action_code is ActionCode.WITHDRAW_ADVICE


def test_unobserved_rival_reserve_widens_the_scenarios(config, manifest):
    """Less information about a rival produces a wider ensemble, never a point.

    Three beliefs of decreasing information, each strictly wider than the last:

    * mean 2.6 MJ with a 480 kJ standard deviation;
    * the same 90 %-labelled quantile interval with the mean removed, which is
      additionally widened because A05 measures its coverage at 0.7885;
    * nothing at all, which spans the declared 0-4 MJ physical window and carries
      ``rival_energy_unknown``.

    In no case is the reserve collapsed to a single value, and in no case is it
    replaced by zero.
    """
    known = scenarios_from_estimate(estimate_with(), config, battery_max_j=manifest.battery_energy_max_j)
    interval = scenarios_from_estimate(
        interval_only_estimate(), config, battery_max_j=manifest.battery_energy_max_j
    )
    unknown = scenarios_from_estimate(
        wide_energy_estimate(), config, battery_max_j=manifest.battery_energy_max_j
    )

    assert known.energy_spread_j < interval.energy_spread_j < unknown.energy_spread_j
    for sample in (known, interval, unknown):
        reserves = {s.rival_reserve_j for s in sample.scenarios}
        assert len(reserves) > 1, "an uncertain reserve is never a point value"
        assert all(value >= 0.0 for value in reserves)

    assert ReasonCode.RIVAL_ENERGY_UNKNOWN not in known.reason_codes
    assert ReasonCode.RIVAL_ENERGY_UNKNOWN in unknown.reason_codes
    assert all(s.energy_known for s in known.scenarios)
    assert not any(s.energy_known for s in unknown.scenarios)

    assert "widened" in interval.energy_support
    assert "not identified" in unknown.energy_support


def test_the_widened_interval_is_not_presented_as_a_calibrated_bound(config, manifest):
    """A nominal 90 % interval is widened, and its provenance stays visible.

    ``handoffs/A05.md`` measures 0.7885 empirical coverage against that label and
    attributes the shortfall to bias rather than spread. The widening is a
    conservative margin only; the recorded support string says the interval was
    widened so that no consumer can read the ensemble as calibrated.
    """
    widening = float(config.scenarios.interval_coverage_widening.value)
    assert widening > 1.0

    sample = scenarios_from_estimate(
        interval_only_estimate(), config, battery_max_j=manifest.battery_energy_max_j
    )
    reserves = sorted({s.rival_reserve_j for s in sample.scenarios})
    assert reserves[0] == pytest.approx(1_860_800.0, rel=1e-9)
    assert reserves[-1] == pytest.approx(3_339_200.0, rel=1e-9)
    assert "quantile" in sample.energy_support
    assert "0.90" in sample.energy_support


def test_a_rule_pack_change_invalidates_an_outstanding_plan(manifest, config, world):
    """A different ruleset hash replaces the instruction immediately.

    The dwell has not elapsed and the improvement would not clear the threshold,
    so only the invalidation can be responsible for the switch.
    """
    estimate = estimate_with()
    context = context_with(ruleset_hash="sha256:pack-v2")
    outstanding = ActivePlan(
        plan_id="plan-maintain-r4",
        action_code=ActionCode.MAINTAIN,
        selected_at_s=estimate.created_at_s - 0.2,
        expires_at_s=estimate.created_at_s + 60.0,
        ruleset_hash="sha256:pack-v1",
        final_score=0.0,
        head_profile=DeploymentProfile.NEUTRAL,
    )
    unchanged = plan(
        estimate,
        context_with(ruleset_hash="sha256:pack-v1"),
        None,
        5.0,
        manifest=manifest,
        config=config,
        world=world,
        current_plan=outstanding,
    )
    assert "invalidation" not in (unchanged.detail or "")

    invalidated = plan(
        estimate,
        context,
        None,
        5.0,
        manifest=manifest,
        config=config,
        world=world,
        current_plan=outstanding,
    )
    assert invalidated.status is PlanningStatus.OK
    assert "ruleset_changed" in (invalidated.detail or "")


def test_a_stale_estimate_suppresses_advice(estimate, context, manifest, config):
    """Freshness is evaluated at selection, not only at publication."""
    late_s = estimate.cutoff_s + float(config.budgets.estimate_max_age_s.value) + 0.5
    result = plan(
        estimate, context, None, 5.0, manifest=manifest, config=config, now_s=late_s, rollout_enabled=False
    )
    assert result.status is PlanningStatus.INPUT_UNAVAILABLE
    assert ReasonCode.STALE_OBSERVATIONS in result.reason_codes


def test_an_unavailable_solver_is_reported_and_not_substituted(
    estimate, context, manifest, config, monkeypatch
):
    """Without CasADi the planner says so; it never falls back to a heuristic."""

    def _missing() -> None:
        raise SolverUnavailable("casadi is not importable: simulated absence")

    monkeypatch.setattr(optimiser_module, "_casadi", _missing)
    result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, rollout_enabled=False)
    assert result.status is PlanningStatus.SOLVER_UNAVAILABLE
    assert result.accepted == ()
    assert "solver is unavailable" in (result.detail or "")


def test_the_estimation_ensemble_satisfies_the_planner_scenario_protocol():
    """A05's ``sample_scenarios`` output plugs into the planner unchanged.

    The planner does not import the estimation module on its decision path; it
    consumes a structural protocol. This test is the contract between the two:
    if A05's trajectory shape changes, it fails here rather than at runtime.
    """
    belief = RivalParticleFilter(load_rival_config("rival-modes-v1"), car_id="car-07", seed=11)
    ensemble = sample_scenarios(belief, 4, 5, horizon_s=6.0, step_s=0.5)

    assert isinstance(ensemble, ScenarioEnsembleView)
    assert all(isinstance(trajectory, RivalScenarioView) for trajectory in ensemble.trajectories)

    sample = scenarios_from_views(ensemble.trajectories, load_planner_config())
    assert sample.count == 4
    assert sum(sample.weights) == pytest.approx(1.0)
    assert all(s.rival_reserve_j >= 0.0 for s in sample.scenarios)
    assert "sampler's to disclose" in sample.energy_support
