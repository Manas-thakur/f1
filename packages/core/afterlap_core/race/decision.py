from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from afterlap_contracts import DeploymentProfile, Quality

from ..simulation.observation import Observation
from .session import RaceSession
from .settings import RaceSettings

DECISION_PROFILES = tuple(DeploymentProfile)
PREVIEW_OFFSETS_M = (0.0, 50.0, 100.0, 200.0, 400.0)
OWN_FEATURES = (
    ("speed_mps", 100.0),
    ("acceleration_mps2", 15.0),
    ("battery_energy_j", 4.0e6),
    ("battery_temperature_k", 350.0),
    ("recharge_this_lap_j", 8.5e6),
    ("electrical_power_w", 350000.0),
    ("boost_this_lap_s", 30.0),
    ("deployed_this_lap_j", 8.5e6),
    ("grip_multiplier", 1.0),
    ("lateral_d_m", 6.0),
)
CONTEXT_FEATURES = (
    ("lap_fraction", 1.0),
    ("race_fraction", 1.0),
    ("wetness", 1.0),
    ("ambient_temperature_k", 350.0),
    ("wind_mps", 20.0),
    ("track_mu", 2.0),
    ("track_width_m", 20.0),
    ("time_remaining_s", 14400.0),
)
RIVAL_FEATURES = (
    ("relative_progress_m", 150.0),
    ("relative_speed_mps", 40.0),
    ("gap_s", 5.0),
    ("lateral_d_m", 6.0),
    ("speed_mps", 100.0),
)
FEATURE_NAMES = (
    tuple(name for name, _ in OWN_FEATURES)
    + tuple(name for name, _ in CONTEXT_FEATURES)
    + tuple(f"curvature_{int(offset)}m" for offset in PREVIEW_OFFSETS_M)
    + tuple(f"racing_line_{int(offset)}m" for offset in PREVIEW_OFFSETS_M)
    + tuple(f"ahead_{name}" for name, _ in RIVAL_FEATURES)
    + tuple(f"behind_{name}" for name, _ in RIVAL_FEATURES)
)
FEATURE_SCALES = (
    tuple(scale for _, scale in OWN_FEATURES)
    + tuple(scale for _, scale in CONTEXT_FEATURES)
    + tuple(0.05 for _ in PREVIEW_OFFSETS_M)
    + tuple(6.0 for _ in PREVIEW_OFFSETS_M)
    + tuple(scale for _, scale in RIVAL_FEATURES) * 2
)
OBSERVATION_SIZE = len(FEATURE_NAMES) * 2


def decision_schema() -> dict[str, Any]:
    return {
        "environment_version": "boost-decision-v1",
        "observation_features": FEATURE_NAMES,
        "observation_scales": FEATURE_SCALES,
        "observation_size": OBSERVATION_SIZE,
        "missing_value_encoding": "zero value plus availability mask",
        "actions": [profile.value for profile in DECISION_PROFILES],
        "authority": "energy deployment profile only",
    }


@dataclass(frozen=True, slots=True)
class BoostRecommendation:
    car_id: str
    mode: str
    source: str
    confidence: float | None
    manual_available: bool
    manual_reason: str
    boost_available: bool
    overtake_available: bool
    risk_score: float
    reward_score: float
    risk_reward_ratio: float | None
    opportunity: bool
    target_car_id: str | None
    gap_ahead_s: float | None
    straight_score: float
    reason: str
    regulation_basis: str
    observed_at_s: float

    @property
    def can_apply(self) -> bool:
        return self.boost_available and self.mode in {
            DeploymentProfile.PUSH.value,
            DeploymentProfile.OVERTAKE.value,
        }

    def payload(self) -> dict[str, Any]:
        return {**asdict(self), "can_apply": self.can_apply}


def _racing_line_at(session: RaceSession, car_id: str, progress_m: float) -> float | None:
    racing_line = session.drivers[car_id].racing_line
    return None if racing_line is None else racing_line.target_at(progress_m)


