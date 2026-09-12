from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..simulation.config import InitialCarState, ScenarioBundle, load_car, load_scenario
from .circuit import assumed, circuit
from .settings import RaceSettings


@dataclass(frozen=True)
class RaceWeather:
    temperature_k: float
    wind_mps: float

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        return 101325 / (287.05 * self.temperature_k)

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        return self.wind_mps * math.cos(heading_rad)

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        return 1.0

    @property
    def describes(self) -> str:
        return f"synthetic constant weather: {self.temperature_k} K, wind {self.wind_mps} m/s"


def race_bundle(settings: RaceSettings) -> ScenarioBundle:
    template = load_scenario("oval-low-energy")
    baseline = load_car("synthetic-2026")
    track, _ = circuit(settings.circuit, settings.wetness)
    rng = np.random.default_rng(settings.seed)
    cars = {}
    states = {}
    drivers = {}
    policies = {}
    for index in range(settings.cars):
        car_id = f"car-{index + 1:02d}"
        factor = float(rng.uniform(0.94, 1.06))
        car = baseline.model_copy(
            update={
                "id": f"race-car-{settings.seed}-{index}",
                "mass_kg": assumed(float(rng.uniform(780, 830)), "kg"),
                "cda_m2": assumed(float(rng.uniform(1.05, 1.3)), "m^2"),
                "cla_m2": assumed(float(rng.uniform(3.8, 4.8)), "m^2"),
                "max_tractive_force_n": assumed(float(rng.uniform(16500, 19000)), "N"),
                "ice_power_map": tuple(
                    point.model_copy(
                        update={
                            "power_w": assumed(point.power_w.value * factor, "W"),
                        }
                    )
                    for point in baseline.ice_power_map
                ),
                "ambient_temperature_k": assumed(settings.temperature_k, "K"),
            }
        )
        cars[car_id] = car
        states[car_id] = InitialCarState(
            progress_m=assumed(200 - index * 10, "m"),
            speed_mps=assumed(float(rng.uniform(12, 16)), "m/s"),
            energy_j=assumed(float(rng.uniform(2.4e6, 3.8e6)), "J"),
            temperature_k=assumed(settings.temperature_k + 5, "K"),
            lateral_d_m=assumed(2.5 if index % 2 else -2.5, "m"),
        )
        drivers[car_id] = template.drivers["own"].model_copy(
            update={
                "reaction_delay_mean_s": assumed(float(rng.uniform(0.12, 0.25)), "s"),
            }
        )
        if index:
            policies[car_id] = template.opponent_policies["rival"]
    scenario = template.model_copy(
        update={
            "id": f"race-{settings.circuit}-{settings.seed}",
            "track_id": track.id,
            "cars": {car_id: car.id for car_id, car in cars.items()},
            "ego_car_id": "car-01",
            "initial_states": states,
            "drivers": drivers,
            "opponent_policies": policies,
            "seed": settings.seed,
            "duration_s": assumed(settings.time_limit_s, "s"),
            "gap_ahead_s": None,
            "evaluation_checkpoints": track.checkpoint_ids,
            "retention_checkpoint_id": "sector-2",
            "observation": template.observation.model_copy(update={"delay_s": assumed(0.1, "s")}),
        }
    )
    return ScenarioBundle(scenario=scenario, track=track, car_configs=cars)
