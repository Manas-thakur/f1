"""Training callbacks: metrics, checkpointing and the honesty guards.

``SAC_IMPLEMENTATION.md`` asks for reward terms tracked *separately*, actual
finish position and time, energy distributions, proposal projection distance,
solver timeouts, instruction churn, observed executions, critic loss, entropy
and throughput — and it flags one specific failure mode: **a high reward with
frequent withdrawals**. :class:`MetricsCallback` records the withdrawal rate
beside the reward for exactly that reason, so the two are never seen apart.

:class:`NonFiniteLossGuard` stops a run whose critic loss or entropy coefficient
stops being finite. A run that keeps going after that is producing numbers, not
results.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3.common.callbacks import BaseCallback

from ..paths import atomic_write_json
from .checkpoints import save_checkpoint

__all__ = [
    "CheckpointCallback",
    "MetricsCallback",
    "NonFiniteLossGuard",
    "TrainingMetrics",
]


@dataclass
class TrainingMetrics:
    """Rolling aggregates. Every physical outcome is kept beside the utility."""

    episode_returns: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    episode_lengths: deque[int] = field(default_factory=lambda: deque(maxlen=200))
    finish_positions: deque[int] = field(default_factory=lambda: deque(maxlen=200))
    elapsed_times_s: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    final_energy_j: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    reward_terms: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=2000))
    )
    projection_distance_j: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    decisions: int = 0
    withdrawals: int = 0
    solver_timeouts: int = 0
    instruction_changes: int = 0
    instructions_issued: int = 0
    observed_executions: int = 0
    missed_executions: int = 0
    learned_disabled_ticks: int = 0
    clip_events: int = 0
    finished_episodes: int = 0
    failed_episodes: int = 0
    truncated_episodes: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    transitions: int = 0
    optimiser_stats: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=500))
    )
    """Critic loss, actor loss and entropy coefficient, sampled from SB3's logger."""

    @property
    def withdrawal_rate(self) -> float:
        return self.withdrawals / self.decisions if self.decisions else 0.0

    @property
    def transitions_per_second(self) -> float:
        elapsed = time.perf_counter() - self.started_at
        return self.transitions / elapsed if elapsed > 0.0 else 0.0

    def summary(self) -> dict[str, Any]:
        def stat(values: deque[float] | deque[int]) -> dict[str, float] | None:
            if not values:
                return None
            array = np.asarray(values, dtype=np.float64)
            return {
                "mean": float(array.mean()),
                "p50": float(np.percentile(array, 50)),
                "p05": float(np.percentile(array, 5)),
                "p95": float(np.percentile(array, 95)),
                "count": int(array.size),
            }

        return {
            "transitions": self.transitions,
            "transitions_per_second": self.transitions_per_second,
            "episode_return": stat(self.episode_returns),
            "episode_length": stat(self.episode_lengths),
            "finish_position": stat(self.finish_positions),
            "elapsed_time_s": stat(self.elapsed_times_s),
            "final_energy_j": stat(self.final_energy_j),
            "projection_distance_j": stat(self.projection_distance_j),
            "reward_terms": {name: stat(values) for name, values in sorted(self.reward_terms.items())},
            "decisions": self.decisions,
            "withdrawals": self.withdrawals,
            "withdrawal_rate": self.withdrawal_rate,
            "solver_timeouts": self.solver_timeouts,
            "instruction_changes": self.instruction_changes,
            "instructions_issued": self.instructions_issued,
            "observed_executions": self.observed_executions,
            "missed_executions": self.missed_executions,
            "learned_disabled_ticks": self.learned_disabled_ticks,
            "clip_events": self.clip_events,
            "finished_episodes": self.finished_episodes,
            "failed_episodes": self.failed_episodes,
            "truncated_episodes": self.truncated_episodes,
            "optimiser": {name: stat(values) for name, values in sorted(self.optimiser_stats.items())},
        }


