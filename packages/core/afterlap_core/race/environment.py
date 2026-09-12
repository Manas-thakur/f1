from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from afterlap_contracts import DeploymentProfile

from .session import RaceSession
from .settings import RaceSettings

PROFILES = tuple(DeploymentProfile)
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

    def __init__(self, settings: RaceSettings | None = None, *, automatic_profiles: bool = False) -> None:
        self.settings = settings or RaceSettings()
        self.action_space = spaces.Discrete(len(PROFILES))
        self.observation_space = spaces.Box(-5, 5, shape=(40,), dtype=np.float32)
        self.session: RaceSession | None = None
        self.previous_action: int | None = None
        self.automatic_profiles = automatic_profiles
        self._seeded = False

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if seed is not None and not 0 <= seed <= 2**32 - 1:
            raise ValueError("episode seed must be a 32-bit unsigned integer")
        if seed is not None or not self._seeded:
            effective = self.settings.seed if seed is None else seed
            super().reset(seed=effective)
            self._seeded = True
        else:
            super().reset(seed=None)
            effective = int(self.np_random.integers(0, 2**32))
        settings = self.settings.model_copy(update={"seed": effective})
        self.session = RaceSession(settings)
        self.previous_action = None
        return encode(self.session), {"environment_version": "race-bms-v1", "episode_seed": effective}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.session is None or self.session.done or "car-01" in self.session.finishes:
            raise RuntimeError("reset is required before stepping")
        if not self.action_space.contains(action):
            raise ValueError("action must name one of the five deployment profiles")
        session = self.session
        if not self.automatic_profiles:
            session.bms_profiles["car-01"] = PROFILES[action]
        start = session.simulator.session_time_s
        while session.simulator.session_time_s < start + 1 - 1e-9:
            session.advance(min(session.settings.dt_s, start + 1 - session.simulator.session_time_s))
            if session.done or "car-01" in session.finishes:
                break
        elapsed = session.simulator.session_time_s - start
        finished = "car-01" in session.finishes
        failed = session.status == "failed"
        changed = (
            not self.automatic_profiles
            and self.previous_action is not None
            and self.previous_action != action
        )
        reward = -elapsed - 0.1 * changed
        position = None
        if failed:
            reward -= 20000
        elif finished:
            position = 1 + sum(t < session.finishes["car-01"] for t in session.finishes.values())
            reward -= 30 * (position - 1)
        self.previous_action = int(action)
        info = {
            "environment_version": "race-bms-v1",
            "episode_seed": session.settings.seed,
            "elapsed_s": elapsed,
            "finish_position": position,
            "failure": session.failure,
            "requested_profile": "automatic" if self.automatic_profiles else PROFILES[action].value,
        }
        return encode(session), float(reward), finished or failed, session.status == "truncated", info
