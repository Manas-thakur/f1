from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from afterlap_core.simulation import ScenarioBundle, load_bundle

if TYPE_CHECKING:
    from afterlap_core.config import Parameter


def _param(template: Parameter, value: float) -> Parameter:
    return template.model_copy(update={"value": float(value)})


def build_bundle(
    scenario_id: str = "two-straight-counterattack",
    *,
    reaction_delay_s: float | None = 0.0,
    observation_delay_s: float | None = None,
    energies_j: dict[str, float] | None = None,
    speeds_mps: dict[str, float] | None = None,
    progress_m: dict[str, float] | None = None,
    expose_rival_energy: bool | None = None,
    energy_channel_available: bool | None = None,
    noise_free: bool = False,
) -> ScenarioBundle:

    bundle = load_bundle(scenario_id)
    scenario = bundle.scenario
    updates: dict[str, Any] = {}

    if reaction_delay_s is not None:
        updates["drivers"] = {
            car_id: driver.model_copy(
                update={
                    "reaction_delay_mean_s": _param(driver.reaction_delay_mean_s, reaction_delay_s),
                    "reaction_delay_std_s": _param(driver.reaction_delay_std_s, 0.0),
                    "execution_jitter_s": _param(driver.execution_jitter_s, 0.0),
                }
            )
            for car_id, driver in scenario.drivers.items()
        }

    observation_updates: dict[str, Any] = {}
    if observation_delay_s is not None:
        observation_updates["delay_s"] = _param(scenario.observation.delay_s, observation_delay_s)
    if expose_rival_energy is not None:
        observation_updates["expose_rival_energy"] = expose_rival_energy
    if energy_channel_available is not None:
        observation_updates["energy_channel_available"] = energy_channel_available
    if noise_free:
        observation_updates["noise_sigma"] = {
            name: _param(param, 0.0) for name, param in scenario.observation.noise_sigma.items()
        }
    if observation_updates:
        updates["observation"] = scenario.observation.model_copy(update=observation_updates)

    if energies_j or speeds_mps or progress_m:
        states = {}
        for car_id, state in scenario.initial_states.items():
            state_updates: dict[str, Any] = {}
            if energies_j and car_id in energies_j:
                state_updates["energy_j"] = _param(state.energy_j, energies_j[car_id])
            if speeds_mps and car_id in speeds_mps:
                state_updates["speed_mps"] = _param(state.speed_mps, speeds_mps[car_id])
            if progress_m and car_id in progress_m:
                state_updates["progress_m"] = _param(state.progress_m, progress_m[car_id])
            states[car_id] = state.model_copy(update=state_updates) if state_updates else state
        updates["initial_states"] = states
        updates["gap_ahead_s"] = None

    if not updates:
        return bundle
    return ScenarioBundle(
        scenario=scenario.model_copy(update=updates),
        track=bundle.track,
        car_configs=bundle.car_configs,
    )


@pytest.fixture
def loop_bundle() -> ScenarioBundle:
    return build_bundle()
