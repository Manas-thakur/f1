from __future__ import annotations

import argparse
import itertools
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.circuit import assumed
from afterlap_core.simulation.config import load_car
from afterlap_core.simulation.policies import DriverAction
from afterlap_core.simulation.track_source import StaticEnvironment


def experiment(seed: int, case: str, duration: float, dt: float = 0.01) -> dict[str, Any]:
    settings = RaceSettings(
        circuit="monza",
        seed=seed,
        cars=3 if case == "blocked" else 2,
        dt_s=dt,
        time_limit_s=duration,
        wake=case != "no-wake",
    )
    start = time.perf_counter()
    session = RaceSession(settings)
    cold = time.perf_counter() - start
    world = session.simulator.world
    baseline = load_car("synthetic-2026")
    cars = dict.fromkeys(world.cars, baseline)
    initial = {}
    for index, car in enumerate(world.cars):
        initial[car] = world.bundle.scenario.initial_states[car].model_copy(
            update={
                "progress_m": assumed(3900 - 30 * index, "m"),
                "speed_mps": assumed(34 if index == 0 else 38, "m/s"),
                "lateral_d_m": assumed(0 if index < 2 else -3, "m"),
                "energy_j": assumed(3e6, "J"),
            }
        )
    if case == "blocked":
        initial["car-03"] = initial["car-03"].model_copy(update={"progress_m": assumed(3870, "m")})
    observation = world.bundle.scenario.observation.model_copy(update={"noise_sigma": {}, "quantisation": {}})
    drivers = {
        car: driver.model_copy(update={"reaction_delay_mean_s": assumed(0.18, "s")})
        for car, driver in world.driver_configs.items()
    }
    scenario = world.bundle.scenario.model_copy(
        update={"initial_states": initial, "observation": observation, "drivers": drivers}
    )
    bundle = world.bundle.model_copy(update={"scenario": scenario, "car_configs": cars})
    session.bundle = bundle
    session.simulator.reset(bundle, environment=StaticEnvironment(), wake=session.simulator.wake_model)
    world = session.simulator.world
    world.policies.clear()
    session.lanes = {car: initial[car].lateral_d_m.value for car in world.cars}
    for car, driver in getattr(session, "drivers", {}).items():
        driver.lane = session.lanes[car]
        driver.traits = driver.traits.model_copy(update={"preferred_line_m": 0, "reaction_s": 0.18})
    for car, lane in session.lanes.items():
        world.active_actions[car] = DriverAction(target_lateral_d_m=lane, throttle=0, brake=0)
    rows = []
    start = time.perf_counter()
    while not session.done:
        now = session.simulator.session_time_s
        leader = world.cars["car-01"]
        target_speed = 34 if case != "abort" or now < 2 else 60
        force = (
            baseline.mass_kg.value * (target_speed - leader.speed_mps)
            + leader.drag_force_n
            + leader.rolling_force_n
        )
        session.control(
            "car-01",
            DriverAction(
                profile=DeploymentProfile.HARVEST,
                target_lateral_d_m=0,
                throttle=max(
                    0,
                    min(
                        1,
                        force
                        * max(1, leader.speed_mps)
                        / (baseline.ice_power_at(leader.speed_mps) * baseline.drivetrain_efficiency.value),
                    ),
                ),
                brake=max(0, min(1, -force / baseline.max_brake_force_n.value)),
            ),
        )
        if case == "blocked":
            session.control(
                "car-03",
                DriverAction(profile=DeploymentProfile.HARVEST, target_lateral_d_m=-3, throttle=0.15),
            )
        session.advance(0.1)
        follower = world.cars["car-02"]
        action = world.active_actions["car-02"]
        rows.append(
            {
                "t": world.race.session_time_s,
                "gap": leader.progress_m - follower.progress_m,
                "speed": follower.speed_mps,
                "relative_speed": follower.speed_mps - leader.speed_mps,
                "accel": follower.acceleration_mps2,
                "brake": getattr(follower, "applied_brake", action.brake_floor),
                "lateral": follower.lateral_d_m,
                "target": action.target_lateral_d_m,
                "state": action.label,
            }
        )
    elapsed = time.perf_counter() - start
    gap = np.array([row["gap"] for row in rows])
    acceleration = np.array([row["accel"] for row in rows])
    return {
        "seed": seed,
        "case": case,
        "dt_s": dt,
        "cold_s": cold,
        "wall_s": elapsed,
        "sim_s": world.race.session_time_s,
        "status": session.status,
        "failure": session.failure,
        "gap_min_m": float(gap.min()),
        "gap_std_m": float(gap.std()),
        "jerk_rms_mps3": float(np.sqrt(np.mean((np.diff(acceleration) / 0.1) ** 2)))
        if len(acceleration) > 1
        else None,
        "state_changes": sum(a["state"] != b["state"] for a, b in itertools.pairwise(rows)),
        "events": dict(Counter(event.kind for event in world.passes)),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Matched physical pass and abort experiments; privileged offline evidence"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37])
    parser.add_argument("--cases", nargs="+", default=["pass", "abort", "blocked", "no-wake"])
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--dt", type=float, default=0.01)
    args = parser.parse_args()
    results = []
    for case in args.cases:
        for seed in args.seeds:
            result = experiment(seed, case, args.duration, args.dt)
            results.append(result)
            print(json.dumps({key: value for key, value in result.items() if key != "rows"}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(results, output, allow_nan=False)


if __name__ == "__main__":
    main()
