from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from afterlap_contracts import DeploymentProfile

from .control import DriverControl
from .diversity import episode_race_settings, next_episode_seed
from .session import RaceSession
from .settings import RaceSettings

PROFILES = tuple(DeploymentProfile)
ACTION_FIELDS = (
    "driver_mode",
    "deployment_profile",
    "pace_scale",
    "target_lateral_d_m",
    "low_drag",
    "manual_pedals",
    "throttle",
    "brake",
)
ACTION_LOW = np.full(len(ACTION_FIELDS), -1, dtype=np.float32)
ACTION_HIGH = np.full(len(ACTION_FIELDS), 1, dtype=np.float32)
FEATURES = (
    "speed_mps",
    "acceleration_mps2",
    "progress_m",
    "battery_energy_j",
    "battery_temperature_k",
    "recharge_this_lap_j",
    "electrical_power_w",
    "lateral_d_m",
)
SCALES = (100, 50, 10000, 4e6, 350, 9e6, 350000, 6)


def decode_action(action: np.ndarray) -> DriverControl:
    values = np.asarray(action, dtype=np.float32)
    if values.shape != (len(ACTION_FIELDS),) or not np.isfinite(values).all():
        raise ValueError(f"action must contain {len(ACTION_FIELDS)} finite normalized values")
    if np.any(values < ACTION_LOW) or np.any(values > ACTION_HIGH):
        raise ValueError("action values must be normalized to [-1, 1]")
    profile_index = min(len(PROFILES) - 1, int((float(values[1]) + 1) * len(PROFILES) / 2))
    if values[0] < 0:
        return DriverControl(mode="automatic", profile=PROFILES[profile_index])
    manual = values[5] >= 0
    return DriverControl(
        mode="direct",
        profile=PROFILES[profile_index],
        pace_scale=0.85 + 0.15 * float(values[2]),
        target_lateral_d_m=5 * float(values[3]),
        low_drag=bool(values[4] >= 0),
        throttle=(float(values[6]) + 1) / 2 if manual else None,
        brake=(float(values[7]) + 1) / 2 if manual else None,
    )


def encode_control(control: DriverControl) -> np.ndarray:
    profile_index = PROFILES.index(control.profile)
    manual = control.throttle is not None
    return np.asarray(
        [
            1 if control.mode == "direct" else -1,
            -1 + (2 * profile_index + 1) / len(PROFILES),
            (control.pace_scale - 0.85) / 0.15,
            control.target_lateral_d_m / 5,
            1 if control.low_drag else -1,
            1 if manual else -1,
            2 * control.throttle - 1 if control.throttle is not None else -1,
            2 * control.brake - 1 if control.brake is not None else -1,
        ],
        dtype=np.float32,
    )


def encode(session: RaceSession) -> np.ndarray:
    observation = session.simulator.observe(car_id="car-01")["car-01"]
    values = [observation.channels.get(key) for key in FEATURES]
    scales = list(SCALES)
    progress = observation.channels.get("progress_m")
    for distance in (0, 100, 250, 500, 1000, 1500):
        values.append(None if progress is None else session.track.curvature_at(progress + distance))
        scales.append(0.05)
    for rival in (observation.rival_ahead(), observation.rival_behind()):
        for key, scale in (("relative_progress_m", 100), ("relative_speed_mps", 30), ("lateral_d_m", 6)):
            values.append(None if rival is None else rival.get(key))
            scales.append(scale)
    normalized = [
        0 if value is None else np.clip(value / scale, -5, 5)
        for value, scale in zip(values, scales, strict=True)
    ]
    return np.asarray([*normalized, *(float(value is not None) for value in values)], dtype=np.float32)


class RaceEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, settings: RaceSettings | None = None) -> None:
        self.settings = settings or RaceSettings()
        self.action_space = spaces.Box(ACTION_LOW, ACTION_HIGH, dtype=np.float32)
        self.observation_space = spaces.Box(-5, 5, shape=(40,), dtype=np.float32)
        self.session: RaceSession | None = None
        self.previous_control: DriverControl | None = None

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        episode_seed = next_episode_seed(self.np_random, seed)
        settings = episode_race_settings(self.settings, episode_seed)
        self.session = RaceSession(settings)
        self.previous_control = None
        return encode(self.session), {
            "environment_version": "race-control-v2",
            "episode_seed": episode_seed,
            "circuit": settings.circuit,
        }

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.session is None or self.session.done or "car-01" in self.session.finishes:
            raise RuntimeError("reset is required before stepping")
        if not self.action_space.contains(action):
            raise ValueError(f"action must contain {len(ACTION_FIELDS)} normalized values")
        session = self.session
        control = decode_action(action)
        if control.mode == "automatic":
            session.control("car-01", None)
            session.bms_profiles["car-01"] = control.profile
        else:
            session.bms_profiles.pop("car-01", None)
            session.control("car-01", control.driver_action())
        start = session.simulator.session_time_s
        while session.simulator.session_time_s < start + 1 - 1e-9:
            session.advance(min(session.settings.dt_s, start + 1 - session.simulator.session_time_s))
            if session.done or "car-01" in session.finishes:
                break
        elapsed = session.simulator.session_time_s - start
        finished = "car-01" in session.finishes
        failed = session.status == "failed"
        changed = self.previous_control is not None and self.previous_control != control
        reward = -elapsed - 0.1 * changed
        position = None
        if failed:
            reward -= 20000
        elif finished:
            position = 1 + sum(t < session.finishes["car-01"] for t in session.finishes.values())
            reward -= 30 * (position - 1)
        self.previous_control = control
        info = {
            "environment_version": "race-control-v2",
            "elapsed_s": elapsed,
            "finish_position": position,
            "failure": session.failure,
            "requested_control": control.model_dump(mode="json"),
            "boost_evaluation": session.storyline.confusion.payload(),
            "tyres": session.tyres["car-01"].payload(session._visual_lateral("car-01")),
        }
        return encode(session), float(reward), finished or failed, session.status == "truncated", info
