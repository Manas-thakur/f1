"""The closed loop that exists today, end to end across module boundaries.

    scenario -> simulator step -> observation -> rules context -> checked plan
    -> recorded outcome

A03 (simulation), A04 (rules), A06 (planning) and A13 (evaluation) are merged,
so the slice runs three of the comparison matrix's six rows: a legal fixed
schedule, a legal greedy attacker and A06's MPC-only planner, each filtered
through the rule context and independently re-checked. The learned rows are not
part of this slice and the tests say so rather than standing in for them.

Two properties are the point of the file:

* the controller never sees rival truth, and mutating that truth changes nothing
  it can observe or decide;
* changing the deployment changes later energy and position — a different
  instruction must move the car, not only the text on a screen.
"""

from __future__ import annotations

import json

import pytest

from afterlap_contracts import (
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    PlanningStatus,
    ReasonCode,
    fixtures,
)
from afterlap_core.evaluation.controllers import (
    COMPARISON_MATRIX,
    LegalFixedSchedule,
    LegalGreedyAttacker,
    ScheduleEntry,
)
from afterlap_core.evaluation.independent_ledger import (
    ProgressSample,
    find_crossings,
    reconstruct,
    record_trajectory,
)
from afterlap_core.rules import CheckerState, SpeedProfile, SpeedSample, check_plan
from afterlap_core.simulation import Simulator
from afterlap_core.simulation.observation import debug_truth, observe

from .conftest import DT_S, run_slice

HORIZON_S = 20.0


@pytest.fixture(scope="module")
def conserve_controller() -> LegalFixedSchedule:
    return LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.HARVEST),), name="fixed_conserve")


@pytest.fixture(scope="module")
def push_controller() -> LegalFixedSchedule:
    return LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.PUSH),), name="fixed_push")


MPC_ELIGIBILITY = EligibilityState.ELIGIBLE_DETECTED
"""Declared, not derived: this slice has no detection-line machine, and an attack
candidate is inadmissible without overtake permission. Every controller compared
against the planner receives the same declared value."""

MPC_BUDGET_MS = 60_000.0
"""A deliberately enormous planning allowance for a *functional* test.

A06's planner needs 135-170 ms per decision when this file runs on its own, and
0.8-2.5 s per decision once the whole evaluation suite has run first in the same
process. Against the 200 ms runtime target it therefore withdraws under load,
correctly: a late plan is not published. Holding these functional tests to a
realistic budget would make them measure the test machine's load rather than the
loop, so the allowance is stated and made ample here, and the deadline behaviour
is tested deliberately in ``test_a_budget_it_cannot_meet_withdraws_the_advice``.

The 200 ms figure remains A06's and A14's to measure on declared, quiet
hardware. Nothing in this file promises it, and the spread above is reported in
``handoffs/A13.md`` as an observation about this machine, not about the
planner."""


@pytest.fixture(scope="module")
def mpc_trace(bundle, rule_pack):
    from .conftest import MpcController

    controller = MpcController(rule_pack, bundle)
    trace = run_slice(
        bundle,
        rule_pack,
        controller,
        horizon_s=12.0,
        seed=42,
        eligibility=MPC_ELIGIBILITY,
        compute_budget_ms=MPC_BUDGET_MS,
    )
    return trace, controller


@pytest.fixture(scope="module")
def conserve_trace(bundle, rule_pack, conserve_controller):
    return run_slice(bundle, rule_pack, conserve_controller, horizon_s=HORIZON_S, seed=42)


@pytest.fixture(scope="module")
def push_trace(bundle, rule_pack, push_controller):
    return run_slice(bundle, rule_pack, push_controller, horizon_s=HORIZON_S, seed=42)


