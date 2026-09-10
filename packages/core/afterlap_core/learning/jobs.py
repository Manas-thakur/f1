"""Operator-facing training jobs.

``afterlap_core.cli train`` imported ``run_training`` from
:mod:`afterlap_core.learning.train_sac` and no such function existed, so every
training, evaluation, ablation and promotion command on the coordinator CLI
raised on import or on call. The algorithm layer was complete and unreachable.

This module is the reachable surface. It does three things and refuses to do a
fourth:

* it resolves the frozen configuration documents by id, so a job is described
  by what is on disk rather than by flags typed at a prompt;
* it runs training or a resume, records what was observed, and optionally
  packages the final checkpoint into a bundle;
* it returns plain JSON-shaped data, because the caller is a CLI whose output
  is read by a person and diffed by a script.

It never promotes, never marks a bundle approved, and never fills an absent
metric. A job that failed returns its failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import Paths
from .config import EnvConfig, SacConfig, load_env_config, load_sac_config
from .packaging import PackagedBundle, PackagingError, package_checkpoint
from .train_sac import TrainingResult, TrainingStatus, benchmark_throughput, resume, smoke_run, train

__all__ = [
    "resolve_config_id",
    "run_packaging",
    "run_throughput_benchmark",
    "run_training",
]

DEFAULT_RULE_FAMILY = "synthetic-pack-v1"


def resolve_config_id(value: str | Path | None, default: str) -> str:
    """Accept a config id or a path to one of the shipped documents.

    Operators reach for a path because that is what they see in the repository;
    the loaders key on an id. Resolving here keeps one spelling working without
    duplicating the loader's search rules.
    """
    if value is None:
        return default
    text = str(value)
    candidate = Path(text)
    if candidate.suffix in {".yaml", ".yml"}:
        return candidate.stem
    return text


def _selected_checkpoint(result: TrainingResult) -> Path | None:
    if not result.checkpoints:
        return None
    final = [path for path in result.checkpoints if path.name == "final"]
    return final[-1] if final else result.checkpoints[-1]


def run_training(
    *,
    sac_config_id: str | Path | None = None,
    env_config_id: str | Path | None = None,
    seed: int = 11,
    total_steps: int | None = None,
    scenario_id: str | None = None,
    n_envs: int | None = None,
    checkpoint_every: int | None = None,
    smoke: bool = False,
    resume_from: Path | None = None,
    evaluation_episodes: int = 0,
    evaluation_seed: int = 101,
    evaluation_scenario_id: str = "two-straight-counterattack",
    package: bool = False,
    rule_family: str = DEFAULT_RULE_FAMILY,
    save_replay_buffer: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    """Run one training job and report exactly what it produced.

    ``smoke`` and ``resume_from`` are mutually exclusive: a resume continues a
    real run, and labelling the continuation of a real run as a smoke job would
    mislabel the artifact it produces.
    """
    if smoke and resume_from is not None:
        raise ValueError("a resume continues an existing run and cannot also be a smoke job")

    algorithm: SacConfig = load_sac_config(resolve_config_id(sac_config_id, "sac-v1"))
    settings: EnvConfig = load_env_config(resolve_config_id(env_config_id, "env-v1"))

    if resume_from is not None:
        result = resume(
            Path(resume_from),
            additional_timesteps=int(total_steps if total_steps is not None else algorithm.total_timesteps),
            config=settings,
            algorithm=algorithm,
            seed=seed,
            scenario_id=scenario_id,
            root=root,
            n_envs=int(n_envs or 1),
        )
    elif smoke:
        result = smoke_run(
            transitions=int(total_steps if total_steps is not None else 3000),
            seed=seed,
            scenario_id=scenario_id or "two-straight-counterattack",
            config=settings,
            algorithm=algorithm,
            root=root,
            n_envs=int(n_envs or 1),
            checkpoint_every=int(checkpoint_every or 1000),
        )
    else:
        result = train(
            algorithm=algorithm,
            config=settings,
            seed=seed,
            total_timesteps=total_steps,
            scenario_id=scenario_id,
            n_envs=n_envs,
            checkpoint_every=checkpoint_every,
            save_replay_buffer=save_replay_buffer,
            root=root,
            evaluation_episodes=evaluation_episodes,
            evaluation_seed=evaluation_seed,
            evaluation_scenario_id=evaluation_scenario_id,
        )

    payload: dict[str, Any] = {
        "job": "train",
        "sac_config": algorithm.revision,
        "sac_config_hash": algorithm.content_hash,
        "env_config": settings.revision,
        "env_config_hash": settings.content_hash,
        "environment_version": settings.environment_version,
        "resumed_from": None if resume_from is None else str(resume_from),
        "result": result.as_dict(),
        "mean_evaluation_return": result.mean_evaluation_return,
        "bundle": None,
    }

    if not package:
        payload["packaging"] = "not requested"
        return payload

    checkpoint = _selected_checkpoint(result)
    if checkpoint is None:
        payload["packaging"] = (
            "no checkpoint was written, so there is nothing to package; this is reported rather "
            "than an empty bundle being created"
        )
        return payload
    if result.status is not TrainingStatus.COMPLETED:
        payload["packaging"] = (
            f"training status is {result.status.value!r}; the checkpoint is packaged so the failure "
            "is inspectable and the bundle says so"
        )
    try:
        packaged: PackagedBundle = package_checkpoint(
            checkpoint,
            bundle_id=None,
            rule_family=rule_family,
            env_config=settings,
            deterministic_returns=result.evaluation_returns,
            deterministic_detail=result.evaluation_detail or None,
            supported_scenario_families=tuple(sorted({spec.family for spec in settings.scenarios})),
            paths=Paths.default(root),
        )
    except PackagingError as exc:
        payload["packaging"] = f"packaging refused: {exc}"
        return payload
    payload["bundle"] = packaged.as_dict()
    payload["packaging"] = "packaged"
    return payload


def run_packaging(
    checkpoint: Path,
    *,
    rule_family: str = DEFAULT_RULE_FAMILY,
    env_config_id: str | Path | None = None,
    bundle_directory: Path | None = None,
    bundle_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Package an existing verified checkpoint into a bundle."""
    settings = load_env_config(resolve_config_id(env_config_id, "env-v1"))
    packaged = package_checkpoint(
        Path(checkpoint),
        bundle_directory=bundle_directory,
        bundle_id=bundle_id,
        rule_family=rule_family,
        env_config=settings,
        supported_scenario_families=tuple(sorted({spec.family for spec in settings.scenarios})),
        paths=Paths.default(root),
    )
    return {"job": "package", **packaged.as_dict()}


def run_throughput_benchmark(
    *,
    env_config_id: str | Path | None = None,
    transitions: int = 1000,
    scenario_id: str | None = None,
    seed: int = 11,
) -> dict[str, Any]:
    """Measure environment throughput before a step budget is chosen."""
    settings = load_env_config(resolve_config_id(env_config_id, "env-v1"))
    measured = benchmark_throughput(settings, transitions=transitions, scenario_id=scenario_id, seed=seed)
    return {"job": "throughput", "env_config": settings.revision, **measured}
