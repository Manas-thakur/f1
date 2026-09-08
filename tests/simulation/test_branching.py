"""Paired branching from one snapshot.

Two branches share their exogenous disturbances by construction (keyed random
streams), but their opponents genuinely re-decide from each branch's own
observations. These tests check both halves of that claim, and that a truncated
branch records an incomplete evaluation instead of quietly comparing an earlier
checkpoint.
"""

from __future__ import annotations

import pytest
from conftest import build_bundle

from afterlap_contracts import DeploymentProfile, Provenance
from afterlap_core.simulation import (
    DriverAction,
    Simulator,
    Treatment,
    capture_complete_state,
    run_branch,
    run_paired,
    snapshot_hash,
)

DT_S = 0.02
PRE_ROLL_STEPS = 25


def _constant(profile: DeploymentProfile, **kwargs):
    def act(observation) -> DriverAction:
        del observation
        return DriverAction(profile=profile, label=profile.value, **kwargs)

    return act


def _prepared(scenario_id: str = "two-straight-counterattack", **kwargs):
    bundle = build_bundle(scenario_id, reaction_delay_s=0.10, **kwargs)
    simulator = Simulator().reset(bundle, seed=42)
    for _ in range(PRE_ROLL_STEPS):
        simulator.step(None, DT_S)
    return bundle, capture_complete_state(simulator)


def _trajectory(result) -> list[tuple]:
    cars = result.final_snapshot["cars"]
    return [
        (car_id, cars[car_id]["progress_m"], cars[car_id]["speed_mps"], cars[car_id]["battery_energy_j"])
        for car_id in sorted(cars)
    ]


class TestIdenticalBranches:
    def test_two_branches_with_the_same_actions_are_identical(self) -> None:
        bundle, snapshot = _prepared()
        treatments = (
            Treatment(id="a", controller=_constant(DeploymentProfile.PUSH)),
            Treatment(id="b", controller=_constant(DeploymentProfile.PUSH)),
        )
        results = run_paired(bundle, snapshot, treatments, horizon_s=8.0, dt_s=DT_S)
        assert _trajectory(results["a"]) == _trajectory(results["b"])
        assert results["a"].rival_actions == results["b"].rival_actions
        assert results["a"].snapshot_hash == results["b"].snapshot_hash

    def test_branching_does_not_disturb_the_parent_simulator(self) -> None:
        bundle = build_bundle(reaction_delay_s=0.10)
        parent = Simulator().reset(bundle, seed=42)
        for _ in range(PRE_ROLL_STEPS):
            parent.step(None, DT_S)
        snapshot = capture_complete_state(parent)
        before = parent.snapshot()

        run_branch(
            bundle,
            snapshot,
            Treatment(id="probe", controller=_constant(DeploymentProfile.OVERTAKE)),
            horizon_s=6.0,
            dt_s=DT_S,
        )
        assert parent.snapshot()["cars"] == before["cars"]
        assert parent.snapshot()["ledgers"] == before["ledgers"]

    def test_the_snapshot_hash_identifies_the_state_not_the_treatment(self) -> None:
        _, snapshot = _prepared()
        assert snapshot_hash(snapshot) == snapshot_hash(snapshot)
        mutated = {**snapshot, "cars": {**snapshot["cars"]}}
        mutated["cars"] = {
            car_id: {**state, "speed_mps": state["speed_mps"] + 1.0}
            for car_id, state in snapshot["cars"].items()
        }
        assert snapshot_hash(mutated) != snapshot_hash(snapshot)


class TestDivergentBranches:
    def test_different_actions_diverge_and_the_rivals_react_differently(self) -> None:
        bundle, snapshot = _prepared()
        treatments = (
            Treatment(id="attack", controller=_constant(DeploymentProfile.OVERTAKE)),
            Treatment(
                id="back-off",
                controller=_constant(DeploymentProfile.HARVEST, throttle=0.0, brake=0.3),
            ),
        )
        results = run_paired(bundle, snapshot, treatments, horizon_s=10.0, dt_s=DT_S)

        assert _trajectory(results["attack"]) != _trajectory(results["back-off"])
        attacking = results["attack"].final_snapshot["cars"]["own"]["progress_m"]
        backing_off = results["back-off"].final_snapshot["cars"]["own"]["progress_m"]
        assert attacking > backing_off + 50.0

        assert results["attack"].rival_actions != results["back-off"].rival_actions
        attack_labels = {step["actions"]["rival"]["label"] for step in results["attack"].rival_actions}
        backoff_labels = {step["actions"]["rival"]["label"] for step in results["back-off"].rival_actions}
        assert attack_labels != backoff_labels, (
            "the opponent must re-decide from its own branch observations, not replay a script"
        )

    def test_changing_deployment_changes_later_energy_and_position(self) -> None:
        bundle, snapshot = _prepared()
        results = run_paired(
            bundle,
            snapshot,
            (
                Treatment(id="spend", controller=_constant(DeploymentProfile.OVERTAKE)),
                Treatment(id="save", controller=_constant(DeploymentProfile.CONSERVE)),
            ),
            horizon_s=10.0,
            dt_s=DT_S,
        )
        spend = results["spend"].final_snapshot
        save = results["save"].final_snapshot
        assert spend["cars"]["own"]["battery_energy_j"] < save["cars"]["own"]["battery_energy_j"]
        assert spend["cars"]["own"]["progress_m"] > save["cars"]["own"]["progress_m"]


