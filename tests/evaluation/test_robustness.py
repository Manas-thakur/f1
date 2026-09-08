"""The robustness sweep and its one hard invariant.

Every dimension the spec names for this module must produce a labelled result,
and no unknown critical condition may end in a confident active directive. The
last test in the file falsifies the invariant against a deliberately broken
controller, so that "the invariant held" is a measurement rather than a
tautology.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import DeploymentProfile, PlanningStatus, Quality, ReasonCode
from afterlap_core.evaluation.controllers import (
    ControlDecision,
    ControlRequest,
    LegalFixedSchedule,
    LegalGreedyAttacker,
    ScheduleEntry,
    assert_no_truth_access,
    build_request,
)
from afterlap_core.evaluation.harness import controller_rule_context
from afterlap_core.evaluation.robustness import (
    OPERATIONS_OWNED_DIMENSIONS,
    RobustnessDimension,
    RobustnessOutcome,
    assert_no_confident_directive_under_unknown,
    run_robustness_sweep,
)
from afterlap_core.rules import load_rule_pack
from afterlap_core.simulation import Simulator


@pytest.fixture(scope="module")
def sweep() -> tuple[RobustnessOutcome, ...]:
    return run_robustness_sweep()


class TestSweepCoverage:
    def test_every_dimension_produces_a_labelled_result(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        covered = {outcome.dimension for outcome in sweep}
        assert covered == set(RobustnessDimension), sorted(
            d.value for d in set(RobustnessDimension) - covered
        )
        for outcome in sweep:
            assert outcome.label, f"{outcome.dimension} produced an unlabelled result"
            assert outcome.perturbation, f"{outcome.dimension} did not say what it perturbed"
            assert outcome.status in {"held", "violated", "unmeasured"}
            assert outcome.evidence, f"{outcome.dimension}:{outcome.label} carries no evidence"

    def test_no_dimension_reports_a_violation(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        violations = [o for o in sweep if o.status == "violated"]
        assert not violations, [f"{o.dimension.value}:{o.label}" for o in violations]

    def test_the_operations_owned_dimensions_are_named_as_out_of_scope(self) -> None:
        """DB outage and worker crash are A14's; they are not silently omitted."""
        assert OPERATIONS_OWNED_DIMENSIONS == ("db_outage", "worker_crash")
        owned = {d.value for d in RobustnessDimension}
        assert not owned & set(OPERATIONS_OWNED_DIMENSIONS)


