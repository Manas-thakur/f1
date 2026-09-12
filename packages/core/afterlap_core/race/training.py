from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np

from afterlap_contracts import DeploymentProfile

from .decision import (
    DECISION_PROFILES,
    BoostDecisionEnv,
    assess_boost,
    decision_manifest,
)
from .settings import RaceSettings


def _baseline_action(env: BoostDecisionEnv, observation: np.ndarray) -> int:
    del observation
    assert env.session is not None
    measured = env.session.observations()["car-01"]
    recommendation = assess_boost(env.session, measured)
    return DECISION_PROFILES.index(DeploymentProfile(recommendation.mode))


def evaluate_decision_policy(
    model: Any | None,
    settings: RaceSettings,
    episodes: int,
    seed_offset: int = 10000,
) -> dict[str, float | int]:
    episode_rewards: list[float] = []
    final_ranks: list[int] = []
    deployed_mj: list[float] = []
    passes: list[int] = []
    opportunities = 0
    opportunity_boosts = 0
    boosts = 0
    actions = 0
    failures = 0
    for episode in range(episodes):
        env = BoostDecisionEnv(settings)
        observation, _ = env.reset(seed=settings.seed + seed_offset + episode)
        total_reward = 0.0
        total_deployed_j = 0.0
        episode_passes = 0
        while True:
            if model is None:
                action = _baseline_action(env, observation)
            else:
                predicted, _ = model.predict(observation, deterministic=True)
                action = int(np.asarray(predicted).item())
            observation, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            total_deployed_j += float(info["deployed_j"])
            episode_passes += int(info["passes"])
            opportunity = bool(info["opportunity"])
            boosted = info["profile"] in {
                DeploymentProfile.PUSH.value,
                DeploymentProfile.OVERTAKE.value,
            }
            opportunities += int(opportunity)
            opportunity_boosts += int(opportunity and boosted)
            boosts += int(boosted)
            actions += 1
            if terminated or truncated:
                failures += int(info["failure"] is not None)
                final_ranks.append(int(info["rank"]))
                break
        episode_rewards.append(total_reward)
        deployed_mj.append(total_deployed_j / 1.0e6)
        passes.append(episode_passes)
    return {
        "episodes": episodes,
        "mean_reward": statistics.fmean(episode_rewards),
        "reward_std": statistics.pstdev(episode_rewards) if episodes > 1 else 0.0,
        "mean_finish_position": statistics.fmean(final_ranks),
        "mean_deployed_mj": statistics.fmean(deployed_mj),
        "mean_passes": statistics.fmean(passes),
        "overtake_opportunity_recall": 0.0 if opportunities == 0 else opportunity_boosts / opportunities,
        "boost_action_rate": 0.0 if actions == 0 else boosts / actions,
        "failure_rate": failures / episodes,
    }


def train_decision_policy(
    settings: RaceSettings,
    output: Path,
    total_timesteps: int,
    cycles: int,
    evaluation_episodes: int,
    learning_rate: float,
) -> dict[str, Any]:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.monitor import Monitor

    if cycles < 1 or evaluation_episodes < 1 or total_timesteps < cycles:
        raise ValueError("training requires at least one step per cycle and one evaluation episode")
    raw_env = BoostDecisionEnv(settings)
    check_env(raw_env, skip_render_check=True)
    training_env = Monitor(BoostDecisionEnv(settings))
    rollout_steps = max(32, min(256, total_timesteps // cycles))
    batch_size = min(64, rollout_steps)
    model = PPO(
        "MlpPolicy",
        training_env,
        seed=settings.seed,
        n_steps=rollout_steps,
        batch_size=batch_size,
        n_epochs=10,
        learning_rate=learning_rate,
        gamma=0.996672,
        verbose=0,
        device="cpu",
    )
    baseline = evaluate_decision_policy(None, settings, evaluation_episodes)
    output.parent.mkdir(parents=True, exist_ok=True)
    cycle_steps = total_timesteps // cycles
    remainder = total_timesteps % cycles
    history: list[dict[str, float | int | bool]] = []
    best_reward = float("-inf")
    best_cycle = 0
    completed_steps = 0
    for cycle in range(1, cycles + 1):
        requested_steps = cycle_steps + int(cycle <= remainder)
        model.learn(total_timesteps=requested_steps, reset_num_timesteps=cycle == 1)
        completed_steps += requested_steps
        evaluation = evaluate_decision_policy(
            model,
            settings,
            evaluation_episodes,
            seed_offset=10000,
        )
        mean_reward = float(evaluation["mean_reward"])
        improved = mean_reward > best_reward
        if improved:
            best_reward = mean_reward
            best_cycle = cycle
            model.save(str(output.with_name(f"{output.name}.best")))
        history.append(
            {
                "cycle": cycle,
                "timesteps": completed_steps,
                "optimizer_epochs": cycle * model.n_epochs,
                "improved": improved,
                "reward_improvement_over_baseline": mean_reward - float(baseline["mean_reward"]),
                **evaluation,
            }
        )
    model.save(str(output))
    if raw_env.session is None:
        raw_env.reset(seed=settings.seed)
    assert raw_env.session is not None
    manifest = decision_manifest(raw_env.session)
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    metrics = {
        "type": "boost_training_metrics",
        "status": "completed",
        "policy": str(output),
        "algorithm": "PPO",
        "seed": settings.seed,
        "circuit": settings.circuit,
        "total_timesteps": completed_steps,
        "cycles": cycles,
        "evaluation_episodes_per_cycle": evaluation_episodes,
        "optimizer_epochs_per_cycle": model.n_epochs,
        "learning_rate": learning_rate,
        "best_cycle": best_cycle,
        "baseline": baseline,
        "history": history,
        "promotion": {
            "candidate": best_reward > float(baseline["mean_reward"])
            and float(history[best_cycle - 1]["failure_rate"]) == 0.0,
            "automatic": False,
            "reason": "manual review is required; evaluation is seeded simulation only",
        },
        "provenance": "generated from uncalibrated simulator episodes; no real-car performance claim",
    }
    output.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def load_training_metrics(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text())
    if payload.get("type") != "boost_training_metrics" or not isinstance(payload.get("history"), list):
        raise ValueError("invalid boost training metrics")
    return payload
