"""The coordinator CLI runs real work and refuses input it cannot run.

``simulate`` used to accept anything typer could parse into a float.
``--duration-s inf`` integrated without end, and ``--duration-s nan`` printed a
complete, successful-looking report of a zero-length run: a fabricated result
from nonsense input. The bounds below are the regression tests for that.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from afterlap_core.cli import app


def test_simulate_runs_real_physics_and_writes_the_same_json(tmp_path):
    output = tmp_path / "simulation.json"
    result = CliRunner().invoke(app, ["simulate", "--duration-s", "0.5", "--output", str(output)])
    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text())
    assert payload["scenario_id"] == "two-straight-counterattack"
    assert payload["requested_duration_s"] == pytest.approx(0.5)
    assert payload["simulated_duration_s"] == pytest.approx(0.5, abs=0.05)
    assert payload["steps"] > 0
    assert payload["progress_m"]["own"] > 0.0
    assert payload["energy_ledger"]["close_error_j"]["own"] == pytest.approx(0.0, abs=1.0)


@pytest.mark.parametrize(
    "args",
    [
        ["--duration-s", "nan"],
        ["--duration-s", "inf"],
        ["--duration-s", "-1"],
        ["--duration-s", "1e9"],
        ["--dt-s", "0"],
        ["--dt-s", "nan"],
        ["--dt-s", "10"],
        ["--seed", "-1"],
        ["--seed", "4294967296"],
        ["--scenario", "../escape"],
        ["--scenario", "no-such-scenario"],
    ],
)
def test_simulate_refuses_bad_parameters_before_running(args):
    """Nothing runs and nothing is printed that could be read as a result."""
    result = CliRunner().invoke(app, ["simulate", *args])
    assert result.exit_code == 2, result.output
    assert "energy_ledger" not in result.output


def test_evaluate_runs_the_shipped_benchmark_and_reports_a_hash():
    result = CliRunner().invoke(app, ["evaluate"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["split"] == "tuning"
    assert payload["report_hash"].startswith("sha256:")
    assert payload["failed_runs"] == 0
    assert "legal_fixed_schedule" in payload["measured_controllers"]


def test_an_unmerged_candidate_is_unavailable_rather_than_measured():
    """A candidate the package cannot build is refused, never silently replaced."""
    result = CliRunner().invoke(app, ["evaluate", "--candidate", "missing"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "unavailable"
    assert payload["candidate"] == "missing"
    assert "not a controller this package can build" in payload["detail"]


def test_ablation_of_an_unmerged_candidate_reports_unavailable():
    result = CliRunner().invoke(app, ["ablate", "--candidate", "missing"])
    payload = json.loads(result.stdout)
    assert payload["status"] == "unavailable"
    assert payload["job"] == "ablate"
    assert result.exception is None or isinstance(result.exception, SystemExit)
