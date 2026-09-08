"""The harness, the report and the gate module.

The theme here is that absent evidence must stay absent: the four unmerged rows
of the comparison matrix appear in the report as ``unmeasured`` with a reason,
withdrawals stay in the denominator, and the gate module cannot be made to
express a certification claim.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    ApprovalStatus,
    DeploymentProfile,
    ModelManifest,
    PromotionPolicy,
)
from afterlap_core.evaluation import (
    LegalFixedSchedule,
    LegalGreedyAttacker,
    ScheduleEntry,
    build_gate_report,
    build_report,
    list_benchmark_manifests,
    load_benchmark_manifest,
    load_objective,
    objective_utility,
    run_benchmark,
    unavailable_matrix_controllers,
    write_report,
)
from afterlap_core.evaluation.gates import (
    CertificationClaimError,
    FidelityStatus,
    Gate,
    GateEvidence,
    GateStatus,
    NumericalConvergence,
    PhysicsFidelity,
    RealCarValidation,
)
from afterlap_core.evaluation.report import UNMEASURED, matrix_coverage
from afterlap_core.evaluation.statistics import (
    UTILITY,
    EvaluationUnit,
    PairedSample,
    hierarchical_paired_bootstrap,
)
from afterlap_core.paths import Paths


@pytest.fixture(scope="module")
def smoke_manifest():
    return load_benchmark_manifest("commissioning-smoke")


@pytest.fixture(scope="module")
def smoke_run(smoke_manifest):
    controllers = [
        LegalFixedSchedule((ScheduleEntry(0.0, DeploymentProfile.HARVEST),)),
        LegalGreedyAttacker(),
        *unavailable_matrix_controllers(),
    ]
    return run_benchmark(smoke_manifest, controllers)


class TestManifests:
    def test_both_shipped_manifests_load(self) -> None:
        available = list_benchmark_manifests()
        assert "commissioning-smoke" in available
        assert "held-out-test-v1" in available

    def test_the_held_out_manifest_declares_itself_as_the_test_split(self) -> None:
        manifest = load_benchmark_manifest("held-out-test-v1")
        assert manifest.split == "test"
        assert manifest.frozen_at is not None
        assert manifest.unit_count == 25
        assert any("target" in note for note in manifest.notes)

    def test_the_manifest_hash_is_stable_and_content_addressed(self, smoke_manifest) -> None:
        again = load_benchmark_manifest("commissioning-smoke")
        assert smoke_manifest.manifest_hash == again.manifest_hash
        assert smoke_manifest.manifest_hash.startswith("sha256:")

    def test_a_manifest_with_a_step_larger_than_its_decision_interval_is_refused(
        self, smoke_manifest
    ) -> None:
        payload = smoke_manifest.model_dump()
        payload["dt_s"] = 5.0
        with pytest.raises(ValueError, match="must not exceed the decision interval"):
            type(smoke_manifest).model_validate(payload)


class TestPairedRuns:
    def test_every_controller_runs_every_unit(self, smoke_run, smoke_manifest) -> None:
        expected = smoke_manifest.unit_count * len(smoke_run.controller_names)
        assert len(smoke_run.outcomes) == expected
        assert not smoke_run.failed_runs

    def test_paired_runs_share_the_starting_snapshot(self, smoke_run) -> None:
        by_unit: dict[tuple[str, int], set[str]] = {}
        for outcome in smoke_run.outcomes:
            if outcome.status == "failed":
                continue
            by_unit.setdefault((outcome.scenario_id, outcome.seed), set()).add(outcome.snapshot_hash)
        for unit, hashes in by_unit.items():
            assert len(hashes) == 1, f"unit {unit} started from more than one snapshot"

    def test_rival_actions_are_recorded_per_branch_not_replayed(self, smoke_run) -> None:
        """Each branch's opponents re-decide; the log is evidence, not an input."""
        logs = {
            outcome.controller: outcome.rival_action_log
            for outcome in smoke_run.outcomes
            if outcome.scenario_id == "two-straight-counterattack" and outcome.seed == 42 and outcome.measured
        }
        assert len(logs) >= 2
        assert all(log for log in logs.values())
        greedy = logs["legal_greedy_attacker"]
        fixed = logs["legal_fixed_schedule"]
        assert greedy != fixed, (
            "the rival's recorded action stream was identical under two different ego "
            "strategies, which would mean the branches were not re-deciding"
        )

    def test_the_rival_trajectory_differs_between_branches(self, smoke_run) -> None:
        """The physical evidence that opponents were not replayed."""
        finals = {
            outcome.controller: outcome.rival_final_progress_m
            for outcome in smoke_run.outcomes
            if outcome.scenario_id == "two-straight-counterattack" and outcome.seed == 42 and outcome.measured
        }
        greedy = finals["legal_greedy_attacker"]["rival"]
        fixed = finals["legal_fixed_schedule"]["rival"]
        assert greedy != fixed, (
            "the rival finished at the identical progress under two different ego "
            "strategies; its controls would then be a replay, not a reaction"
        )

    def test_the_oval_rivals_coincidence_is_recorded_as_a_fixture_limit(self, smoke_run) -> None:
        """A limitation of the fixtures, asserted so it cannot drift unnoticed.

        A03's opponents react only through a hysteretic gap state machine and
        there is no wake model, so a rival whose state machine does not change
        inside the horizon follows the identical trajectory in both branches.
        On ``oval-defend-hold`` over 20 s that is what happens. The independence
        of the branches is structural (separate simulators, separate
        observations); what this test records is that the *fixture* does not
        exercise it, which matters when reading a paired comparison on that row.
        """
        finals = {
            outcome.controller: outcome.rival_final_progress_m
            for outcome in smoke_run.outcomes
            if outcome.scenario_id == "oval-defend-hold" and outcome.seed == 42 and outcome.measured
        }
        assert finals["legal_greedy_attacker"]["rival"] == finals["legal_fixed_schedule"]["rival"], (
            "the oval rival now diverges between branches; update this recorded "
            "limitation rather than deleting the test"
        )

    def test_deployment_changes_the_realised_energy_and_position(self, smoke_run) -> None:
        fixed = next(
            o
            for o in smoke_run.outcomes
            if o.controller == "legal_fixed_schedule"
            and o.scenario_id == "two-straight-counterattack"
            and o.seed == 42
        )
        greedy = next(
            o
            for o in smoke_run.outcomes
            if o.controller == "legal_greedy_attacker"
            and o.scenario_id == "two-straight-counterattack"
            and o.seed == 42
        )
        assert greedy.final_energy_j < fixed.final_energy_j
        assert greedy.final_progress_m > fixed.final_progress_m

    def test_withdrawals_stay_in_the_denominator(self, smoke_run) -> None:
        for outcome in smoke_run.outcomes:
            assert outcome.decisions > 0
            assert outcome.withdrawn_decisions <= outcome.decisions
            if outcome.measured:
                assert outcome.withdrawal_rate is not None

    def test_unmerged_controllers_are_unavailable_not_zero(self, smoke_run) -> None:
        for name in ("mpc_only", "mpc_plus_actor", "mpc_plus_value", "full_system"):
            runs = smoke_run.for_controller(name)
            assert runs
            assert all(run.status == "unavailable" for run in runs)
            assert all(run.elapsed_time_s is None for run in runs)
            assert all(run.final_energy_j is None for run in runs)
            assert name in smoke_run.unavailable_controllers

    def test_no_baseline_issued_an_inadmissible_profile(self, smoke_run) -> None:
        assert all(outcome.modelled_violations == 0 for outcome in smoke_run.outcomes)

    def test_the_environment_record_is_captured(self, smoke_run) -> None:
        environment = smoke_run.environment
        assert environment.python_version.startswith("3.12")
        assert environment.numpy_version
        assert environment.hardware
        assert smoke_run.rerun_command


