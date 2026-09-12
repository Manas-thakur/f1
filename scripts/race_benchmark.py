from __future__ import annotations

import argparse
import json
import platform
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from afterlap_core.race import RaceSession, RaceSettings


def run(settings: RaceSettings) -> dict[str, Any]:
    start = time.perf_counter()
    session = RaceSession(settings)
    cold = time.perf_counter() - start
    rows = []
    start = time.perf_counter()
    while not session.done:
        session.advance(0.1)
        world = session.simulator.world
        for car_id, state in world.cars.items():
            action = world.active_actions[car_id]
            wake = session.simulator.wake_effect(car_id)
            rows.append(
                {
                    "time_s": session.simulator.session_time_s,
                    "car": car_id,
                    "progress_m": state.progress_m,
                    "speed_mps": state.speed_mps,
                    "acceleration_mps2": state.acceleration_mps2,
                    "lateral_m": state.lateral_d_m,
                    "target_m": action.target_lateral_d_m,
                    "brake_floor": action.brake_floor,
                    "requested_throttle": action.throttle,
                    "requested_brake": action.brake,
                    "applied_throttle": getattr(state, "applied_throttle", None),
                    "applied_brake": getattr(state, "applied_brake", None),
                    "intent": action.label,
                    "profile": state.active_profile.value,
                    "deploy_w": state.deploy_power_dc_w,
                    "grip_multiplier": world.environment.grip_multiplier(
                        state.s_m, world.race.session_time_s
                    ),
                    "wake": None if wake is None else wake.shielding,
                }
            )
    wall = time.perf_counter() - start
    ego = [row for row in rows if row["car"] == "car-01"]
    jerk = np.diff([row["acceleration_mps2"] for row in ego]) / 0.1
    return {
        "hardware": platform.platform(),
        "manifest": session.manifest(),
        "cold_start_s": cold,
        "wall_s": wall,
        "simulated_s": session.simulator.session_time_s,
        "simulated_s_per_wall_s": session.simulator.session_time_s / wall,
        "status": session.status,
        "failure": session.failure,
        "events": dict(Counter(event.kind for event in session.simulator.world.passes)),
        "ego_jerk_rms_mps3": float(np.sqrt(np.mean(jerk**2))) if len(jerk) else None,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline truth diagnostics, never actor features")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = (
        RaceSettings.model_validate_json(args.settings.read_text())
        if args.settings
        else RaceSettings(circuit="monza", cars=2, time_limit_s=10)
    )
    result = run(settings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, allow_nan=False)
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "manifest"}}))


if __name__ == "__main__":
    main()
