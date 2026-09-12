from __future__ import annotations

from itertools import pairwise

import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, Simulator

RESOLUTIONS = (0.02, 0.01, 0.005)
HORIZON_S = 14.0
PRE_ROLL_S = 0.4
CHECKPOINT = "attack-exit"

ELAPSED_DRIFT_TOLERANCE_S = 1.0e-3


ENERGY_DRIFT_TOLERANCE_J = 1.0e2


def _controller(profile: DeploymentProfile):
    def act(observation) -> DriverAction:
        del observation
        return DriverAction(profile=profile, label=profile.value)

    return act


TREATMENTS = {"push": DeploymentProfile.OVERTAKE, "conserve": DeploymentProfile.HARVEST}


def _bundle():
    from conftest import build_bundle

    return build_bundle(
        progress_m={"own": 1600.0, "rival": 1750.0},
        speeds_mps={"own": 70.0, "rival": 70.0},
        energies_j={"own": 3.0e6, "rival": 3.0e6},
    )


def _run_suite(dt_s: float) -> dict[str, dict[str, float]]:
    bundle = _bundle()
    simulator = Simulator().reset(bundle)
    elapsed = 0.0
    while elapsed < PRE_ROLL_S - 1e-12:
        simulator.step(None, min(dt_s, PRE_ROLL_S - elapsed))
        elapsed += min(dt_s, PRE_ROLL_S - elapsed)
    snapshot = simulator.snapshot()

    results: dict[str, dict[str, float]] = {}
    for name, profile in TREATMENTS.items():
        branch = Simulator().reset(bundle)
        branch.restore(snapshot)
        start_time = branch.session_time_s
        while branch.session_time_s - start_time < HORIZON_S - 1e-12:
            step = min(dt_s, HORIZON_S - (branch.session_time_s - start_time))
            branch.step({"own": DriverAction(profile=profile, label=name)}, step)
        records = [
            record
            for record in branch.world.checkpoint_records
            if record.car_id == "own"
            and record.checkpoint_id == CHECKPOINT
            and record.session_time_s > start_time
        ]
        assert records, f"{name} did not reach {CHECKPOINT} within {HORIZON_S} s at dt={dt_s}"
        results[name] = {
            "elapsed_time_s": records[0].session_time_s - start_time,
            "energy_j": records[0].battery_energy_j,
        }
    return results


def report_convergence() -> dict[float, dict[str, dict[str, float]]]:

    return {dt: _run_suite(dt) for dt in RESOLUTIONS}


@pytest.fixture(scope="module")
def convergence_report() -> dict[float, dict[str, dict[str, float]]]:
    return report_convergence()


class TestConvergence:
    def test_the_treatments_are_actually_distinguishable(self, convergence_report) -> None:

        for dt, results in convergence_report.items():
            gap = results["conserve"]["elapsed_time_s"] - results["push"]["elapsed_time_s"]
            assert gap > 10.0 * ELAPSED_DRIFT_TOLERANCE_S, (
                f"at dt={dt} the treatments differ by only {gap} s, which the drift tolerance "
                "could not distinguish"
            )

    def test_halving_dt_does_not_change_the_branch_ranking(self, convergence_report) -> None:
        rankings = {
            dt: tuple(sorted(results, key=lambda name: results[name]["elapsed_time_s"]))
            for dt, results in convergence_report.items()
        }
        assert len(set(rankings.values())) == 1, f"branch ranking changed with dt: {rankings}"

    def test_checkpoint_elapsed_time_converges(self, convergence_report) -> None:
        for treatment in TREATMENTS:
            times = [convergence_report[dt][treatment]["elapsed_time_s"] for dt in RESOLUTIONS]
            deltas = [abs(later - earlier) for earlier, later in pairwise(times)]
            assert all(delta <= ELAPSED_DRIFT_TOLERANCE_S for delta in deltas), (
                f"{treatment} elapsed times {times} drift by {deltas}"
            )

    def test_final_energy_converges(self, convergence_report) -> None:
        for treatment in TREATMENTS:
            energies = [convergence_report[dt][treatment]["energy_j"] for dt in RESOLUTIONS]
            deltas = [abs(later - earlier) for earlier, later in pairwise(energies)]
            assert all(delta <= ENERGY_DRIFT_TOLERANCE_J for delta in deltas), (
                f"{treatment} energies {energies} drift by {deltas}"
            )

    def test_refinement_reduces_the_change(self, convergence_report) -> None:

        for treatment in TREATMENTS:
            times = [convergence_report[dt][treatment]["elapsed_time_s"] for dt in RESOLUTIONS]
            coarse_delta = abs(times[1] - times[0])
            fine_delta = abs(times[2] - times[1])
            assert fine_delta <= coarse_delta + ELAPSED_DRIFT_TOLERANCE_S


if __name__ == "__main__":
    import json

    print(json.dumps({str(k): v for k, v in report_convergence().items()}, indent=2, sort_keys=True))