class TestObjective:
    def test_the_frozen_objective_is_read_not_invented(self) -> None:
        objective = load_objective()
        assert objective.revision == "objective-v1"
        assert objective.elapsed_second_penalty == 1.0
        assert objective.finish_position_penalty == 30.0

    def test_utility_penalises_time_position_and_churn(self, smoke_run) -> None:
        objective = load_objective()
        outcome = next(o for o in smoke_run.outcomes if o.measured)
        utility = objective_utility(outcome, objective)
        expected = -(
            objective.elapsed_second_penalty * outcome.elapsed_time_s
            + objective.instruction_change_penalty * outcome.instruction_changes
            + objective.finish_position_penalty * (outcome.final_position - 1)
        )
        assert utility == pytest.approx(expected)

    def test_an_unmeasured_run_cannot_be_scored(self, smoke_run) -> None:
        objective = load_objective()
        unavailable = next(o for o in smoke_run.outcomes if o.status == "unavailable")
        with pytest.raises(ValueError, match="no measured outcome"):
            objective_utility(unavailable, objective)


@pytest.fixture(scope="module")
def report_bundle(smoke_run):
    objective = load_objective()
    units = {}
    for outcome in smoke_run.outcomes:
        if not outcome.measured:
            continue
        key = (outcome.scenario_id, outcome.seed)
        entry = units.setdefault(key, {"family": outcome.family, "values": {}})
        entry["values"][outcome.controller] = objective_utility(outcome, objective)
    sample = PairedSample(
        metric=UTILITY,
        units=tuple(
            EvaluationUnit(
                scenario_id=scenario,
                seed=seed,
                family=entry["family"],
                values=entry["values"],
            )
            for (scenario, seed), entry in sorted(units.items())
        ),
    )
    result = hierarchical_paired_bootstrap(
        sample,
        "legal_greedy_attacker",
        "legal_fixed_schedule",
        iterations=500,
        seed=17,
    )
    return build_report(
        smoke_run,
        report_id="a13-commissioning-smoke",
        reference_controller="legal_fixed_schedule",
        bootstraps=[result],
    )