class TestUnknownCriticalConditions:
    def test_no_confident_active_directive_under_an_unknown(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        assert_no_confident_directive_under_unknown(sweep)
        for outcome in sweep:
            if outcome.critical_condition_unknown:
                assert outcome.confident_active_directives == 0, (
                    f"{outcome.dimension.value}:{outcome.label} issued "
                    f"{outcome.confident_active_directives} confident active directives"
                )

    def test_the_unknown_cases_are_actually_exercised(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        """The invariant would be vacuous if nothing raised an unknown."""
        unknown = [o for o in sweep if o.critical_condition_unknown]
        assert len(unknown) >= 6
        assert all(o.decisions > 0 for o in unknown)

    def test_stale_data_withdraws_every_decision(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.DATA_AGE)
        assert outcome.decisions > 0
        assert outcome.withdrawn_decisions == outcome.decisions
        assert outcome.active_directives == 0

    def test_missing_rules_withdraw_advice(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.MISSING_RULES)
        assert outcome.withdrawn_decisions == outcome.decisions
        assert "rules_unknown" in outcome.evidence["statuses"]

    def test_a_dropped_energy_channel_suppresses_energy_advice(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.DROPPED_ENERGY_CHANNEL)
        assert "own_energy_unavailable" in outcome.evidence["capability_gaps"]
        assert outcome.active_directives == 0
        assert DeploymentProfile.OVERTAKE.value not in outcome.evidence["profiles"]

    def test_a_solver_timeout_ignores_the_late_result(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.SOLVER_TIMEOUT)
        assert outcome.withdrawn_decisions == outcome.decisions
        assert outcome.evidence["statuses"] == ["deadline_exceeded"]

    def test_a_model_hash_mismatch_falls_back_with_a_visible_identity(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.MODEL_HASH_MISMATCH)
        assert outcome.confident_active_directives == 0
        assert any(p.startswith("baseline_fallback:") for p in outcome.evidence["provenance"])
        assert "learned_model_disabled" in outcome.evidence["reasons"]

    def test_an_unavailable_temperature_makes_the_derate_unknown(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(
            o
            for o in sweep
            if o.dimension is RobustnessDimension.THERMAL_DERATING and o.label == "temperature_unavailable"
        )
        assert outcome.critical_condition_unknown
        assert outcome.withdrawn_decisions == outcome.decisions


class TestObservableEffects:
    def test_a_changed_rival_response_changes_the_outcome(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.CHANGED_RIVAL_RESPONSE)
        assert outcome.evidence["spread_m"] > 1.0
        assert len(set(outcome.evidence["rival_progress_m"].values())) == 3

    def test_a_delayed_driver_action_changes_the_realised_energy(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.DELAYED_DRIVER_ACTION)
        assert abs(outcome.evidence["difference_j"]) > 1000.0

    def test_the_energy_floor_is_respected_from_a_low_start(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.LOW_INITIAL_ENERGY)
        assert outcome.evidence["floor_respected"] is True

    def test_thermal_derating_lowers_the_ceiling(self, sweep: tuple[RobustnessOutcome, ...]) -> None:
        outcome = next(
            o
            for o in sweep
            if o.dimension is RobustnessDimension.THERMAL_DERATING and o.label == "derate_active"
        )
        assert outcome.evidence["derated_ceiling_w"] < outcome.evidence["ceiling_before_derate_w"]

    def test_line_crossings_agree_with_the_independent_reference(
        self, sweep: tuple[RobustnessOutcome, ...]
    ) -> None:
        outcome = next(o for o in sweep if o.dimension is RobustnessDimension.LINE_BOUNDARY_TIMING)
        assert outcome.evidence["dt=0.02"]["reference_crossings"] > 0
        assert (
            outcome.evidence["dt=0.02"]["reference_crossings"]
            == outcome.evidence["dt=0.02"]["recorded_crossings"]
        )
        assert outcome.evidence["worst_difference_s"] < 1.0e-8


class TestInvariantHasTeeth:
    """Falsify the invariant against a controller that breaks it deliberately."""

    def test_a_reckless_controller_is_caught(self) -> None:
        reckless = RobustnessOutcome(
            dimension=RobustnessDimension.MISSING_RULES,
            label="reckless_controller",
            status="violated",
            perturbation="a controller that answers confidently under an unresolved rule",
            critical_condition_unknown=True,
            decisions=10,
            active_directives=10,
            confident_active_directives=10,
        )
        with pytest.raises(AssertionError, match="confident active directive"):
            assert_no_confident_directive_under_unknown([reckless])

    def test_a_confident_active_directive_is_precisely_defined(self) -> None:
        from afterlap_core.simulation.policies import DriverAction

        confident = ControlDecision(
            controller="x",
            status=PlanningStatus.OK,
            action=DriverAction(profile=DeploymentProfile.OVERTAKE),
        )
        assert confident.is_confident_active_directive

        qualified = ControlDecision(
            controller="x",
            status=PlanningStatus.OK,
            action=DriverAction(profile=DeploymentProfile.OVERTAKE),
            reasons=(ReasonCode.OWN_ENERGY_UNAVAILABLE,),
        )
        assert qualified.is_active_directive
        assert not qualified.is_confident
        assert not qualified.is_confident_active_directive

        passive = ControlDecision(
            controller="x",
            status=PlanningStatus.OK,
            action=DriverAction(profile=DeploymentProfile.NEUTRAL),
        )
        assert not passive.is_active_directive

        withdrawn = ControlDecision(controller="x", status=PlanningStatus.RULES_UNKNOWN, action=None)
        assert withdrawn.withdrawn
        assert not withdrawn.is_confident_active_directive


class TestEqualObservationAccess:
    def test_the_control_request_exposes_no_simulator_truth(self) -> None:
        assert_no_truth_access()

    def test_every_controller_receives_the_identical_request(self) -> None:
        """Equal access is structural: one request object, several controllers."""
        from afterlap_core.simulation import load_bundle

        bundle = load_bundle("two-straight-counterattack")
        pack = load_rule_pack("synthetic-pack-v1")
        simulator = Simulator()
        simulator.reset(bundle)
        for _ in range(60):
            simulator.step(None, 0.02)
        ego = bundle.scenario.ego_car_id
        observation = simulator.observe(car_id=ego)[ego]
        context, _gaps = controller_rule_context(observation, pack, session_id="equal-access")
        request = build_request(
            car_id=ego,
            session_time_s=simulator.session_time_s,
            observation=observation,
            rule_context=context,
            compute_budget_ms=200.0,
            disturbance_keys=("wind", "grip", "sensor_noise", "driver_response"),
        )
        controllers = [
            LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.PUSH),)),
            LegalGreedyAttacker(),
        ]
        decisions = [controller.decide(request) for controller in controllers]
        assert all(isinstance(decision, ControlDecision) for decision in decisions)
        # The request is frozen, so no controller could have mutated it for the next.
        assert isinstance(request, ControlRequest)
        with pytest.raises((AttributeError, TypeError)):
            request.compute_budget_ms = 1.0  # type: ignore[misc]

    def test_a_missing_observation_is_absent_not_zero(self) -> None:
        from afterlap_core.simulation import load_bundle

        bundle = load_bundle("loop-no-energy-channel")
        simulator = Simulator()
        simulator.reset(bundle)
        for _ in range(30):
            simulator.step(None, 0.02)
        ego = bundle.scenario.ego_car_id
        observation = simulator.observe(car_id=ego)[ego]
        assert observation.quality is Quality.VALID
        assert not observation.has("battery_energy_j")
        with pytest.raises(KeyError, match="absent, never zero"):
            observation.get("battery_energy_j")
