"""Integration-resolution convergence.

The acceptance criterion is not "the trajectories are identical" — a finite-step
integrator changes its answer when the step changes. It is that *halving dt does
not change the branch ranking*: the decision the simulator supports must not be
an artefact of the integration resolution.

The measured deltas are printed by ``report_convergence`` and reproduced in
``handoffs/A03.md``.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, Simulator, Treatment, run_branch

RESOLUTIONS = (0.02, 0.01, 0.005)
HORIZON_S = 14.0
PRE_ROLL_S = 0.4
CHECKPOINT = "attack-exit"

ELAPSED_DRIFT_TOLERANCE_S = 1.0e-3
"""Allowed change in checkpoint elapsed time when the step is halved.

Established empirically from the runs below. Measured on this suite, refining
0.02 -> 0.01 -> 0.005 moves the ``push`` checkpoint time by 1.3e-6 s then
3.3e-7 s, and the ``conserve`` time by 4.7e-7 s then 1.2e-7 s: the ratio of
about four per halving is the expected second-order behaviour of the midpoint
integrator. The threshold sits three orders of magnitude above the largest
observed delta, which is loose enough to survive platform float differences and
still nine orders below the 0.69 s separation between the treatments.
"""

ENERGY_DRIFT_TOLERANCE_J = 1.0e2
"""Allowed change in final stored energy when the step is halved.

Measured: ``push`` moves by about 1e-8 J, ``conserve`` by 25.0 J then 12.5 J
out of 2.91 MJ (8.6e-6 relative). The halving ratio is first order, which is the
electrical saturation being resolved once per step; 100 J is four times the
largest observed delta and 2.5e-5 of the battery window.
"""


def _controller(profile: DeploymentProfile):
    def act(observation) -> DriverAction:
        del observation
        return DriverAction(profile=profile, label=profile.value)

    return act


TREATMENTS = (
    Treatment(id="push", controller=_controller(DeploymentProfile.OVERTAKE)),
    Treatment(id="conserve", controller=_controller(DeploymentProfile.HARVEST)),
)


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
    for treatment in TREATMENTS:
        branch = run_branch(
            bundle,
            snapshot,
            treatment,
            horizon_s=HORIZON_S,
            dt_s=dt_s,
            checkpoint_ids=(CHECKPOINT,),
        )
        outcome = branch.outcome_by_checkpoint[CHECKPOINT]
        assert outcome.event_observed, (
            f"{treatment.id} did not reach {CHECKPOINT} within {HORIZON_S} s at dt={dt_s}"
        )
        assert outcome.elapsed_time_s is not None
        assert outcome.energy_j is not None
        results[treatment.id] = {
            "elapsed_time_s": outcome.elapsed_time_s,
            "energy_j": outcome.energy_j,
        }
    return results


def report_convergence() -> dict[float, dict[str, dict[str, float]]]:
    """Run the whole suite at every resolution. Used by the test and the handoff."""
    return {dt: _run_suite(dt) for dt in RESOLUTIONS}


@pytest.fixture(scope="module")
def convergence_report() -> dict[float, dict[str, dict[str, float]]]:
    return report_convergence()


class TestConvergence:
    def test_the_treatments_are_actually_distinguishable(self, convergence_report) -> None:
        """A ranking test is meaningless if the treatments produce the same result."""
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
            times = [convergence_report[dt][treatment.id]["elapsed_time_s"] for dt in RESOLUTIONS]
            deltas = [abs(later - earlier) for earlier, later in pairwise(times)]
            assert all(delta <= ELAPSED_DRIFT_TOLERANCE_S for delta in deltas), (
                f"{treatment.id} elapsed times {times} drift by {deltas}"
            )

    def test_final_energy_converges(self, convergence_report) -> None:
        for treatment in TREATMENTS:
            energies = [convergence_report[dt][treatment.id]["energy_j"] for dt in RESOLUTIONS]
            deltas = [abs(later - earlier) for earlier, later in pairwise(energies)]
            assert all(delta <= ENERGY_DRIFT_TOLERANCE_J for delta in deltas), (
                f"{treatment.id} energies {energies} drift by {deltas}"
            )

    def test_refinement_reduces_the_change(self, convergence_report) -> None:
        """Successive refinement must not make the answer wander further."""
        for treatment in TREATMENTS:
            times = [convergence_report[dt][treatment.id]["elapsed_time_s"] for dt in RESOLUTIONS]
            coarse_delta = abs(times[1] - times[0])
            fine_delta = abs(times[2] - times[1])
            assert fine_delta <= coarse_delta + ELAPSED_DRIFT_TOLERANCE_S


if __name__ == "__main__":  # pragma: no cover - used to produce handoff numbers
    import json

    print(json.dumps({str(k): v for k, v in report_convergence().items()}, indent=2, sort_keys=True))
