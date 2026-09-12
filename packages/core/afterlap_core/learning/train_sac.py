"""SAC training and resume.

Stable-Baselines3 ``SAC`` with ``MlpPolicy`` and the starting settings frozen in
``configs/learning/sac-v1.yaml``. The library implementation is used as-is:
nothing here rewrites the actor entropy, the target critics or the action
squashing, because owning a modified algorithm means owning its validation too.

Two things this module refuses to do.

**It does not report a training success it did not observe.** :func:`train`
returns a :class:`TrainingResult` whose ``status`` is the status that actually
happened, including ``non_finite_loss`` and ``failed``. There are no dummy
weights and no synthetic curve.

**It does not treat a smoke run as a trained product.** :func:`smoke_run` exists
because ``SAC_IMPLEMENTATION.md`` step 2 asks for a short job that verifies
finite losses, checkpoints, resume and complete episodes. Its result carries
``is_smoke_run=True`` and its own warning string, and anything that packages it
into a bundle inherits that warning in the model card.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import torch
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import CallbackList
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecEnv

from ..paths import Paths, atomic_write_json
from .callbacks import CheckpointCallback, MetricsCallback, NonFiniteLossGuard, TrainingMetrics
from .checkpoints import CheckpointManifest, restore_into, verify_checkpoint
from .circuits import load_circuit_split, split_readiness
from .config import EnvConfig, SacConfig, load_env_config, load_sac_config
from .env import AfterlapEnv
from .reward import load_reward_manifest, objective_content_hash

__all__ = [
    "TrainingResult",
    "TrainingStatus",
    "benchmark_throughput",
    "build_vec_env",
    "resume",
    "smoke_run",
    "train",
]


class TrainingStatus(StrEnum):
    COMPLETED = "completed"
    NON_FINITE_LOSS = "non_finite_loss"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """What a training job actually produced. Never a claim it did not observe."""

    status: TrainingStatus
    run_id: str
    run_directory: Path
    requested_timesteps: int
    completed_timesteps: int
    wall_clock_s: float
    transitions_per_second: float
    metrics: dict[str, Any]
    checkpoints: tuple[Path, ...]
    environment_version: str
    feature_hash: str
    reward_revision: str
    is_smoke_run: bool = False
    failure_detail: str | None = None
    hardware: str = ""
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "run_id": self.run_id,
            "run_directory": str(self.run_directory),
            "requested_timesteps": self.requested_timesteps,
            "completed_timesteps": self.completed_timesteps,
            "wall_clock_s": self.wall_clock_s,
            "transitions_per_second": self.transitions_per_second,
            "metrics": self.metrics,
            "checkpoints": [str(p) for p in self.checkpoints],
            "environment_version": self.environment_version,
            "feature_hash": self.feature_hash,
            "reward_revision": self.reward_revision,
            "is_smoke_run": self.is_smoke_run,
            "failure_detail": self.failure_detail,
            "hardware": self.hardware,
            "warning": self.warning,
        }


SMOKE_WARNING = (
    "SMOKE RUN. This job existed only to verify finite losses, checkpointing, resume and "
    "complete episodes over a few thousand transitions. It is NOT a trained model, it has no "
    "held-out evaluation, and reporting it as a trained product would be a fabricated result."
)


def _hardware() -> str:
    import platform

    return (
        f"{platform.platform()} / {platform.processor() or 'unknown cpu'} / "
        f"python {platform.python_version()}"
    )


def _make_single_env(
    config: EnvConfig, scenario_id: str | None, seed: int, index: int, session_id: str
) -> Any:
    def factory() -> Monitor[np.ndarray, np.ndarray]:
        env = AfterlapEnv(config=config, scenario_id=scenario_id, session_id=f"{session_id}:{index}")
        env.reset(seed=seed + index)
        return Monitor(env)

    return factory


def build_vec_env(
    config: EnvConfig,
    *,
    n_envs: int,
    seed: int,
    scenario_id: str | None = None,
    subprocess: bool = False,
    session_id: str = "train",
) -> VecEnv:
    """Build the vectorised environment.

    ``SubprocVecEnv`` is available but off by default: the simulator and the
    CasADi solve are the cost here, and oversubscribing BLAS threads across
    workers on a laptop makes throughput worse, not better. Measure before
    turning it on.
    """
    factories = [_make_single_env(config, scenario_id, seed, i, session_id) for i in range(n_envs)]
    vec = SubprocVecEnv(factories) if subprocess and n_envs > 1 else DummyVecEnv(factories)
    vec.seed(seed)
    return vec


def _build_model(
    vec_env: VecEnv, algorithm: SacConfig, *, seed: int, device: str, tensorboard_log: str | None = None
) -> SAC:
    target_entropy: Any = algorithm.target_entropy
    if isinstance(target_entropy, str) and target_entropy != "auto":
        target_entropy = float(target_entropy)
    return SAC(
        algorithm.policy,
        vec_env,
        learning_rate=algorithm.learning_rate,
        buffer_size=algorithm.buffer_size,
        learning_starts=algorithm.learning_starts,
        batch_size=algorithm.batch_size,
        tau=algorithm.tau,
        gamma=algorithm.gamma,
        train_freq=algorithm.train_freq,
        gradient_steps=algorithm.gradient_steps,
        ent_coef=algorithm.ent_coef,
        target_entropy=target_entropy,
        policy_kwargs={"net_arch": list(algorithm.net_arch)},
        seed=seed,
        device=device,
        verbose=0,
        tensorboard_log=tensorboard_log,
    )


def benchmark_throughput(
    config: EnvConfig | None = None,
    *,
    transitions: int = 1000,
    scenario_id: str | None = None,
    seed: int = 11,
) -> dict[str, Any]:
    """Measure environment throughput before choosing a training budget.

    ``SAC_IMPLEMENTATION.md`` requires at least 1 000 transitions to be
    benchmarked before a total step count is chosen. This measures the
    *environment* — simulator, estimator, encoder and planner — with a uniform
    random policy and no gradient work, which is the term that dominates.
    """
    settings = config or load_env_config()
    env = AfterlapEnv(config=settings, scenario_id=scenario_id)
    rng = np.random.default_rng(seed)

    totals: dict[str, float] = {}

    def accumulate() -> None:
        for name, value in env.diagnostics.as_dict().items():
            if name.startswith("mean_"):
                continue
            totals[name] = totals.get(name, 0.0) + float(value)

    reset_started = time.perf_counter()
    env.reset(seed=seed)
    reset_s = time.perf_counter() - reset_started
    resets = 1
    episodes = 0
    step_s = 0.0

    for _ in range(transitions):
        action = rng.uniform(-1.0, 1.0, size=2).astype(np.float32)
        started = time.perf_counter()
        _, _, terminated, truncated, _ = env.step(action)
        step_s += time.perf_counter() - started
        if terminated or truncated:
            episodes += 1
            accumulate()
            started = time.perf_counter()
            env.reset(seed=seed + episodes)
            reset_s += time.perf_counter() - started
            resets += 1
    accumulate()
    elapsed = step_s + reset_s
    return {
        "transitions": transitions,
        "wall_clock_s": elapsed,
        "transitions_per_second": transitions / elapsed if elapsed > 0.0 else 0.0,
        "step_wall_clock_s": step_s,
        "step_transitions_per_second": transitions / step_s if step_s > 0.0 else 0.0,
        "reset_wall_clock_s": reset_s,
        "resets": resets,
        "mean_reset_s": reset_s / resets if resets else 0.0,
        "episodes": episodes,
        "environment_version": settings.environment_version,
        "planner_mode": settings.planner_mode,
        "scenario_id": scenario_id or "mixed",
        "hardware": _hardware(),
        "diagnostics": dict(sorted(totals.items())),
        "note": (
            "Environment throughput only, with a uniform random policy and no gradient work. "
            "It is not a trained-model figure and it is not a latency claim for the planner. "
            "Diagnostics are summed over every episode; the reset column is the declared "
            "warm-up, which is scenario setup rather than a scored transition."
        ),
    }


def train(
    *,
    algorithm: SacConfig | None = None,
    config: EnvConfig | None = None,
    seed: int = 11,
    total_timesteps: int | None = None,
    run_id: str | None = None,
    root: Path | None = None,
    scenario_id: str | None = None,
    n_envs: int | None = None,
    subprocess: bool = False,
    save_replay_buffer: bool = True,
    checkpoint_every: int | None = None,
    is_smoke_run: bool = False,
    resume_from: Path | None = None,
) -> TrainingResult:
    """Run one SAC training job and report what actually happened."""
    settings = config or load_env_config()
    sac_config = algorithm or load_sac_config()
    reward = load_reward_manifest(settings.objective_id)
    steps = int(total_timesteps if total_timesteps is not None else sac_config.total_timesteps)
    envs = int(n_envs if n_envs is not None else sac_config.n_envs)
    every = int(checkpoint_every if checkpoint_every is not None else sac_config.checkpoint_every_steps)
    identifier = run_id or f"sac-{settings.revision}-seed{seed}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    paths = Paths.default(root).ensure()
    run_directory = paths.models / "learning" / identifier
    run_directory.mkdir(parents=True, exist_ok=True)

    if abs(sac_config.gamma - reward.gamma) > 1e-12:
        raise ValueError(
            f"SAC gamma {sac_config.gamma!r} differs from the frozen reward gamma {reward.gamma!r}; "
            "the critic would discount on a different horizon than the reward it is fitting"
        )

    torch.manual_seed(seed)
    np.random.seed(seed)

    vec_env = build_vec_env(settings, n_envs=envs, seed=seed, scenario_id=scenario_id, subprocess=subprocess)
    metrics = TrainingMetrics()
    model = _build_model(vec_env, sac_config, seed=seed, device=sac_config.device)

    resumed_manifest: CheckpointManifest | None = None
    if resume_from is not None:
        resumed_manifest = restore_into(
            Path(resume_from),
            model,
            expected_environment_version=settings.environment_version,
            expected_feature_hash=_feature_hash(),
        )

    checkpoint_cb = CheckpointCallback(
        run_directory / "checkpoints",
        every_steps=every,
        run_id=identifier,
        environment_version=settings.environment_version,
        feature_hash=_feature_hash(),
        reward_revision=reward.revision,
        algorithm_config=sac_config.as_manifest(),
        env_config_hash=settings.content_hash,
        seeds=(seed,),
        metrics=metrics,
        save_replay_buffer=save_replay_buffer,
    )
    guard = NonFiniteLossGuard()
    callbacks = CallbackList([MetricsCallback(metrics), guard, checkpoint_cb])

    circuit_split = load_circuit_split()
    manifest = {
        "run_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "requested_timesteps": steps,
        "n_envs": envs,
        "scenario_id": scenario_id or "mixed",
        "environment_version": settings.environment_version,
        "env_config_hash": settings.content_hash,
        "algorithm": sac_config.as_manifest(),
        "reward_revision": reward.revision,
        "objective_hash": objective_content_hash(settings.objective_id),
        "feature_hash": _feature_hash(),
        "circuit_split": circuit_split.as_manifest(split_readiness(circuit_split)),
        "hardware": _hardware(),
        "is_smoke_run": is_smoke_run,
        "resumed_from": None if resumed_manifest is None else str(resume_from),
        "status": "running",
    }
    atomic_write_json(run_directory / "run_manifest.json", manifest)

    started = time.perf_counter()
    status = TrainingStatus.COMPLETED
    failure: str | None = None
    try:
        model.learn(
            total_timesteps=steps,
            callback=callbacks,
            reset_num_timesteps=resumed_manifest is None,
            progress_bar=False,
        )
    except BaseException as exc:
        status = TrainingStatus.FAILED
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        elapsed = time.perf_counter() - started
        vec_env.close()

    if guard.failures and status is TrainingStatus.COMPLETED:
        status = TrainingStatus.NON_FINITE_LOSS
        failure = "non-finite training statistic: " + "; ".join(guard.failures)

    completed = int(model.num_timesteps)
    summary = metrics.summary()
    result = TrainingResult(
        status=status,
        run_id=identifier,
        run_directory=run_directory,
        requested_timesteps=steps,
        completed_timesteps=completed,
        wall_clock_s=elapsed,
        transitions_per_second=completed / elapsed if elapsed > 0.0 else 0.0,
        metrics=summary,
        checkpoints=tuple(checkpoint_cb.written),
        environment_version=settings.environment_version,
        feature_hash=_feature_hash(),
        reward_revision=reward.revision,
        is_smoke_run=is_smoke_run,
        failure_detail=failure,
        hardware=_hardware(),
        warning=SMOKE_WARNING if is_smoke_run else "",
    )
    manifest["status"] = status.value
    manifest["result"] = result.as_dict()
    atomic_write_json(run_directory / "run_manifest.json", manifest)
    return result


def smoke_run(
    *,
    transitions: int = 3000,
    seed: int = 11,
    scenario_id: str | None = "two-straight-counterattack",
    config: EnvConfig | None = None,
    algorithm: SacConfig | None = None,
    root: Path | None = None,
    n_envs: int = 1,
    learning_starts: int = 200,
    checkpoint_every: int = 1000,
) -> TrainingResult:
    """The step-2 smoke job. **Not a trained product.**

    ``learning_starts`` is lowered so gradient steps actually run inside a few
    thousand transitions; that makes the job a *check that the machinery works*,
    not a shortened version of training. The result carries ``is_smoke_run`` and
    :data:`SMOKE_WARNING`.
    """
    import dataclasses

    settings = config or load_env_config()
    base = algorithm or load_sac_config()
    tuned = dataclasses.replace(
        base,
        learning_starts=learning_starts,
        buffer_size=min(base.buffer_size, max(transitions * 2, 1000)),
        batch_size=min(base.batch_size, 64),
        gradient_steps=1,
        n_envs=n_envs,
        total_timesteps=transitions,
    )
    return train(
        algorithm=tuned,
        config=settings,
        seed=seed,
        total_timesteps=transitions,
        run_id=f"smoke-{settings.revision}-seed{seed}",
        root=root,
        scenario_id=scenario_id,
        n_envs=n_envs,
        checkpoint_every=checkpoint_every,
        is_smoke_run=True,
    )


def resume(
    checkpoint: Path,
    *,
    additional_timesteps: int,
    config: EnvConfig | None = None,
    algorithm: SacConfig | None = None,
    seed: int = 11,
    scenario_id: str | None = None,
    root: Path | None = None,
    n_envs: int = 1,
) -> TrainingResult:
    """Resume from a verified checkpoint and continue training."""
    manifest = verify_checkpoint(Path(checkpoint))
    return train(
        algorithm=algorithm,
        config=config,
        seed=seed,
        total_timesteps=additional_timesteps,
        run_id=f"{manifest.run_id}-resumed",
        root=root,
        scenario_id=scenario_id,
        n_envs=n_envs,
        resume_from=Path(checkpoint),
    )


def deterministic_evaluation(
    model: SAC,
    *,
    config: EnvConfig | None = None,
    scenario_id: str = "two-straight-counterattack",
    seed: int = 101,
    episodes: int = 1,
) -> list[float]:
    """Deterministic actor-mean rollouts. Used to compare a resume with a run.

    Bitwise equivalence across platforms is not promised. What is compared is
    that the same model, on the same machine, from the same seed, produces the
    same returns.
    """
    settings = config or load_env_config()
    env = AfterlapEnv(config=settings, scenario_id=scenario_id)
    returns: list[float] = []
    for episode in range(episodes):
        observation, _ = env.reset(seed=seed + episode, options={"scenario_seed": 11})
        total = 0.0
        terminated = truncated = False
        while not (terminated or truncated):
            action, _ = model.predict(observation, deterministic=True)
            observation, reward, terminated, truncated, _ = env.step(action)
            total += float(reward)
        returns.append(total)
    env.close()
    return returns


def _feature_hash() -> str:
    from ..feature_manifest import ENERGY_V1

    return ENERGY_V1.content_hash()