class TestTheLoopCloses:
    def test_the_loop_produces_decisions_and_an_outcome(self, conserve_trace) -> None:
        assert len(conserve_trace.decisions) == int(HORIZON_S)
        assert conserve_trace.final_progress_m > 0.0
        assert conserve_trace.final_position >= 1
        assert conserve_trace.rival_actions, "the rival must have decided for itself"

    def test_every_issued_profile_was_admissible_at_the_time(self, conserve_trace) -> None:
        """The rules module gated the plan; no instruction escaped the context."""
        checked = 0
        for decision, context in zip(conserve_trace.decisions, conserve_trace.contexts, strict=True):
            if decision.action is None or context is None:
                continue
            assert decision.action.profile in context.admissible_profiles
            checked += 1
        assert checked >= int(HORIZON_S) - 2

    def test_the_first_tick_withdraws_because_nothing_is_old_enough_yet(self, conserve_trace) -> None:
        """A real operational state, reported as missing rather than filled in."""
        first = conserve_trace.decisions[0]
        assert first.withdrawn
        assert first.status is PlanningStatus.INPUT_UNAVAILABLE

    def test_the_independent_checker_agrees_the_issued_plan_is_legal(
        self, bundle, rule_pack, conserve_trace
    ) -> None:
        """A04's checker re-derives the plan rather than trusting the controller.

        The plan carries the profile the controller actually issued and is
        checked against the very rule context the slice resolved at that tick,
        so the verdict is about this run and not about a fixture.
        """
        index, issued = next((i, d) for i, d in enumerate(conserve_trace.decisions) if d.action is not None)
        context = conserve_trace.contexts[index]
        assert context is not None

        template = fixtures.candidate_plan()
        segment = template.profile_segments[0].model_copy(
            update={
                "profile_id": issued.action.profile,
                "start_progress_m": 200.0,
                "end_progress_m": 1_500.0,
                "requested_budget_j": 0.0,
                "harvest_target_j": 100_000.0,
            }
        )
        plan = template.model_copy(
            update={
                "id": "acceptance-slice-plan",
                "profile_segments": (segment,),
                "constraint_result": fixtures.constraint_result(),
            }
        )
        state = CheckerState(
            session_time_s=context.resolved_at_s,
            progress_m=0.0,
            battery_energy_j=2.4e6,
            speed_profile=SpeedProfile(samples=(SpeedSample(0.0, 70.0), SpeedSample(2_000.0, 80.0))),
            track_length_m=bundle.track.length,
            charge_bus_efficiency=0.94,
            discharge_efficiency=0.95,
        )
        result = check_plan(plan, state, context, manifest=rule_pack.manifest)
        assert result.status is not CheckStatus.FAIL, [
            (check.check_id, check.detail) for check in result.checks if check.status is CheckStatus.FAIL
        ]
        assert result.checker_version
        assert result.ruleset_hash == context.ruleset_hash


class TestObservationIsolation:
    def test_the_observation_never_carries_rival_truth(self, conserve_trace) -> None:
        for payload in conserve_trace.observations:
            for rival in payload["rivals"]:
                assert "battery_energy_j" not in rival
                assert "battery_temperature_k" not in rival
                assert "recharge_cumulative_j" not in rival
            text = json.dumps(payload)
            assert "recharge_ledger" not in text

    def test_mutating_hidden_rival_truth_changes_no_observation_byte(
        self, bundle, rule_pack, conserve_controller
    ) -> None:
        ego = bundle.scenario.ego_car_id
        rival = bundle.scenario.rival_ids[0]

        def prepared() -> Simulator:
            simulator = Simulator()
            simulator.reset(bundle, seed=42)
            for _ in range(120):
                simulator.step(None, DT_S)
            return simulator

        baseline = prepared()
        mutated = prepared()
        world = mutated.world
        world.cars[rival].battery_energy_j = 3.99e6
        world.cars[rival].battery_temperature_k = 355.0
        world.cars[rival].recharge_ledger_j = 9.9e6
        world.ledgers[rival].energy_j = 3.99e6
        for sample in world.sensor_buffer:
            sample.cars[rival]["battery_energy_j"] = 3.99e6
            sample.cars[rival]["battery_temperature_k"] = 355.0
            sample.cars[rival]["recharge_cumulative_j"] = 9.9e6

        config = baseline.sensor_config
        before = observe(baseline.world, config, ego)[ego].canonical_bytes()
        after = observe(mutated.world, config, ego)[ego].canonical_bytes()
        assert before == after

        mutated.world.cars[ego].speed_mps += 5.0
        for sample in mutated.world.sensor_buffer:
            sample.cars[ego]["speed_mps"] += 5.0
        assert observe(mutated.world, config, ego)[ego].canonical_bytes() != before

        assert debug_truth(mutated.world)["cars"][rival]["battery_energy_j"] == 3.99e6
        assert debug_truth(baseline.world)["cars"][rival]["battery_energy_j"] != 3.99e6

    def test_the_controller_decides_identically_under_mutated_rival_truth(
        self, bundle, rule_pack, conserve_controller
    ) -> None:
        rival = bundle.scenario.rival_ids[0]

        plain = Simulator()
        plain.reset(bundle, seed=42)
        secret = Simulator()
        secret.reset(bundle, seed=42)
        secret.world.cars[rival].battery_energy_j = 0.0
        secret.world.ledgers[rival].energy_j = 0.0

        first = run_slice(bundle, rule_pack, conserve_controller, horizon_s=6.0, simulator=plain)
        second = run_slice(bundle, rule_pack, conserve_controller, horizon_s=6.0, simulator=secret)
        assert [d.action for d in first.decisions] == [d.action for d in second.decisions]


