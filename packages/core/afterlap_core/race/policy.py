from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .environment import FEATURES, PROFILES, SCALES
from .session import RaceSession
from .settings import RaceSettings


def model_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def policy_manifest(session: RaceSession) -> dict[str, Any]:
    return {
        **session.manifest(),
        "model_hash": model_hash(),
        "action_profiles": [p.value for p in PROFILES],
        "own_features": FEATURES,
        "own_scales": SCALES,
        "observation_size": 40,
        "authority": "battery deployment only; automatic racecraft",
        "reward_version": "race-bms-reward-v1",
    }


def policy_paths(path: Path) -> tuple[Path, Path]:
    archive = path if path.suffix == ".zip" else Path(f"{path}.zip")
    return archive, archive.with_suffix(".manifest.json")


def load_policy(path: Path, session: RaceSession) -> Any:
    archive, sidecar = policy_paths(path)
    manifest = json.loads(sidecar.read_text())
    expected = policy_manifest(session)
    for key in (
        "model_hash",
        "model_version",
        "environment_version",
        "action_profiles",
        "own_features",
        "own_scales",
        "observation_size",
        "authority",
        "reward_version",
    ):
        if json.dumps(manifest.get(key)) != json.dumps(expected[key]):
            raise ValueError(f"incompatible saved policy {key}; retraining with this model is required")
    from stable_baselines3 import PPO

    return PPO.load(archive, device="cpu")


def train_policy(
    settings: RaceSettings,
    output: Path,
    *,
    steps: int,
    workers: int = 1,
    rollout_steps: int = 128,
    batch_size: int = 64,
) -> dict[str, Any]:
    if workers < 1 or workers > 64 or rollout_steps < 2 or steps < 1:
        raise ValueError("workers must be 1-64, rollout steps at least 2, and total steps positive")
    samples = workers * rollout_steps
    if batch_size < 2 or batch_size > samples or samples % batch_size:
        raise ValueError("batch size must be at least 2 and divide workers times rollout steps")
    if settings.seed + workers - 1 > 2**32 - 1:
        raise ValueError("worker seeds exceed the supported 32-bit seed range")
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    from .environment import RaceEnv

    torch.set_num_threads(1)
    archive, sidecar = policy_paths(output)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() or sidecar.exists():
        raise FileExistsError("policy output already exists; choose a new experiment name")
    monitors = archive.with_suffix(".episodes")
    env = make_vec_env(
        RaceEnv,
        n_envs=workers,
        seed=settings.seed,
        env_kwargs={"settings": settings},
        monitor_dir=str(monitors),
        monitor_kwargs={"info_keywords": ("episode_seed",)},
        vec_env_cls=SubprocVecEnv if workers > 1 else DummyVecEnv,
        vec_env_kwargs={"start_method": "spawn"} if workers > 1 else {},
    )
    try:
        model = PPO(
            "MlpPolicy",
            env,
            seed=settings.seed,
            n_steps=rollout_steps,
            batch_size=batch_size,
            verbose=1,
            gamma=0.996672,
            device="cpu",
        )
        model.learn(total_timesteps=steps)
        model.save(str(archive))
        training = {
            "requested_steps": steps,
            "collected_steps": model.num_timesteps,
            "workers": workers,
            "worker_seeds": list(range(settings.seed, settings.seed + workers)),
            "rollout_steps": rollout_steps,
            "batch_size": batch_size,
            "gamma": 0.996672,
            "monitor_directory": str(monitors),
        }
        sidecar.write_text(
            json.dumps({**policy_manifest(RaceSession(settings)), "training": training}, indent=2)
        )
        return {"status": "training_completed", "output": str(archive), "promoted": False, **training}
    finally:
        env.close()