class TestReport:
    def test_the_contract_record_validates(self, report_bundle) -> None:
        report = report_bundle.contract
        assert report.id == "a13-commissioning-smoke"
        assert report.scenario_count == 2
        assert report.seed_count == 2
        assert report.hardware
        assert report.rerun_command
        assert report.latency_p95_ms is not None

    def test_the_unmerged_rows_read_as_unmeasured(self, report_bundle) -> None:
        rows = {row["controller"]: row for row in report_bundle.detail["comparison_matrix"]}
        for name in ("mpc_only", "mpc_plus_actor", "mpc_plus_value", "full_system"):
            assert rows[name]["status"] == UNMEASURED
            assert rows[name]["reason"]
            assert rows[name]["comparison"] is None
        assert rows["legal_fixed_schedule"]["status"] == "reference"
        assert rows["legal_greedy_attacker"]["status"] == "measured"

    def test_unmeasured_rows_are_named_in_the_contract_notes(self, report_bundle) -> None:
        joined = " ".join(report_bundle.contract.notes)
        assert "unmeasured comparison-matrix rows" in joined
        assert "mpc_only" in joined

    def test_calibration_absence_is_stated_not_implied_perfect(self, report_bundle) -> None:
        assert report_bundle.contract.calibration == ()
        assert any("calibration is unmeasured" in note for note in report_bundle.contract.notes)

    def test_the_matrix_coverage_table_lists_all_six_rows(self, smoke_run) -> None:
        coverage = matrix_coverage(smoke_run)
        assert len(coverage) == 6
        assert sum(1 for row in coverage if row["status"] == UNMEASURED) == 4

    def test_per_family_results_are_reported_separately(self, report_bundle) -> None:
        families = report_bundle.detail["per_family"]
        assert set(families) == {"loop-counterattack", "oval-defence"}
        for entry in families.values():
            assert entry["scenario_count"] == 1
            assert entry["seed_count"] == 2

    def test_failed_and_missing_runs_are_counted(self, report_bundle) -> None:
        population = report_bundle.detail["population"]
        assert population["planned_units"] == 4
        assert population["failed_runs"] == 0
        assert population["unavailable_runs"] == 16
        assert population["completed_runs"] == 8

    def test_hard_violations_are_listed_individually(self, report_bundle) -> None:
        assert report_bundle.detail["hard_violations"] == []
        assert report_bundle.contract.modelled_violations == 0

    def test_losing_snapshots_are_reproducible(self, report_bundle) -> None:
        losing = report_bundle.detail["losing_snapshots"]
        assert isinstance(losing, dict)
        for entries in losing.values():
            for entry in entries:
                assert entry["snapshot_hash"]
                assert entry["manifest_hash"]
                assert entry["scenario_id"] and entry["seed"] is not None

    def test_the_report_never_claims_certification(self, report_bundle) -> None:
        assert report_bundle.detail["certification"] == "not_claimed"
        text = json.dumps(report_bundle.as_dict())
        assert "certified" not in text.lower()

    def test_it_writes_and_reloads(self, report_bundle, tmp_path) -> None:
        paths = Paths.default(tmp_path)
        target = write_report(report_bundle, paths=paths)
        assert target.exists()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["report"]["id"] == "a13-commissioning-smoke"
        assert payload["report_hash"].startswith("sha256:")
        assert payload["detail"]["manifest"]["hash"] == report_bundle.detail["manifest"]["hash"]