class TestDeploymentChangesThePhysics:
    def test_a_different_deployment_changes_later_energy_and_position(
        self, conserve_trace, push_trace
    ) -> None:
        assert push_trace.final_energy_j < conserve_trace.final_energy_j
        assert push_trace.final_progress_m > conserve_trace.final_progress_m
        gap = push_trace.final_progress_m - conserve_trace.final_progress_m
        assert gap > 1.0, f"deployment moved the car by only {gap} m"

    def test_the_profiles_actually_differed(self, conserve_trace, push_trace) -> None:
        conserve_profiles = {d.action.profile for d in conserve_trace.decisions if d.action is not None}
        push_profiles = {d.action.profile for d in push_trace.decisions if d.action is not None}
        assert conserve_profiles == {DeploymentProfile.HARVEST}
        assert DeploymentProfile.PUSH in push_profiles
        assert conserve_profiles != push_profiles

    def test_the_push_schedule_is_downgraded_when_the_battery_reaches_the_floor(self, push_trace) -> None:
        """A legal fixed schedule stops being legal once the energy runs out.

        Over 20 s of PUSH the battery reaches its floor, the rule context stops
        admitting PUSH, and the controller downgrades to NEUTRAL rather than
        issuing an instruction the car cannot execute. The downgrade carries a
        reason code, so it is visible in the report rather than silent.
        """
        assert push_trace.final_energy_j == pytest.approx(0.0, abs=1.0)
        downgraded = [
            decision
            for decision in push_trace.decisions
            if decision.action is not None and decision.action.profile is not DeploymentProfile.PUSH
        ]
        assert downgraded, "the battery reached its floor but no instruction was downgraded"
        assert all(ReasonCode.POWER_CEILING_EXCEEDED in decision.reasons for decision in downgraded)
        for decision, context in zip(push_trace.decisions, push_trace.contexts, strict=True):
            if decision.action is None or context is None:
                continue
            assert decision.action.profile in context.admissible_profiles