class TestOutcomeRecords:
    def test_a_reached_checkpoint_produces_a_complete_outcome(self) -> None:
        bundle, snapshot = _prepared()
        result = run_branch(
            bundle,
            snapshot,
            Treatment(id="reach", controller=_constant(DeploymentProfile.OVERTAKE)),
            horizon_s=40.0,
            dt_s=DT_S,
            checkpoint_ids=("attack-exit",),
        )
        outcome = result.outcome_by_checkpoint["attack-exit"]
        assert outcome.event_observed is True
        assert outcome.incomplete_reason is None
        assert outcome.elapsed_time_s is not None and outcome.elapsed_time_s > 0.0
        assert outcome.energy_j is not None
        assert outcome.provenance is Provenance.SIMULATED
        assert result.truncated is False
        assert result.complete_outcomes == result.outcomes

    def test_truncating_a_branch_records_an_incomplete_evaluation(self) -> None:
        bundle, snapshot = _prepared()
        treatment = Treatment(id="short", controller=_constant(DeploymentProfile.NEUTRAL))
        short = run_branch(
            bundle,
            snapshot,
            treatment,
            horizon_s=1.0,
            dt_s=DT_S,
            checkpoint_ids=("attack-exit", "counterattack-exit"),
        )
        assert short.truncated is True
        for checkpoint_id in ("attack-exit", "counterattack-exit"):
            outcome = short.outcome_by_checkpoint[checkpoint_id]
            assert outcome.event_observed is False
            assert outcome.elapsed_time_s is None
            assert outcome.energy_j is None
            assert outcome.incomplete_reason is not None
            assert "horizon" in outcome.incomplete_reason
        assert short.complete_outcomes == ()

    def test_an_incomplete_branch_is_not_silently_compared_at_an_earlier_point(self) -> None:
        """A truncated branch must not borrow the earlier checkpoint's numbers."""
        bundle, snapshot = _prepared()
        result = run_branch(
            bundle,
            snapshot,
            Treatment(id="partial", controller=_constant(DeploymentProfile.OVERTAKE)),
            horizon_s=40.0,
            dt_s=DT_S,
            checkpoint_ids=("attack-exit", "counterattack-exit"),
        )
        reached = result.outcome_by_checkpoint["attack-exit"]
        missed = result.outcome_by_checkpoint["counterattack-exit"]
        assert reached.event_observed is True
        assert missed.event_observed is False
        assert missed.elapsed_time_s is None
        assert missed.checkpoint.checkpoint_id == "counterattack-exit"
        assert missed.checkpoint.checkpoint_id != reached.checkpoint.checkpoint_id
        assert result.truncated is True

    def test_outcomes_are_wire_contract_records(self) -> None:
        bundle, snapshot = _prepared()
        result = run_branch(
            bundle,
            snapshot,
            Treatment(id="wire", controller=_constant(DeploymentProfile.PUSH)),
            horizon_s=20.0,
            dt_s=DT_S,
            checkpoint_ids=("attack-exit",),
        )
        payload = result.outcomes[0].model_dump(mode="json")
        assert payload["schema_version"] == "1.0"
        assert payload["provenance"] == "simulated"
        # No simulator truth leaks into a wire record.
        assert "cars" not in payload
        assert "world" not in payload


class TestValidation:
    def test_duplicate_treatment_ids_are_refused(self) -> None:
        bundle, snapshot = _prepared()
        treatment = Treatment(id="same", controller=_constant(DeploymentProfile.NEUTRAL))
        with pytest.raises(ValueError, match="unique"):
            run_paired(bundle, snapshot, (treatment, treatment), horizon_s=2.0, dt_s=DT_S)

    def test_a_non_positive_horizon_is_refused(self) -> None:
        bundle, snapshot = _prepared()
        treatment = Treatment(id="zero", controller=_constant(DeploymentProfile.NEUTRAL))
        with pytest.raises(ValueError):
            run_branch(bundle, snapshot, treatment, horizon_s=0.0, dt_s=DT_S)