class TestGates:
    def _fidelity(self) -> PhysicsFidelity:
        return PhysicsFidelity(
            status=FidelityStatus.ESTABLISHED_IN_SIMULATION,
            reference="03_simulation/NUMERICS_AND_VALIDATION.md reference equations",
            independent_checker="afterlap_core.evaluation.independent_ledger",
            residual_summary="battery ledger closes to 3.7e-8 J over a 20 s two-car run",
            test_ids=("tests/evaluation/test_independent_ledger.py",),
        )

    def _convergence(self) -> NumericalConvergence:
        return NumericalConvergence(
            status=FidelityStatus.ESTABLISHED_IN_SIMULATION,
            resolutions=(0.02, 0.01, 0.005),
            quantity_summary="elapsed-time deltas fall by four per halving",
            ranking_stable=True,
            test_ids=("tests/numerics/test_convergence.py",),
        )

    def test_real_car_validation_has_exactly_one_reachable_value(self) -> None:
        record = RealCarValidation()
        assert record.status is FidelityStatus.UNMEASURABLE_NO_REAL_CAR_DATA
        with pytest.raises(CertificationClaimError, match="no real-car measurements"):
            RealCarValidation(measurements_available=True)

    def test_the_three_fidelity_statuses_are_separate(self) -> None:
        report = build_gate_report(
            source_revision="workspace",
            generated_at=datetime.now(UTC),
            gates=(),
            physics_fidelity=self._fidelity(),
            numerical_convergence=self._convergence(),
        )
        fidelity = report.as_dict()["fidelity"]
        assert set(fidelity) == {"physics", "numerical_convergence", "real_car_validation"}
        assert fidelity["physics"]["status"] == "established_in_simulation"
        assert fidelity["real_car_validation"]["status"] == "unmeasurable_no_real_car_data"

    def test_physics_fidelity_cannot_borrow_the_real_car_status(self) -> None:
        with pytest.raises(ValueError, match="separate record"):
            PhysicsFidelity(
                status=FidelityStatus.UNMEASURABLE_NO_REAL_CAR_DATA,
                reference="x",
                independent_checker="y",
                residual_summary="z",
            )

    @pytest.mark.parametrize(
        "claim",
        [
            "this build is certified for race use",
            "FIA-approved rule pack",
            "validated against a real car",
            "guaranteed within the energy window",
            "homologated for the 2026 season",
        ],
    )
    def test_a_certification_claim_is_refused(self, claim: str) -> None:
        with pytest.raises(CertificationClaimError):
            GateEvidence(gate=Gate.G1, status=GateStatus.NOT_RUN, owner="A13", note=claim)

    def test_a_gate_cannot_pass_without_evidence(self) -> None:
        with pytest.raises(ValueError, match="test ids"):
            GateEvidence(gate=Gate.G1, status=GateStatus.PASSED, owner="A13")
        with pytest.raises(ValueError, match="evidence path"):
            GateEvidence(
                gate=Gate.G1,
                status=GateStatus.PASSED,
                owner="A13",
                test_ids=("tests/evaluation/test_independent_ledger.py",),
            )

    def test_a_partial_gate_must_name_what_is_missing(self) -> None:
        with pytest.raises(ValueError, match="names nothing missing"):
            GateEvidence(gate=Gate.G7, status=GateStatus.PARTIAL, owner="A13")

    def test_an_unreported_gate_reads_as_not_run(self) -> None:
        report = build_gate_report(
            source_revision="workspace",
            generated_at=datetime.now(UTC),
            gates=(
                GateEvidence(
                    gate=Gate.G1,
                    status=GateStatus.PASSED,
                    owner="A13",
                    test_ids=("tests/evaluation/test_independent_ledger.py",),
                    evidence_path="artifacts/reports/a13-commissioning-smoke.json",
                ),
            ),
            physics_fidelity=self._fidelity(),
            numerical_convergence=self._convergence(),
        )
        assert report.status_of(Gate.G1) is GateStatus.PASSED
        assert report.status_of(Gate.G7) is GateStatus.NOT_RUN
        assert report.as_dict()["certification"] == "not_claimed"


class TestPromotionRefusesWithoutEvidence:
    def test_an_approved_bundle_requires_a_report_and_a_frozen_policy(self) -> None:
        with pytest.raises(ValueError, match="benchmark report"):
            ModelManifest(
                schema_version=SCHEMA_VERSION,
                id="candidate-1",
                algorithm="sac",
                weights_hash="sha256:0",
                feature_schema_hash="sha256:1",
                rule_family="synthetic-2026-r0",
                reward_revision="objective-v1",
                approval_status=ApprovalStatus.APPROVED,
                created_at=datetime.now(UTC),
            )

    def test_an_enabled_policy_without_thresholds_is_refused(self) -> None:
        with pytest.raises(ValueError, match="without frozen thresholds"):
            PromotionPolicy(enabled=True)