class MetricsCallback(BaseCallback):
    """Aggregates per-step ``info`` into :class:`TrainingMetrics`."""

    def __init__(self, metrics: TrainingMetrics | None = None, verbose: int = 0) -> None:
        super().__init__(verbose)
        self.metrics = metrics or TrainingMetrics()
        self._returns: dict[int, float] = defaultdict(float)
        self._lengths: dict[int, int] = defaultdict(int)

    def _on_step(self) -> bool:
        infos = self.locals.get("infos") or ()
        rewards = self.locals.get("rewards")
        dones = self.locals.get("dones")
        for index, info in enumerate(infos):
            self.metrics.transitions += 1
            if rewards is not None and index < len(rewards):
                self._returns[index] += float(rewards[index])
            self._lengths[index] += 1

            terms = info.get("reward_terms")
            if isinstance(terms, dict):
                for name in (
                    "elapsed_penalty",
                    "instruction_penalty",
                    "terminal_finish",
                    "terminal_failure",
                    "shaping",
                ):
                    value = terms.get(name)
                    if isinstance(value, (int, float)) and math.isfinite(float(value)):
                        self.metrics.reward_terms[name].append(float(value))

            planning = info.get("planning")
            if isinstance(planning, dict):
                self.metrics.decisions += 1
                if planning.get("selected_plan_id") is None:
                    self.metrics.withdrawals += 1
                if planning.get("status") == "deadline_exceeded":
                    self.metrics.solver_timeouts += 1

            diagnostics = info.get("diagnostics")
            if isinstance(diagnostics, dict):
                for name in ("instructions_issued", "observed_executions", "missed_executions"):
                    value = diagnostics.get(name)
                    if isinstance(value, int):
                        setattr(self.metrics, name, max(getattr(self.metrics, name), value))
                projection = diagnostics.get("mean_projection_distance_j")
                if isinstance(projection, (int, float)) and math.isfinite(float(projection)):
                    self.metrics.projection_distance_j.append(float(projection))

            outcome = info.get("episode_outcome")
            if isinstance(outcome, dict):
                self.metrics.episode_returns.append(self._returns[index])
                self.metrics.episode_lengths.append(self._lengths[index])
                self._returns[index] = 0.0
                self._lengths[index] = 0
                position = outcome.get("finish_position")
                if isinstance(position, int):
                    self.metrics.finish_positions.append(position)
                elapsed = outcome.get("elapsed_time_s")
                if isinstance(elapsed, (int, float)):
                    self.metrics.elapsed_times_s.append(float(elapsed))
                energy = outcome.get("final_energy_j")
                if isinstance(energy, (int, float)):
                    self.metrics.final_energy_j.append(float(energy))
                self.metrics.instruction_changes += int(outcome.get("instruction_changes") or 0)
                if outcome.get("finished"):
                    self.metrics.finished_episodes += 1
                if outcome.get("failed"):
                    self.metrics.failed_episodes += 1
                if outcome.get("truncated"):
                    self.metrics.truncated_episodes += 1
        del dones
        return True

    TRACKED_LOSSES = (
        "train/critic_loss",
        "train/actor_loss",
        "train/ent_coef",
        "train/ent_coef_loss",
    )

    def _on_rollout_end(self) -> None:
        summary = self.metrics.summary()
        logger = self.logger
        if logger is None:  # pragma: no cover - SB3 always sets one
            return
        values = getattr(logger, "name_to_value", {})
        for key in self.TRACKED_LOSSES:
            value = values.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                self.metrics.optimiser_stats[key.split("/", 1)[1]].append(float(value))
        logger.record("afterlap/withdrawal_rate", summary["withdrawal_rate"])
        logger.record("afterlap/transitions_per_second", summary["transitions_per_second"])


class NonFiniteLossGuard(BaseCallback):
    """Stops the run when a tracked loss or the entropy coefficient goes non-finite."""

    WATCHED = ("train/critic_loss", "train/actor_loss", "train/ent_coef", "train/ent_coef_loss")

    def __init__(self, verbose: int = 0) -> None:
        super().__init__(verbose)
        self.failures: list[str] = []

    def _on_step(self) -> bool:
        logger = self.logger
        if logger is None:  # pragma: no cover
            return True
        values = getattr(logger, "name_to_value", {})
        for key in self.WATCHED:
            value = values.get(key)
            if value is None:
                continue
            if not math.isfinite(float(value)):
                self.failures.append(f"{key}={value!r}")
                return False
        return True


class CheckpointCallback(BaseCallback):
    """Writes an atomic checkpoint every ``every_steps`` transitions."""

    def __init__(
        self,
        directory: Path,
        *,
        every_steps: int,
        run_id: str,
        environment_version: str,
        feature_hash: str,
        reward_revision: str,
        algorithm_config: dict[str, Any],
        env_config_hash: str,
        seeds: tuple[int, ...] = (),
        metrics: TrainingMetrics | None = None,
        save_replay_buffer: bool = True,
        verbose: int = 0,
    ) -> None:
        super().__init__(verbose)
        self.directory = Path(directory)
        self.every_steps = max(1, int(every_steps))
        self.run_id = run_id
        self.environment_version = environment_version
        self.feature_hash = feature_hash
        self.reward_revision = reward_revision
        self.algorithm_config = algorithm_config
        self.env_config_hash = env_config_hash
        self.seeds = seeds
        self.metrics = metrics
        self.save_replay_buffer = save_replay_buffer
        self.written: list[Path] = []
        self._next_at = self.every_steps

    def _write(self, tag: str) -> Path:
        target = self.directory / tag
        path = save_checkpoint(
            target,
            self.model,
            run_id=self.run_id,
            step_count=int(self.model.num_timesteps),
            environment_version=self.environment_version,
            feature_hash=self.feature_hash,
            reward_revision=self.reward_revision,
            algorithm_config=self.algorithm_config,
            env_config_hash=self.env_config_hash,
            seeds=self.seeds,
            metrics=self.metrics.summary() if self.metrics is not None else None,
            save_replay_buffer=self.save_replay_buffer,
        )
        self.written.append(path)
        atomic_write_json(
            self.directory / "latest.json",
            {"checkpoint": path.name, "step_count": int(self.model.num_timesteps)},
        )
        return path

    def _on_step(self) -> bool:
        if self.model.num_timesteps >= self._next_at:
            self._write(f"step-{int(self.model.num_timesteps):09d}")
            self._next_at = int(self.model.num_timesteps) + self.every_steps
        return True

    def _on_training_end(self) -> None:
        self._write("final")
