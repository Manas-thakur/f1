"""The operator entry points, and the CLI that could not previously reach them.

On the audited revision five of nine coordinator commands raised on import or
on call: ``simulate`` imported a module that did not exist, ``train`` and
``ablate`` imported functions that were never written, and ``evaluate`` and
``promote`` passed keyword arguments no signature accepted. The regression
tests here are deliberately shallow and broad -- they invoke every command and
assert it resolves -- because the defect was never subtle. It was unreachable
code that nothing exercised.

No training runs here. ``run_training`` is checked for its argument handling
and its refusals; the bounded run that produced real metrics is a separate,
recorded job, not a test.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="the training jobs import the learning stack")
pytest.importorskip("stable_baselines3", reason="the training jobs import SB3")

from typer.testing import CliRunner

from afterlap_core.cli import app
from afterlap_core.evaluation import jobs as evaluation_jobs
from afterlap_core.learning import jobs as learning_jobs

runner = CliRunner()


def _artifacts_in(root: Path):
    """Redirect artefact writes without moving the shipped configuration root.

    ``Paths.default(root)`` moves ``configs`` too, so a benchmark run under a
    temporary root would fail to load the manifests it is meant to run.
    """
    import dataclasses

    from afterlap_core.paths import Paths

    base = Paths.default()
    artifacts = root / "artifacts"
    return dataclasses.replace(
        base,
        artifacts=artifacts,
        trajectories=artifacts / "trajectories",
        models=artifacts / "models",
        reports=artifacts / "reports",
        exports=artifacts / "exports",
        spool=artifacts / "spool",
    ).ensure()


class TestEveryCommandResolves:
    """Each of these would have failed on the audited revision."""

    @pytest.mark.parametrize(
        "command",
        ["simulate", "train", "evaluate", "ablate", "promote", "package-model", "throughput"],
    )
    def test_the_command_is_registered_and_its_help_renders(self, command: str) -> None:
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output
        assert command.split("-", maxsplit=1)[0] in result.output.lower() or "usage" in result.output.lower()

    def test_the_headless_runner_module_exists_and_is_importable(self) -> None:
        from afterlap_core.runner import run_headless

        assert callable(run_headless)

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("afterlap_core.learning.jobs", "run_training"),
            ("afterlap_core.learning.jobs", "run_packaging"),
            ("afterlap_core.learning.jobs", "run_throughput_benchmark"),
            ("afterlap_core.learning.promotion", "decide_from_paths"),
            ("afterlap_core.evaluation.jobs", "run_evaluation"),
            ("afterlap_core.evaluation.jobs", "run_ablation_job"),
            ("afterlap_core.evaluation.harness", "run_ablation"),
            ("afterlap_core.evaluation.harness", "paired_sample_from_run"),
        ],
    )
    def test_the_referenced_symbol_exists(self, module: str, name: str) -> None:
        import importlib

        assert hasattr(importlib.import_module(module), name)


class TestHeadlessRunner:
    def test_a_short_run_reports_its_ledger_and_names_what_produced_it(self) -> None:
        from afterlap_core.runner import run_headless

        result = run_headless(duration_s=1.0, dt_s=0.05, seed=3)
        summary = result.summary()
        assert summary["kind"] == "open_loop_schedule"
        assert "no estimator, planner" in summary["detail"]
        assert result.steps == 20
        assert set(result.energy_j) == set(result.energy_close_error_j)
        assert all(abs(value) < 1.0 for value in result.energy_close_error_j.values())

    @pytest.mark.parametrize(
        ("duration_s", "dt_s"),
        [(0.0, 0.01), (-1.0, 0.01), (1.0, 0.0), (1.0, 2.0)],
    )
    def test_an_impossible_run_is_refused_rather_than_summarised(
        self, duration_s: float, dt_s: float
    ) -> None:
        from afterlap_core.runner import run_headless

        with pytest.raises(ValueError):
            run_headless(duration_s=duration_s, dt_s=dt_s)


class TestConfigResolution:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "sac-v1"),
            ("sac-v1", "sac-v1"),
            ("configs/learning/sac-v1.yaml", "sac-v1"),
            (Path("configs/learning/env-v1.yaml"), "env-v1"),
        ],
    )
    def test_a_path_or_an_id_resolve_to_the_same_id(self, value, expected: str) -> None:
        assert learning_jobs.resolve_config_id(value, "sac-v1") == expected


class TestTrainingJobRefusals:
    def test_a_smoke_resume_is_refused_because_it_would_mislabel_the_artifact(self) -> None:
        with pytest.raises(ValueError, match="cannot also be a smoke job"):
            learning_jobs.run_training(smoke=True, resume_from=Path("nowhere"))

    def test_the_job_exposes_no_way_to_declare_a_bundle_approved(self) -> None:
        parameters = inspect.signature(learning_jobs.run_training).parameters
        assert "approval_status" not in parameters
        assert "approved" not in parameters
        assert "promote" not in parameters


class TestEvaluationJob:
    def test_a_named_candidate_without_a_controller_is_unavailable_not_the_baseline(self) -> None:
        """Evaluating the baseline under a candidate's name would misreport it."""
        payload = evaluation_jobs.run_evaluation(candidate="mpc_plus_actor")
        assert payload["status"] == "unavailable"
        assert "not a controller this package can build" in payload["detail"]

    def test_an_ablation_without_a_learned_controller_is_unmeasured_not_a_null_result(self) -> None:
        payload = evaluation_jobs.run_ablation_job(candidate="mpc_plus_actor", disable="policy")
        assert payload["status"] == "unavailable"
        assert "would report no difference" in payload["detail"]

    def test_an_unknown_ablation_target_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown ablation target"):
            evaluation_jobs.run_ablation_job(candidate="x", disable="everything")

    def test_the_baseline_controllers_declare_no_learned_contribution(self) -> None:
        for controller in evaluation_jobs.baseline_controllers():
            assert controller.uses_actor is False
            assert controller.uses_learned_return is False


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    """One real benchmark run over the commissioning-smoke manifest."""
    return evaluation_jobs.run_evaluation(
        candidate="baseline",
        benchmark_id="commissioning-smoke",
        bootstrap_iterations=64,
        paths=_artifacts_in(tmp_path_factory.mktemp("evaluation")),
    )