def decision_values(session: RaceSession, observation: Observation) -> list[float | None]:
    channels = observation.channels
    progress = channels.get("progress_m")
    track_length = float(observation.context.get("track_length_m", session.track.length))
    lap_fraction = None if progress is None else float(progress) % track_length / track_length
    race_distance = session.settings.laps * track_length
    race_fraction = None if progress is None else min(1.0, float(progress) / race_distance)
    time_remaining = max(0.0, session.settings.time_limit_s - observation.delivered_at_s)
    own = [channels.get(name) for name, _ in OWN_FEATURES]
    context: list[float | None] = [
        lap_fraction,
        race_fraction,
        session.settings.wetness,
        session.settings.temperature_k,
        session.settings.wind_mps,
        observation.context.get("mu"),
        observation.context.get("width_m"),
        time_remaining,
    ]
    curvature = [
        None if progress is None else session.track.curvature_at(float(progress) + offset)
        for offset in PREVIEW_OFFSETS_M
    ]
    line = [
        None if progress is None else _racing_line_at(session, observation.car_id, float(progress) + offset)
        for offset in PREVIEW_OFFSETS_M
    ]
    rivals: list[float | None] = []
    for rival in (observation.rival_ahead(), observation.rival_behind()):
        rivals.extend(None if rival is None else rival.get(name) for name, _ in RIVAL_FEATURES)
    return [*own, *context, *curvature, *line, *rivals]


def encode_decision(session: RaceSession, observation: Observation) -> np.ndarray:
    values = decision_values(session, observation)
    normalized = [
        0.0
        if value is None or not math.isfinite(float(value))
        else float(np.clip(float(value) / scale, -5, 5))
        for value, scale in zip(values, FEATURE_SCALES, strict=True)
    ]
    available = [float(value is not None and math.isfinite(float(value))) for value in values]
    return np.asarray([*normalized, *available], dtype=np.float32)


def _nearest_ahead(observation: Observation) -> dict[str, Any] | None:
    rival = observation.rival_ahead()
    return None if rival is None else dict(rival)


def assess_boost(session: RaceSession, observation: Observation) -> BoostRecommendation:
    channels = observation.channels
    speed = channels.get("speed_mps")
    energy = channels.get("battery_energy_j")
    temperature = channels.get("battery_temperature_k")
    acceleration = channels.get("acceleration_mps2")
    boost_latched = channels.get("boost_latched") == 1
    progress = channels.get("progress_m")
    car = session.bundle.car_configs[observation.car_id]
    energy_floor = float(car.battery_energy_min_j.value)
    energy_ceiling = float(car.battery_energy_max_j.value)
    reserve = energy_floor + 0.18 * (energy_ceiling - energy_floor)
    derate_start = float(car.derate_start_temperature_k.value)
    derate_end = float(car.derate_end_temperature_k.value)
    required = observation.quality is Quality.VALID and all(
        value is not None for value in (speed, energy, temperature, progress)
    )
    curvatures = (
        []
        if progress is None
        else [abs(session.track.curvature_at(float(progress) + offset)) for offset in PREVIEW_OFFSETS_M]
    )
    maximum_curvature = max(curvatures, default=0.05)
    straight_score = float(np.clip(1.0 - maximum_curvature / 0.012, 0.0, 1.0))
    ahead = _nearest_ahead(observation)
    raw_gap = None if ahead is None else float(ahead["gap_s"])
    gap = None if raw_gap is None or not math.isfinite(raw_gap) else abs(raw_gap)
    closing = 0.0 if ahead is None else max(0.0, -float(ahead["relative_speed_mps"]))
    opportunity = bool(ahead is not None and gap is not None and gap <= 1.5 and closing >= 0.2)
    energy_margin = 0.0 if energy is None else float(np.clip((float(energy) - reserve) / 800000.0, 0, 1))
    thermal_margin = (
        0.0
        if temperature is None
        else float(np.clip((derate_end - float(temperature)) / max(1.0, derate_end - derate_start), 0, 1))
    )
    manual_available = bool(
        required and float(energy) > reserve and float(temperature) < derate_end and not boost_latched
    )
    boost_available = bool(
        manual_available and float(speed) >= 50 / 3.6 and (acceleration is None or float(acceleration) > -2.0)
    )
    wet_risk = session.settings.wetness
    corner_risk = 1.0 - straight_score
    proximity_risk = 0.0 if gap is None else float(np.clip((0.45 - gap) / 0.45, 0, 1))
    thermal_risk = 1.0 - thermal_margin
    reserve_risk = 1.0 - energy_margin
    risk = float(
        np.clip(
            0.30 * corner_risk
            + 0.22 * wet_risk
            + 0.20 * proximity_risk
            + 0.14 * thermal_risk
            + 0.14 * reserve_risk,
            0,
            1,
        )
    )
    gap_value = 0.0 if gap is None else float(np.clip((1.5 - gap) / 1.5, 0, 1))
    closing_value = float(np.clip(closing / 10.0, 0, 1))
    reward = float(
        np.clip(
            (0.48 * gap_value + 0.22 * closing_value + 0.20 * straight_score + 0.10 * energy_margin)
            * float(opportunity),
            0,
            1,
        )
    )
    ratio = None if reward <= 0 else reward / max(0.05, risk)
    if not required:
        manual_reason = "Required delayed telemetry is unavailable"
    elif boost_latched:
        manual_reason = "Boost must be released before recovered energy can be deployed"
    elif energy is not None and float(energy) <= reserve:
        manual_reason = "Battery energy reserve is unavailable"
    elif temperature is not None and float(temperature) >= derate_end:
        manual_reason = "Battery thermal limit is active"
    else:
        manual_reason = "Manual boost is available"
    if not required:
        mode = DeploymentProfile.NEUTRAL.value
        reason = "Required delayed telemetry is unavailable"
    elif boost_latched:
        mode = DeploymentProfile.HARVEST.value
        reason = "Boost must be released before recovered energy can be deployed"
    elif not boost_available:
        mode = (
            DeploymentProfile.HARVEST.value
            if energy is not None and float(energy) <= reserve
            else DeploymentProfile.CONSERVE.value
        )
        reason = "Boost is held for battery, thermal, braking, or launch constraints"
    elif opportunity and reward > risk and straight_score >= 0.45:
        mode = DeploymentProfile.PUSH.value
        reason = "Closing opportunity has positive modeled reward after risk"
    elif energy_margin < 0.35:
        mode = DeploymentProfile.CONSERVE.value
        reason = "Energy reserve is more valuable than immediate deployment"
    elif straight_score >= 0.8 and acceleration is not None and float(acceleration) > 0.5:
        mode = DeploymentProfile.PUSH.value
        reason = "Straight-line acceleration window supports deployment"
    elif corner_risk >= 0.6 or wet_risk >= 0.5:
        mode = DeploymentProfile.HARVEST.value
        reason = "Corner or wet-condition risk favors recovery"
    else:
        mode = DeploymentProfile.NEUTRAL.value
        reason = "No high-value deployment or recovery window is present"
    return BoostRecommendation(
        car_id=observation.car_id,
        mode=mode,
        source="rules_baseline",
        confidence=None,
        manual_available=manual_available,
        manual_reason=manual_reason,
        boost_available=boost_available,
        overtake_available=False,
        risk_score=risk,
        reward_score=reward,
        risk_reward_ratio=ratio,
        opportunity=opportunity,
        target_car_id=None if ahead is None else str(ahead["car_id"]),
        gap_ahead_s=gap,
        straight_score=straight_score,
        reason=reason,
        regulation_basis="FIA 2026 B7.2 and C5.2.7-10; event Overtake activation data unavailable",
        observed_at_s=observation.observed_at_s,
    )