class TestDeterministicBranching:
    def test_identical_treatments_from_one_snapshot_match(
        self, bundle, rule_pack, conserve_controller
    ) -> None:
        base = Simulator()
        base.reset(bundle, seed=42)
        for _ in range(200):
            base.step(None, DT_S)
        snapshot = base.snapshot()

        def branch():
            simulator = Simulator()
            simulator.reset(bundle, seed=snapshot["seed"])
            simulator.restore(snapshot)
            return run_slice(bundle, rule_pack, conserve_controller, horizon_s=10.0, simulator=simulator)

        left = branch()
        right = branch()
        assert left.final_progress_m == right.final_progress_m
        assert left.final_energy_j == right.final_energy_j
        assert left.rival_progress_m == right.rival_progress_m
        assert left.rival_actions == right.rival_actions
        assert [d.action for d in left.decisions] == [d.action for d in right.decisions]

    def test_different_treatments_diverge_with_the_rival_reacting(
        self, bundle, rule_pack, conserve_controller, push_controller
    ) -> None:
        """Two treatments from one snapshot, with the opponent re-deciding.

        The horizon is 30 s rather than 20 s deliberately. A03's opponents react
        only through a hysteretic gap state machine and there is no wake model,
        so the rival's trajectory changes only once the ego's behaviour moves the
        gap across a threshold. From this 4 s pre-roll that takes about 25 s;
        measured at 20 s the two branches' rivals are bit-identical. That is a
        property of the shipped fixture, and it is recorded in
        ``test_the_rival_needs_a_long_enough_branch_to_diverge`` below rather
        than hidden by choosing a convenient horizon silently.
        """
        base = Simulator()
        base.reset(bundle, seed=42)
        for _ in range(200):
            base.step(None, DT_S)
        snapshot = base.snapshot()

        def branch(controller):
            simulator = Simulator()
            simulator.reset(bundle, seed=snapshot["seed"])
            simulator.restore(snapshot)
            return run_slice(bundle, rule_pack, controller, horizon_s=30.0, simulator=simulator)

        conserve = branch(conserve_controller)
        push = branch(push_controller)

        assert conserve.final_progress_m != push.final_progress_m
        assert conserve.final_energy_j != push.final_energy_j
        assert conserve.rival_progress_m != push.rival_progress_m, (
            "the rival ended in the identical place under two different ego "
            "strategies; it would then be a replay, not an independent reaction"
        )
        assert conserve.rival_actions != push.rival_actions

    def test_the_rival_needs_a_long_enough_branch_to_diverge(
        self, bundle, rule_pack, conserve_controller, push_controller
    ) -> None:
        """The fixture limit that sets the horizon above, asserted explicitly.

        This is not a defect in the branching — the branches are separate
        simulators with separate observations throughout. It is a limit of the
        opponent model, and it matters when reading a short paired comparison:
        on a branch too short to move the opponent's state machine, the rival
        contributes no variance at all.
        """
        base = Simulator()
        base.reset(bundle, seed=42)
        for _ in range(200):
            base.step(None, DT_S)
        snapshot = base.snapshot()

        def branch(controller, horizon_s):
            simulator = Simulator()
            simulator.reset(bundle, seed=snapshot["seed"])
            simulator.restore(snapshot)
            return run_slice(bundle, rule_pack, controller, horizon_s=horizon_s, simulator=simulator)

        short_conserve = branch(conserve_controller, 20.0)
        short_push = branch(push_controller, 20.0)
        assert short_conserve.final_progress_m != short_push.final_progress_m
        assert short_conserve.rival_progress_m == short_push.rival_progress_m, (
            "the rival now diverges inside 20 s from this snapshot; update this "
            "recorded fixture limit rather than deleting the test"
        )

    def test_the_two_branches_are_separate_simulators(self, bundle, rule_pack) -> None:
        """A candidate branch cannot inspect the reference branch."""
        base = Simulator()
        base.reset(bundle, seed=42)
        snapshot = base.snapshot()
        left = Simulator()
        left.reset(bundle, seed=snapshot["seed"])
        left.restore(snapshot)
        right = Simulator()
        right.reset(bundle, seed=snapshot["seed"])
        right.restore(snapshot)
        assert left.world is not right.world
        left.step(None, DT_S)
        assert right.session_time_s == 0.0


