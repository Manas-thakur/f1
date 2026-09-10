"""The headless closed-loop run behind ``afterlap_core.cli simulate``.

``cli.py`` imported ``run_headless`` from this module and this module did not
exist, so the coordinator's simplest command raised ``ModuleNotFoundError``.
The `mypy` configuration listed ``afterlap_core.runner`` under
``ignore_missing_imports``, which is why the type gate never noticed.

What this runs is an *open-loop* deployment schedule against the real
simulator: no estimator, no planner, no recommendation. It exists so an
operator can answer "does the physics and the energy ledger behave" in one
command, and so a scenario can be smoke-checked without standing up a session.
The summary is therefore labelled with what produced it.

One boundary matters here. This runner is a simulation-side tool and it reads
``WorldState`` to report the energy ledger, which is exactly what the ledger
question needs. Its output is a diagnostic summary printed to an operator: it
is not a contract payload, it is not published to a session, and nothing in
``apps/`` or ``packages/contracts`` consumes it. A caller that needs the
controller-visible view must go through ``Simulator.observe`` and the
estimator, as the session runtime does -- this module is not a shortcut around
that boundary and must not become one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .paths import Paths
from .simulation import DriverAction, ScenarioBundle, Simulator, load_bundle

__all__ = ["HeadlessResult", "run_headless"]

RUNNER_IDENTITY = "afterlap-headless-runner-1"


@dataclass(frozen=True, slots=True)
class HeadlessResult:
    """What one headless run observed. Unknown stays unknown."""

    scenario_id: str
    track_id: str
    seed: int
    requested_duration_s: float
    simulated_duration_s: float
    dt_s: float
    steps: int
    ego_car_id: str
    progress_m: dict[str, float]
    energy_j: dict[str, float]
    energy_close_error_j: dict[str, float]
    deployed_dc_j: dict[str, float]
    harvested_dc_j: dict[str, float]
    recharge_cumulative_j: dict[str, float]
    checkpoint_crossings: int
    passes: int
    saturation_events: int
    envelope_exceedances: int
    profile_downgrades: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        return {
            "runner": RUNNER_IDENTITY,
            "kind": "open_loop_schedule",
            "detail": (
                "an open-loop deployment schedule against the simulator; no estimator, planner "
                "or recommendation took part, so this is not a controller measurement"
            ),
            "scenario_id": self.scenario_id,
            "track_id": self.track_id,
            "seed": self.seed,
            "requested_duration_s": self.requested_duration_s,
            "simulated_duration_s": self.simulated_duration_s,
            "dt_s": self.dt_s,
            "steps": self.steps,
            "ego_car_id": self.ego_car_id,
            "progress_m": self.progress_m,
            "energy_ledger": {
                "energy_j": self.energy_j,
                "close_error_j": self.energy_close_error_j,
                "deployed_dc_j": self.deployed_dc_j,
                "harvested_dc_j": self.harvested_dc_j,
                "recharge_cumulative_j": self.recharge_cumulative_j,
            },
            "events": {
                "checkpoint_crossings": self.checkpoint_crossings,
                "passes": self.passes,
                "saturation_events": self.saturation_events,
                "envelope_exceedances": self.envelope_exceedances,
                "profile_downgrades": self.profile_downgrades,
            },
            "notes": list(self.notes),
        }


def _schedule_action(bundle: ScenarioBundle, session_time_s: float, duration_s: float) -> DriverAction | None:
    """A neutral hold. Deliberately the least interesting schedule there is.

    A runner that deployed aggressively would produce a more impressive energy
    trace and would be answering a question nobody asked. Holding neutral makes
    the ledger residual and the opponent reactions the only moving parts.
    """
    del bundle, session_time_s, duration_s
    return None


def run_headless(
    *,
    scenario_id: str = "two-straight-counterattack",
    seed: int = 42,
    duration_s: float = 30.0,
    dt_s: float = 0.01,
    paths: Paths | None = None,
) -> HeadlessResult:
    """Run one open-loop simulation and report the energy ledger.

    Raises rather than returning a degraded result when the scenario cannot be
    loaded: a summary of a scenario that failed to load would read as a summary
    of a scenario that ran.
    """
    if duration_s <= 0.0:
        raise ValueError("a run needs a positive duration")
    if dt_s <= 0.0:
        raise ValueError("a run needs a positive integration step")
    if dt_s > duration_s:
        raise ValueError(f"the integration step {dt_s} s exceeds the run duration {duration_s} s")

    bundle = load_bundle(scenario_id, paths)
    simulator = Simulator()
    simulator.reset(bundle, seed=seed)
    ego = bundle.scenario.ego_car_id

    steps = 0
    crossings = 0
    passes = 0
    saturation = 0
    exceedances = 0
    downgrades = 0
    started_s = simulator.session_time_s
    remaining = duration_s
    while remaining > 1e-12:
        step_s = min(dt_s, remaining)
        action = _schedule_action(bundle, simulator.session_time_s, duration_s)
        report = simulator.step({ego: action} if action is not None else None, step_s)
        crossings += len(report.checkpoints)
        passes += len(report.passes)
        saturation += len(report.saturation_events)
        exceedances += len(report.envelope_exceedances)
        downgrades += len(report.profile_downgrades)
        steps += 1
        remaining -= step_s

    ledgers = simulator.world.ledgers
    notes: list[str] = [
        "Every configuration behind this run is a synthetic engineering assumption.",
    ]
    if exceedances:
        notes.append(
            f"{exceedances} envelope exceedance(s) were recorded; the reduced tyre model reports "
            "them as unsupported conditions rather than clipping them away"
        )
    return HeadlessResult(
        scenario_id=bundle.scenario.id,
        track_id=bundle.track.id,
        seed=seed,
        requested_duration_s=duration_s,
        simulated_duration_s=simulator.session_time_s - started_s,
        dt_s=dt_s,
        steps=steps,
        ego_car_id=ego,
        progress_m={
            car_id: float(state.progress_m) for car_id, state in sorted(simulator.world.cars.items())
        },
        energy_j={car_id: float(ledger.energy_j) for car_id, ledger in sorted(ledgers.items())},
        energy_close_error_j={
            car_id: float(value) for car_id, value in sorted(simulator.energy_close_errors().items())
        },
        deployed_dc_j={car_id: float(ledger.deployed_dc_j) for car_id, ledger in sorted(ledgers.items())},
        harvested_dc_j={car_id: float(ledger.harvested_dc_j) for car_id, ledger in sorted(ledgers.items())},
        recharge_cumulative_j={
            car_id: float(ledger.recharge_cumulative_j) for car_id, ledger in sorted(ledgers.items())
        },
        checkpoint_crossings=crossings,
        passes=passes,
        saturation_events=saturation,
        envelope_exceedances=exceedances,
        profile_downgrades=downgrades,
        notes=tuple(notes),
    )
