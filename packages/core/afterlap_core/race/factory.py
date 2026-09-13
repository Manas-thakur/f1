from __future__ import annotations

from ..rng import StreamRegistry
from ..simulation.config import InitialCarState, ScenarioBundle, load_car, load_scenario
from .circuit import assumed, circuit
from .settings import RaceSettings


def race_bundle(settings: RaceSettings) -> ScenarioBundle:
    template = load_scenario("oval-low-energy")
    baseline = load_car("synthetic-2026")
    track, _ = circuit(settings.circuit, 0)
    streams = StreamRegistry(settings.seed)
    variation = settings.variability
    scale = variation.strength * variation.vehicle_scale
    cars = {}
    states = {}
    drivers = {}
    policies = {}
    for index in range(settings.cars):
        car_id = f"car-{index + 1:02d}"
        rng = streams.stream(f"vehicle:{car_id}")
        setup = float(rng.uniform(-1, 1)) * scale
        factor = 1 + float(rng.uniform(-0.06, 0.06)) * scale
        traits = variation.sample_driver(streams, car_id)
        car = baseline.model_copy(
            update={
                "id": f"race-car-{settings.seed}-{index}",
                "mass_kg": assumed(805 + float(rng.uniform(-25, 25)) * scale, "kg"),
                "cda_m2": assumed(1.175 + 0.125 * setup, "m^2"),
                "cla_m2": assumed(4.3 + 0.5 * setup, "m^2"),
                "max_tractive_force_n": assumed(17750 + float(rng.uniform(-1250, 1250)) * scale, "N"),
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
            speed_mps=assumed(14 + float(rng.uniform(-2, 2)) * scale, "m/s"),
            energy_j=assumed(3.1e6, "J"),
            temperature_k=assumed(settings.temperature_k + 5, "K"),
            lateral_d_m=assumed(2.5 if index % 2 else -2.5, "m"),
        )
        drivers[car_id] = template.drivers["own"].model_copy(
            update={
                "reaction_delay_mean_s": assumed(traits.reaction_s, "s"),
                "braking_envelope_fraction": assumed(traits.braking_fraction, "1"),
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
            "observation": template.observation.model_copy(
                update={
                    "delay_s": assumed(0.1, "s"),
                    "noise_sigma": {
                        name: assumed(
                            parameter.value * variation.strength * variation.sensor_scale, parameter.unit
                        )
                        for name, parameter in template.observation.noise_sigma.items()
                    },
                }
            ),
        }
    )
    return ScenarioBundle(scenario=scenario, track=track, car_configs=cars)
