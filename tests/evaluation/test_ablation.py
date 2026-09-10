"""Ablation, and the difference between "no effect" and "not measured".

An ablation removes one learned contribution and re-runs the same scenarios. Its
failure mode is quiet and severe: if the removal silently does nothing -- because
the controller never used the contribution, or because it does not know how to
drop it -- the run completes and reports a difference of zero. A reader takes
that as evidence the component contributes nothing, when it is actually evidence
that nothing was ablated.

Every test here is about keeping those two outcomes distinguishable.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import DeploymentProfile, PlanningStatus, ReasonCode
from afterlap_core.evaluation.controllers import (
    AblatedController,
    AblationUnsupported,
    ControlDecision,
    ControlRequest,
    LegalFixedSchedule,
    ScheduleEntry,
)
from afterlap_core.evaluation.harness import (
    ABLATION_TARGETS,
    load_benchmark_manifest,
    paired_sample_from_run,
    run_ablation,
    run_benchmark,
)


class _Learned:
    """A stand-in that records which contributions it was asked to drop.

    Not a learned controller: it exists so the ablation plumbing can be tested
    without a trained bundle, and it never claims otherwise.
    """

    def __init__(self, *, actor: bool = True, learned_return: bool = True, name: str = "stub") -> None:
        self._actor = actor
        self._learned_return = learned_return
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def uses_actor(self) -> bool:
        return self._actor

    @property
    def uses_learned_return(self) -> bool:
        return self._learned_return

    def without_contribution(self, target: str) -> _Learned:
        if target == "policy":
            return _Learned(actor=False, learned_return=self._learned_return, name=self._name)
        if target == "terminal":
            return _Learned(actor=self._actor, learned_return=False, name=self._name)
        if target == "none":
            return self
        raise AblationUnsupported(f"cannot drop {target!r}")

    def decide(self, request: ControlRequest) -> ControlDecision:
        del request
        return ControlDecision(
            controller=self._name,
            status=PlanningStatus.OK,
            action=DeploymentProfile.NEUTRAL,
            provenance=f"actor={self._actor},value={self._learned_return}",
        )


class _NoAblationSupport:
    """A controller with no ``without_contribution``. The common real case."""

    name = "no_support"
    uses_actor = True
    uses_learned_return = False

    def decide(self, request: ControlRequest) -> ControlDecision:
        del request
        return ControlDecision(
            controller=self.name, status=PlanningStatus.OK, action=DeploymentProfile.NEUTRAL
        )


def _request() -> ControlRequest:
    return ControlRequest.__new__(ControlRequest)


class TestAblatedControllerNaming:
    def test_the_removal_is_named_on_the_controller(self) -> None:
        wrapped = AblatedController(_Learned(), disable="policy")
        assert wrapped.name == "stub+ablate_policy"

    def test_dropping_the_actor_clears_only_the_actor_flag(self) -> None:
        wrapped = AblatedController(_Learned(), disable="policy")
        assert wrapped.uses_actor is False
        assert wrapped.uses_learned_return is True

    def test_dropping_the_terminal_term_clears_only_that_flag(self) -> None:
        wrapped = AblatedController(_Learned(), disable="terminal")
        assert wrapped.uses_actor is True
        assert wrapped.uses_learned_return is False

    def test_the_delegated_decision_is_stamped_as_learned_disabled(self) -> None:
        wrapped = AblatedController(_Learned(), disable="policy")
        decision = wrapped.decide(_request())
        assert ReasonCode.LEARNED_MODEL_DISABLED in decision.reasons
        assert decision.provenance.startswith("ablated:policy:")
        assert "actor=False" in decision.provenance


class TestAnUnablatableControllerIsUnmeasuredNotUnchanged:
    def test_a_controller_that_cannot_drop_the_contribution_returns_unavailable(self) -> None:
        """The defect this guards: a zero difference read as "no effect"."""
        wrapped = AblatedController(_NoAblationSupport(), disable="policy")
        decision = wrapped.decide(_request())
        assert decision.status is PlanningStatus.SOLVER_UNAVAILABLE
        assert decision.action is None
        assert decision.provenance == "ablation_unsupported"
        assert "does not implement without_contribution" in decision.detail

    def test_a_refused_target_is_recorded_with_its_reason(self) -> None:
        wrapped = AblatedController(_Learned(), disable="unknown-target")
        decision = wrapped.decide(_request())
        assert decision.status is PlanningStatus.SOLVER_UNAVAILABLE
        assert "refused the 'unknown-target' ablation" in decision.detail


@pytest.fixture(scope="module")
def manifest():
    return load_benchmark_manifest("commissioning-smoke")


class TestRunAblation:
    def test_an_unknown_target_is_refused_before_anything_runs(self, manifest) -> None:
        with pytest.raises(ValueError, match="unknown ablation target"):
            run_ablation(manifest, [LegalFixedSchedule()], disable="everything")

    def test_every_declared_target_has_a_description(self) -> None:
        assert set(ABLATION_TARGETS) == {"none", "policy", "terminal"}
        assert all(ABLATION_TARGETS.values())

    def test_ablating_a_contribution_no_controller_uses_is_unmeasured(self, manifest) -> None:
        """Baselines use no learned contribution, so there is nothing to remove."""
        run = run_ablation(
            manifest,
            [LegalFixedSchedule(entries=[ScheduleEntry(0.0, DeploymentProfile.NEUTRAL)])],
            disable="policy",
        )
        assert run.unavailable_controllers
        assert all(not outcome.measured for outcome in run.outcomes)
        detail = " ".join(str(outcome.detail) for outcome in run.outcomes)
        assert "no supplied controller uses the 'policy' contribution" in detail
        assert "unmeasured rather than a null result" in detail

    def test_the_rerun_command_names_the_ablation(self, manifest) -> None:
        run = run_ablation(manifest, [LegalFixedSchedule()], disable="policy")
        assert run.rerun_command is not None
        assert "--disable policy" in run.rerun_command


@pytest.fixture(scope="module")
def run(manifest):
    """One benchmark run with a merged baseline and every unmerged row."""
    from afterlap_core.evaluation.controllers import unavailable_matrix_controllers

    return run_benchmark(
        manifest,
        [LegalFixedSchedule(name="legal_fixed_schedule"), *unavailable_matrix_controllers()],
    )


class TestPairedSampleFromRun:
    def test_one_unit_per_scenario_and_seed(self, run) -> None:
        sample = paired_sample_from_run(run)
        keys = [unit.key for unit in sample.units]
        assert len(keys) == len(set(keys))
        expected = {(scenario, seed) for scenario in run.manifest.scenario_ids for seed in run.manifest.seeds}
        assert set(keys) == expected

    def test_a_controller_that_produced_nothing_stays_visible_as_missing(self, run) -> None:
        """A dropped row would quietly improve the mean it is absent from."""
        sample = paired_sample_from_run(run)
        assert sample.units
        for unit in sample.units:
            assert "mpc_only" in unit.missing
            assert "mpc_only" not in unit.values

    def test_the_metric_is_the_frozen_objective_utility(self, run) -> None:
        from afterlap_core.evaluation.harness import load_objective, objective_utility

        sample = paired_sample_from_run(run)
        objective = load_objective()
        measured = next(o for o in run.outcomes if o.measured)
        unit = next(u for u in sample.units if u.key == (measured.scenario_id, measured.seed))
        assert unit.values[measured.controller] == pytest.approx(objective_utility(measured, objective))
        assert sample.metric.metric == "utility"
        assert sample.metric.higher_is_better is True