class TestBaselineEvaluationRunsEndToEnd:
    """The one job here that really executes the simulator, kept small."""

    def test_the_report_is_written_and_hashed(self, report) -> None:
        assert report["status"] == "completed"
        assert report["report_hash"].startswith("sha256:")
        assert Path(report["report_path"]).is_file()
        payload = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
        assert payload["report_hash"] == report["report_hash"]

    def test_both_merged_baselines_were_measured(self, report) -> None:
        assert "legal_fixed_schedule" in report["measured_controllers"]
        assert "legal_greedy_attacker" in report["measured_controllers"]

    def test_the_unmerged_matrix_rows_are_present_as_unmeasured(self, report) -> None:
        """A row that cannot run is unmeasured, never silently omitted."""
        unavailable = set(report["unavailable_controllers"])
        assert {"mpc_only", "mpc_plus_actor", "mpc_plus_value", "full_system"} <= unavailable

    def test_a_paired_comparison_was_computed_against_the_reference(self, report) -> None:
        assert report["comparisons"]
        controllers = {comparison["controller"] for comparison in report["comparisons"]}
        assert "legal_greedy_attacker" in controllers

    def test_the_report_never_claims_certification(self, report) -> None:
        payload = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
        assert payload["detail"]["certification"] == "not_claimed"


class TestPromotionEntryPoint:
    def test_a_directory_without_a_bundle_is_a_refusal_not_a_crash(self, tmp_path) -> None:
        from afterlap_core.learning.promotion import decide_from_paths

        decision = decide_from_paths(bundle_directory=tmp_path)
        assert decision["promoted"] is False
        assert decision["baseline_enabled"] is True
        assert "no bundle.json" in " ".join(decision["detail"])

    def test_deciding_never_writes_approval_into_the_bundle(self, tmp_path) -> None:
        """``AGENTS.md`` forbids automatic promotion; asking is not approving."""
        from afterlap_core.learning.promotion import decide_from_paths

        decision = decide_from_paths(bundle_directory=tmp_path)
        assert decision["recorded_on_disk"] is False
        assert "never as a side effect" in decision["recording_note"]

    def test_the_cli_exits_non_zero_when_promotion_is_refused(self, tmp_path) -> None:
        result = runner.invoke(app, ["promote", "--bundle", str(tmp_path)])
        assert result.exit_code == 1
        assert '"promoted": false' in result.output
