from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .environment import FEATURES, PROFILES, SCALES
from .session import RaceSession


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


def load_policy(path: Path, session: RaceSession) -> Any:
    from stable_baselines3 import PPO

    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    expected = policy_manifest(session)
    for key in ("model_hash", "environment_version", "action_profiles", "observation_size", "reward_version"):
        if manifest.get(key) != expected[key]:
            raise ValueError(f"incompatible saved policy {key}; retraining with this model is required")
    return PPO.load(path, device="cpu")
