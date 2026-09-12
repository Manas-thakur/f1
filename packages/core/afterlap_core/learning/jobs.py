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

from ..feature_manifest import ACTION_SIZE
from ..paths import Paths, sha256_json
from .config import (
    EnvConfig,
    SacConfig,
    load_env_config,
    load_sac_config,
    load_value_config,
)
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


def _named_policy(kind: str, seed: int) -> tuple[Any, str]:
    """A frozen controller for dataset collection, named in the record.

    An ensemble or a calibrator fitted under one controller is not valid under
    another, so the identity is returned alongside the callable and travels into
    every report and bundle.
    """
    import numpy as np

    if kind == "held-neutral":

        def hold(_observation: Any) -> Any:
            return np.zeros(ACTION_SIZE, dtype=np.float32)

        return hold, "held-neutral/action-zero"
    if kind == "uniform-random":
        rng = np.random.default_rng(seed)

        def uniform(_observation: Any) -> Any:
            return rng.uniform(-1.0, 1.0, size=ACTION_SIZE).astype(np.float32)

        return uniform, f"uniform-random/seed{seed}"
    raise ValueError(f"unknown collection policy {kind!r}; expected 'held-neutral' or 'uniform-random'")


def run_value_fit(
    *,
    env_config_id: str | Path | None = None,
    value_config_id: str | Path | None = None,
    episodes: int = 12,
    seed: int = 0,
    scenario_id: str | None = None,
    policy: str = "held-neutral",
    tuning_fraction: float = 0.3,
    max_steps: int | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Collect complete episodes and fit the continuation-return ensemble.

    The split is by episode, never by row: adjacent cutoffs of one episode are
    the same trajectory, and splitting between them would imply an independent
    generalisation the data cannot support. ``fit_ensemble`` enforces this and
    refuses incomplete episodes outright.
    """
    from .dataset import collect_continuation_samples
    from .reward import load_reward_manifest
    from .value import fit_ensemble

    settings = load_env_config(resolve_config_id(env_config_id, "env-v1"))
    value_settings = load_value_config(resolve_config_id(value_config_id, "value-v1"))
    reward = load_reward_manifest(settings.objective_id)
    callable_policy, policy_identity = _named_policy(policy, seed)

    collection = collect_continuation_samples(
        settings,
        policy=callable_policy,
        policy_identity=policy_identity,
        episodes=episodes,
        gamma=reward.gamma,
        seed=seed,
        scenario_id=scenario_id,
        max_steps=max_steps,
    )
    payload: dict[str, Any] = {
        "job": "fit-value",
        "env_config": settings.revision,
        "value_config": value_settings.revision,
        "value_config_hash": value_settings.content_hash,
        "gamma": reward.gamma,
        "reward_revision": reward.revision,
        "collection": collection.as_dict(),
    }
    complete = [sample for sample in collection.samples if sample.complete_episode]
    episode_ids = {sample.episode_id for sample in complete}
    if len(episode_ids) < 2:
        payload["status"] = "unavailable"
        payload["detail"] = (
            f"{len(episode_ids)} complete episode(s) collected; an episode-level train/tuning "
            "split needs at least two, and a fit on fewer would report its own training error"
        )
        _write(payload, output)
        return payload

    ensemble, report = fit_ensemble(
        complete,
        value_settings,
        return_definition_hash=sha256_json(
            {
                "kind": "ordinary_discounted_continuation_return",
                "gamma": reward.gamma,
                "reward_revision": reward.revision,
                "policy_identity": policy_identity,
                "environment_version": settings.environment_version,
            }
        ),
        seed=seed,
        tuning_fraction=tuning_fraction,
    )
    payload["status"] = "completed"
    payload["bundle_id"] = ensemble.bundle_id
    payload["support_thresholds"] = ensemble.support.model_dump(mode="json")
    payload["fit_report"] = report.as_dict()
    payload["observed"] = {
        "overall": report.overall.as_dict(),
        "groups": [group.as_dict() for group in report.groups],
    }
    payload["caveat"] = (
        "these are observed errors on a tuning split of a bounded collection under one frozen "
        "controller. They are not a held-out generalisation claim, and the support thresholds "
        "shipped in value-v1 are declared placeholders rather than values derived from "
        "calibration data."
    )
    _write(payload, output)
    return payload


def run_calibration_fit(
    *,
    env_config_id: str | Path | None = None,
    episodes: int = 16,
    seed: int = 0,
    scenario_id: str | None = None,
    policy: str = "held-neutral",
    planner_deadline_s: float = 5.0,
    min_support: int = 30,
    holdout_fraction: float = 0.3,
    max_steps: int | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Collect forecast/realisation pairs and fit the probability calibrator.

    Returns ``status='unavailable'`` with its reason whenever no map could be
    fitted, which is the expected outcome of a small collection: a monotone map
    through a handful of points reproduces them exactly and says nothing about
    the next forecast.
    """
    from .calibration import fit_calibrator
    from .dataset import collect_calibration_samples, rollout_enabled_config

    base = load_env_config(resolve_config_id(env_config_id, "env-v1"))
    settings = rollout_enabled_config(base, planner_deadline_s=planner_deadline_s)
    callable_policy, policy_identity = _named_policy(policy, seed)

    collection = collect_calibration_samples(
        settings,
        policy=callable_policy,
        policy_identity=policy_identity,
        episodes=episodes,
        seed=seed,
        scenario_id=scenario_id,
        max_steps=max_steps,
    )
    payload: dict[str, Any] = {
        "job": "fit-calibration",
        "env_config": settings.revision,
        "environment_version": settings.environment_version,
        "operational_planner_deadline_s": base.planner_deadline_s,
        "collection": collection.as_dict(),
    }
    episode_ids = {sample.episode_id for sample in collection.samples}
    if len(episode_ids) < 2:
        payload["status"] = "unavailable"
        payload["detail"] = (
            f"{len(collection.samples)} labelled sample(s) across {len(episode_ids)} episode(s); "
            "a held-out calibration split needs at least two episodes, and a calibrator scored "
            "on the episodes it was fitted on reports its own training error"
        )
        _write(payload, output)
        return payload

    fit = fit_calibrator(
        collection.samples,
        forecaster_version=collection.forecaster_version,
        seed=seed,
        holdout_fraction=holdout_fraction,
        min_support=min_support,
    )
    payload["fit"] = fit.as_dict()
    payload["status"] = "completed" if fit.calibrator is not None else "unavailable"
    if fit.calibrator is None:
        payload["detail"] = (
            "no event could be calibrated; every event is listed in `fit.refusals` with its "
            "reason and stays published as an uncalibrated raw frequency"
        )
    payload["caveat"] = (
        "the calibrator was fitted under one frozen controller and one scenario selection, at a "
        "raised planner deadline so re-simulation could complete. It is not frozen before a "
        "final test, so serving reports its output as uncalibrated until an operator freezes it."
    )
    _write(payload, output)
    return payload


def _write(payload: dict[str, Any], output: Path | None) -> None:
    """Write the record beside the run when a path was given."""
    if output is None:
        return
    import json

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


__all__ += ["run_calibration_fit", "run_value_fit"]