class TestIndependentAuditOfTheSlice:
    def test_the_slice_trajectory_passes_the_independent_ledger(
        self, bundle, push_controller, rule_pack
    ) -> None:
        """The evaluator audits the very run the acceptance loop produced."""
        simulator = Simulator()
        simulator.reset(bundle, seed=42)
        trajectory = record_trajectory(
            simulator,
            car_id=bundle.scenario.ego_car_id,
            dt_s=DT_S,
            steps=600,
            controller=lambda _obs: __import__(
                "afterlap_core.simulation.policies", fromlist=["DriverAction"]
            ).DriverAction(profile=DeploymentProfile.PUSH),
        )
        audit = reconstruct(trajectory)
        assert not audit.frame_findings
        failures = [d.name for d in audit.discrepancies if not d.within_tolerance]
        assert not failures, failures

    def test_recorded_checkpoints_agree_with_the_independent_reference(
        self, bundle, rule_pack, push_controller
    ) -> None:
        simulator = Simulator()
        simulator.reset(bundle, seed=42)
        ego = bundle.scenario.ego_car_id
        samples = [
            ProgressSample(
                simulator.session_time_s,
                simulator.world.cars[ego].progress_m,
                simulator.world.cars[ego].speed_mps,
            )
        ]
        for _ in range(1300):
            simulator.step(None, DT_S)
            samples.append(
                ProgressSample(
                    simulator.session_time_s,
                    simulator.world.cars[ego].progress_m,
                    simulator.world.cars[ego].speed_mps,
                )
            )
        lines = {cp.id: float(cp.s_m.value) for cp in bundle.track.checkpoints}
        reference = find_crossings(samples, track_length_m=bundle.track.length, lines=lines)
        recorded = {
            (record.checkpoint_id, record.lap): record.session_time_s
            for record in simulator.world.checkpoint_records
            if record.car_id == ego
        }
        assert reference
        for crossing in reference:
            key = (crossing.label, crossing.lap)
            assert key in recorded, f"the simulator never recorded {key}"
            assert crossing.session_time_s == pytest.approx(recorded[key], abs=1.0e-8)


class TestTheMpcRow:
    """A06's planner, in the same closed loop as the baselines.

    This row exists now because A06 is merged. The tripwire that used to stand
    here asserted the planner was absent so the slice could not silently stay
    narrow; it fired, and this is the extension it was asking for.

    The planner receives its estimate through a synthetic adapter, not through
    A05's filter (see ``conftest.estimate_from_observation``). What is measured
    here is that the planner runs inside the loop, that its instructions are
    legal, and that it withdraws rather than guessing. Nothing here measures
    estimation quality or planner performance.
    """

    def test_the_planner_runs_inside_the_closed_loop(self, mpc_trace) -> None:
        trace, controller = mpc_trace
        assert len(trace.decisions) == 12
        assert controller.results, "the planner was never invoked"
        issued = [d for d in trace.decisions if d.action is not None]
        assert issued, [(d.status.value, round(d.latency_ms, 1), d.detail) for d in trace.decisions]
        assert trace.final_progress_m > 0.0

    def test_every_planner_instruction_was_admissible(self, mpc_trace) -> None:
        trace, _ = mpc_trace
        for decision, context in zip(trace.decisions, trace.contexts, strict=True):
            if decision.action is None or context is None:
                continue
            assert decision.action.profile in context.admissible_profiles

    def test_the_selected_plan_passed_the_independent_checker(self, mpc_trace) -> None:
        """``unknown`` is not acceptance: only a PASS verdict reaches the car."""
        _trace, controller = mpc_trace
        accepted = [r for r in controller.results if r.status is PlanningStatus.OK]
        assert accepted, [(r.status.value, r.duration_ms, r.detail) for r in controller.results]
        for result in accepted:
            selected = next(c for c in result.accepted if c.id == result.selected_plan_id)
            assert selected.constraint_result.status is CheckStatus.PASS
            assert selected.constraint_result.checks
            assert selected.constraint_result.checker_version

    def test_the_learned_contribution_is_disabled_with_no_bundle(self, mpc_trace) -> None:
        """This is the MPC-only row, and it says so in its own provenance."""
        _trace, controller = mpc_trace
        assert all(not r.learned_contribution_enabled for r in controller.results)
        assert all(r.baseline_identity for r in controller.results)

    def test_it_withdraws_rather_than_guessing_when_the_rules_are_unknown(self, bundle) -> None:
        from afterlap_core.rules import load_rule_pack

        from .conftest import MpcController

        unknown_pack = load_rule_pack("synthetic-pack-unknown")
        controller = MpcController(unknown_pack, bundle)
        trace = run_slice(
            bundle,
            unknown_pack,
            controller,
            horizon_s=6.0,
            seed=42,
            eligibility=MPC_ELIGIBILITY,
            compute_budget_ms=MPC_BUDGET_MS,
        )
        assert all(decision.withdrawn for decision in trace.decisions)
        assert all(not decision.is_confident_active_directive for decision in trace.decisions)

    def test_it_is_measured_against_a_baseline_at_equal_observation_access(
        self, bundle, rule_pack, mpc_trace
    ) -> None:
        """A paired comparison, with the same declared eligibility on both arms."""
        trace, _ = mpc_trace
        baseline = run_slice(
            bundle,
            rule_pack,
            LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.NEUTRAL),)),
            horizon_s=12.0,
            seed=42,
            eligibility=MPC_ELIGIBILITY,
            compute_budget_ms=MPC_BUDGET_MS,
        )
        assert len(trace.decisions) == len(baseline.decisions)
        assert trace.final_progress_m != baseline.final_progress_m or (
            trace.final_energy_j != baseline.final_energy_j
        ), "the planner produced an outcome indistinguishable from a fixed neutral schedule"

    def test_a_budget_it_cannot_meet_withdraws_the_advice(self, bundle, rule_pack) -> None:
        """A late answer is not an answer.

        With a 1 ms allowance the planner cannot finish, and it must withdraw
        rather than publish a stale plan. This is the deadline behaviour the
        serving specification requires, tested deliberately rather than observed
        by accident under load.
        """
        from .conftest import MpcController

        controller = MpcController(rule_pack, bundle)
        trace = run_slice(
            bundle,
            rule_pack,
            controller,
            horizon_s=4.0,
            seed=42,
            eligibility=MPC_ELIGIBILITY,
            compute_budget_ms=1.0,
        )
        assert all(decision.withdrawn for decision in trace.decisions)
        assert any(decision.status is PlanningStatus.DEADLINE_EXCEEDED for decision in trace.decisions)
        assert all(not decision.is_confident_active_directive for decision in trace.decisions)

    def test_the_planner_latency_is_recorded_not_assumed(self, mpc_trace) -> None:
        """Latency is carried with every decision. No budget is asserted here.

        The invariant that matters is the *relationship*: a decision whose
        measured cost exceeded the allowance it was given must have withdrawn.
        Asserting a wall-clock number instead would make this test a benchmark
        of whatever else the machine was doing.
        """
        trace, _ = mpc_trace
        planned = [d for d in trace.decisions if d.status is not PlanningStatus.INPUT_UNAVAILABLE]
        assert planned
        assert all(d.latency_ms > 0.0 for d in planned)
        for decision in planned:
            if decision.latency_ms > MPC_BUDGET_MS:
                assert decision.withdrawn, "a decision that overran its allowance was still published"


