"""A compiled package drives the unchanged engine, and the environment seam is live.

The circuit here is a synthetic analytic loop written through the same package
path a real circuit will use, so what is proven is the *wiring*: package ->
loader -> ``TrackSource`` -> ``Simulator``, plus the two ``EnvironmentField``
sites in the force balance.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from afterlap_core.config import Parameter
from afterlap_core.simulation import Simulator
from afterlap_core.simulation.config import ScenarioBundle, load_bundle, load_track
from afterlap_core.simulation.policies import DriverAction
from afterlap_core.simulation.track_source import DEFAULT_ENVIRONMENT, EnvironmentField, StaticEnvironment

from .conftest import SYNTHETIC_TRACK_ID


def _bundle_on(track) -> ScenarioBundle:
    shipped = load_bundle("two-straight-counterattack")
    scenario = shipped.scenario
    states = {}
    for car_id, state in scenario.initial_states.items():
        offset = 0.0 if car_id == scenario.ego_car_id else 60.0
        states[car_id] = state.model_copy(
            update={"progress_m": state.progress_m.model_copy(update={"value": 100.0 + offset})}
        )
    scenario = scenario.model_copy(
        update={
            "track_id": track.id,
            "initial_states": states,
            "gap_ahead_s": None,
            "evaluation_checkpoints": ("turn-1", "sector-3-end"),
            "retention_checkpoint_id": "sector-3-end",
        }
    )
    return ScenarioBundle(scenario=scenario, track=track, car_configs=shipped.car_configs)


def _run(
    bundle: ScenarioBundle, environment: EnvironmentField | None, steps: int = 150
) -> list[tuple[float, float, float]]:
    sim = Simulator().reset(bundle, seed=7, environment=environment)
    rows = []
    action = DriverAction(throttle=1.0, brake=0.0)
    for _ in range(steps):
        sim.step({bundle.scenario.ego_car_id: action}, 0.02)
        ego = sim.world.cars[bundle.scenario.ego_car_id]
        rows.append((ego.progress_m, ego.speed_mps, ego.battery_energy_j))
    return rows


@dataclass(frozen=True)
class _Headwind:
    """Test double: dense, gusty air and a wet surface, uniform along the lap."""

    def air_density_kgpm3(self, s_m, session_time_s, fallback):
        return fallback * 1.10

    def headwind_mps(self, s_m, heading_rad, session_time_s):
        return 12.0

    def grip_multiplier(self, s_m, session_time_s):
        return 0.6

    @property
    def describes(self) -> str:
        return "test double: +10% density, 12 m/s headwind, 0.6 grip"


def test_the_engine_runs_on_a_compiled_package(frozen_package):
    _, paths = frozen_package
    track = load_track(SYNTHETIC_TRACK_ID, paths)
    bundle = _bundle_on(track)
    rows = _run(bundle, None)
    assert rows[-1][0] > rows[0][0] > 100.0, "the ego car must move along the compiled centreline"
    assert all(s > 0.0 for _, s, _ in rows)
    assert bundle.bundle_hash  # the package hash participates in the bundle identity


def test_replay_is_deterministic_on_a_compiled_package(frozen_package):
    _, paths = frozen_package
    bundle = _bundle_on(load_track(SYNTHETIC_TRACK_ID, paths))
    assert _run(bundle, None) == _run(bundle, StaticEnvironment())


def test_the_static_environment_is_the_default(frozen_package):
    _, paths = frozen_package
    bundle = _bundle_on(load_track(SYNTHETIC_TRACK_ID, paths))
    sim = Simulator().reset(bundle, seed=1)
    assert sim.world.environment is DEFAULT_ENVIRONMENT
    assert isinstance(DEFAULT_ENVIRONMENT, EnvironmentField)


def test_conditions_change_the_trajectory_through_the_two_engine_sites(frozen_package):
    _, paths = frozen_package
    bundle = _bundle_on(load_track(SYNTHETIC_TRACK_ID, paths))
    still = _run(bundle, StaticEnvironment())
    windy = _run(bundle, _Headwind())
    assert windy != still
    assert windy[-1][1] < still[-1][1], "a headwind, denser air and less grip must not make the car faster"
    assert windy[-1][0] < still[-1][0]


def test_an_unknown_corridor_disables_the_lateral_degree_of_freedom(frozen_package):
    _, paths = frozen_package
    track = load_track(SYNTHETIC_TRACK_ID, paths)
    bundle = _bundle_on(track)
    sim = Simulator().reset(bundle, seed=3)
    action = DriverAction(throttle=1.0, brake=0.0, target_lateral_d_m=3.0)
    for _ in range(100):
        sim.step({bundle.scenario.ego_car_id: action}, 0.02)
    ego = sim.world.cars[bundle.scenario.ego_car_id]
    assert abs(ego.lateral_d_m) < 1e-6, (
        "no surveyed corridor: the car holds the centreline, not an invented edge"
    )


def test_a_validated_corridor_restores_lateral_motion(frozen_package_with_corridor):
    _, paths = frozen_package_with_corridor
    track = load_track(SYNTHETIC_TRACK_ID, paths)
    assert track.lateral_geometry_surveyed is True
    assert track.width_at(50.0) == pytest.approx(12.0)
    bundle = _bundle_on(track)
    sim = Simulator().reset(bundle, seed=3)
    action = DriverAction(throttle=1.0, brake=0.0, target_lateral_d_m=3.0)
    for _ in range(100):
        sim.step({bundle.scenario.ego_car_id: action}, 0.02)
    assert sim.world.cars[bundle.scenario.ego_car_id].lateral_d_m > 1.0


def test_parameter_provenance_on_the_compiled_source_is_honest(frozen_package):
    _, paths = frozen_package
    track = load_track(SYNTHETIC_TRACK_ID, paths)
    assert isinstance(track.timing_line_s_m, Parameter)
    mu = track.segments[0].mu
    assert mu.verification.value == "synthetic_assumption", "reference mu is not a measurement"
    assert "reference-mu" in mu.source
