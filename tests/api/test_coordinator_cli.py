from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from afterlap_core.cli import app


def test_simulate_runs_real_physics_and_writes_the_same_json(tmp_path):
    output = tmp_path / "simulation.json"
    result = CliRunner().invoke(app, ["simulate", "--duration-s", "0.1", "--output", str(output)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert json.loads(output.read_text()) == payload
    outcome = payload["outcomes"][0]
    assert outcome["status"] == "completed"
    assert outcome["elapsed_time_s"] == pytest.approx(0.1)
    assert outcome["final_progress_m"] > 0
    assert outcome["final_energy_j"] > 0
    assert outcome["snapshot_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "args",
    [
        ["--duration-s", "nan"],
        ["--duration-s", "inf"],
        ["--dt-s", "0"],
        ["--seed", "-1"],
        ["--seed", "4294967296"],
        ["--scenario", "../escape"],
    ],
)
def test_simulate_rejects_bad_parameters_before_running(args):
    result = CliRunner().invoke(app, ["simulate", *args])
    assert result.exit_code == 2


def test_evaluate_uses_the_existing_harness(tmp_path):
    manifest = tmp_path / "benchmark.yaml"
    manifest.write_text("""id: cli-test
split: tuning
description: Synthetic CLI regression
scenario_ids: [two-straight-counterattack]
seeds: [42]
horizon_s: 0.1
dt_s: 0.01
decision_interval_s: 1
compute_budget_ms: 200
rule_pack_id: synthetic-pack-v1
""")
    result = CliRunner().invoke(app, ["evaluate", "--benchmark", str(manifest)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["outcomes"][0]["status"] == "completed"


@pytest.mark.parametrize(
    "args", [["evaluate", "--candidate", "missing"], ["ablate", "--candidate", "missing"]]
)
def test_unimplemented_candidate_paths_report_unavailable(args):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "unavailable"
    assert result.exception is None or isinstance(result.exception, SystemExit)