class TestWhatThisSliceDoesNotCover:
    def test_the_learned_rows_are_absent_by_construction(self) -> None:
        """Recorded so the slice is not mistaken for the whole product.

        A06's planner is now merged and the MPC-only row above exercises it. The
        actor and learned-continuation rows still cannot run: A07's serving path
        is not merged and no trained bundle exists, so ``MPC + actor``,
        ``MPC + value`` and ``full system`` remain unmeasured everywhere they
        appear.
        """
        from afterlap_core import learning

        assert not hasattr(learning, "load_bundle"), (
            "A07's serving path appears to be merged; extend this slice with the "
            "actor and continuation rows rather than deleting the check"
        )
        unmeasured = {row.controller_name for row in COMPARISON_MATRIX if not row.measurable_today}
        assert {"mpc_plus_actor", "mpc_plus_value", "full_system"} <= unmeasured

    def test_the_greedy_reference_spends_its_energy_early(self, bundle, rule_pack) -> None:
        """The comparison matrix's second row behaves as its purpose says."""
        greedy = run_slice(
            bundle, rule_pack, LegalGreedyAttacker(reserve_energy_j=4.0e5), horizon_s=20.0, seed=42
        )
        conserve = run_slice(
            bundle,
            rule_pack,
            LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.HARVEST),)),
            horizon_s=20.0,
            seed=42,
        )
        assert greedy.final_energy_j < conserve.final_energy_j