class BoostDecisionEnv(gym.Env[np.ndarray, int]):
    metadata = {"render_modes": []}

    def __init__(self, settings: RaceSettings | None = None, decision_interval_s: float = 0.5) -> None:
        self.settings = settings or RaceSettings()
        self.decision_interval_s = decision_interval_s
        self.action_space = spaces.Discrete(len(DECISION_PROFILES))
        self.observation_space = spaces.Box(-5, 5, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self.session: RaceSession | None = None
        self.previous_action: int | None = None
        self.last_rank = 1

    def _rank(self) -> int:
        assert self.session is not None
        own = self.session.simulator.world.cars["car-01"].progress_m
        return 1 + sum(
            state.progress_m > own
            for car_id, state in self.session.simulator.world.cars.items()
            if car_id != "car-01"
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        effective = self.settings.seed if seed is None else seed
        self.session = RaceSession(self.settings.model_copy(update={"seed": effective}))
        self.previous_action = None
        self.last_rank = self._rank()
        observation = self.session.observations()["car-01"]
        return encode_decision(self.session, observation), {"environment_version": "boost-decision-v1"}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.session is None or self.session.done or "car-01" in self.session.finishes:
            raise RuntimeError("reset is required before stepping")
        if not self.action_space.contains(action):
            raise ValueError("action must select a deployment profile")
        session = self.session
        before_observation = session.observations()["car-01"]
        assessment = assess_boost(session, before_observation)
        before_progress = session.simulator.world.cars["car-01"].progress_m
        before_deployed = session.simulator.world.ledgers["car-01"].deployed_dc_j
        before_passes = len(session.simulator.world.passes)
        profile = DECISION_PROFILES[int(action)]
        session.bms_profiles["car-01"] = profile
        start = session.simulator.session_time_s
        while session.simulator.session_time_s < start + self.decision_interval_s - 1e-9:
            session.advance(
                min(
                    session.settings.dt_s,
                    start + self.decision_interval_s - session.simulator.session_time_s,
                )
            )
            if session.done or "car-01" in session.finishes:
                break
        state = session.simulator.world.cars["car-01"]
        progress_delta = max(0.0, state.progress_m - before_progress)
        deployed_j = max(0.0, session.simulator.world.ledgers["car-01"].deployed_dc_j - before_deployed)
        rank = self._rank()
        positions_gained = max(0, self.last_rank - rank)
        positions_lost = max(0, rank - self.last_rank)
        new_passes = max(0, len(session.simulator.world.passes) - before_passes)
        boosting = profile in {DeploymentProfile.PUSH, DeploymentProfile.OVERTAKE}
        reward = progress_delta / 100.0 + 10.0 * positions_gained - 12.0 * positions_lost
        reward += 2.5 * new_passes
        reward -= deployed_j / 4.0e6
        reward -= 3.0 * assessment.risk_score * float(boosting)
        reward -= 2.0 * float(boosting and not assessment.boost_available)
        reward -= 0.05 * float(self.previous_action is not None and int(action) != self.previous_action)
        if session.status == "failed":
            reward -= 100.0
        elif "car-01" in session.finishes:
            reward += 40.0 - 2.0 * (rank - 1)
        self.previous_action = int(action)
        self.last_rank = rank
        observation = session.observations()["car-01"]
        info = {
            "environment_version": "boost-decision-v1",
            "profile": profile.value,
            "risk_score": assessment.risk_score,
            "reward_score": assessment.reward_score,
            "opportunity": assessment.opportunity,
            "boost_available": assessment.boost_available,
            "deployed_j": deployed_j,
            "positions_gained": positions_gained,
            "positions_lost": positions_lost,
            "passes": new_passes,
            "failure": session.failure,
            "rank": rank,
        }
        terminated = session.status == "failed" or "car-01" in session.finishes
        return (
            encode_decision(session, observation),
            float(reward),
            terminated,
            session.status == "truncated",
            info,
        )


def decision_manifest(session: RaceSession) -> dict[str, Any]:
    return {
        **session.manifest(),
        "environment_version": "boost-decision-v1",
        "observation_features": FEATURE_NAMES,
        "observation_scales": FEATURE_SCALES,
        "observation_size": OBSERVATION_SIZE,
        "missing_value_encoding": "zero value plus availability mask",
        "action_profiles": [profile.value for profile in DECISION_PROFILES],
        "authority": "energy deployment profile only; steering, braking, and racing line stay automatic",
        "reward_version": "boost-risk-reward-v1",
        "regulation_scope": "FIA 2026 base limits; public event-specific Overtake activation unavailable",
    }


class BoostDecisionEngine:
    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path
        self.model: Any | None = None
        self.manifest: dict[str, Any] | None = None
        if policy_path is not None:
            self.manifest = json.loads(policy_path.with_suffix(".manifest.json").read_text())
            for key, expected in (
                ("environment_version", "boost-decision-v1"),
                ("observation_features", list(FEATURE_NAMES)),
                ("observation_size", OBSERVATION_SIZE),
                ("action_profiles", [profile.value for profile in DECISION_PROFILES]),
                ("reward_version", "boost-risk-reward-v1"),
            ):
                if self.manifest.get(key) != expected:
                    raise ValueError(f"incompatible decision policy {key}")
            from stable_baselines3 import PPO

            self.model = PPO.load(policy_path, device="cpu")

    def recommend(self, session: RaceSession, observation: Observation) -> BoostRecommendation:
        baseline = assess_boost(session, observation)
        if self.model is None:
            return baseline
        encoded = encode_decision(session, observation)
        action, _ = self.model.predict(encoded, deterministic=True)
        index = int(np.asarray(action).item())
        probabilities = self._probabilities(encoded)
        profile = DECISION_PROFILES[index]
        if profile is DeploymentProfile.OVERTAKE and not baseline.overtake_available:
            profile = DeploymentProfile.PUSH
        if profile in {DeploymentProfile.PUSH, DeploymentProfile.OVERTAKE} and not baseline.boost_available:
            profile = DeploymentProfile.CONSERVE
        reason = f"PPO selected {profile.value}; safety and 2026 availability guards applied"
        return BoostRecommendation(
            **{
                **asdict(baseline),
                "mode": profile.value,
                "source": "ppo",
                "confidence": probabilities[index],
                "reason": reason,
            }
        )

    def _probabilities(self, observation: np.ndarray) -> list[float]:
        assert self.model is not None
        tensor, _ = self.model.policy.obs_to_tensor(observation)
        distribution = self.model.policy.get_distribution(tensor).distribution
        values = distribution.probs.detach().cpu().numpy()[0]
        return [float(value) for value in values]
