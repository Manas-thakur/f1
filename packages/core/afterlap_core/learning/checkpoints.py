"""Atomic training checkpoints.

A checkpoint holds everything needed to resume and to prove what produced it:
the SB3 archive (actor, twin critics, target critics, optimisers and the entropy
coefficient), the replay buffer, every random generator state, the environment
version, the normaliser, the step count and the run manifest.

**Atomic.** Everything is written into a staging directory and moved into place
with a single ``os.replace`` of the directory. A reader therefore never observes
a checkpoint whose replay buffer belongs to a different step count than its
weights.

**Resume reproduces subsequent deterministic evaluation.** Bitwise equivalence
across platforms or devices is not promised and is not claimed; what is checked
is that a resumed run and an uninterrupted run agree on a deterministic
evaluation from the same seed on the same machine.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import random
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ..paths import atomic_write_json, sha256_file

__all__ = [
    "CHECKPOINT_SCHEMA",
    "CheckpointError",
    "CheckpointManifest",
    "RngState",
    "list_checkpoints",
    "load_checkpoint_manifest",
    "read_rng_state",
    "restore_rng_state",
    "save_checkpoint",
    "verify_checkpoint",
]

CHECKPOINT_SCHEMA = "afterlap.learning.checkpoint/1"

_MODEL_FILE = "model.zip"
_REPLAY_FILE = "replay_buffer.pkl"
_RNG_FILE = "rng_state.pt"
_MANIFEST_FILE = "checkpoint.json"


class CheckpointError(RuntimeError):
    """A checkpoint could not be written, read or verified."""


@dataclass(frozen=True, slots=True)
class RngState:
    """Every generator that affects a training run."""

    python: Any
    numpy: Any
    torch: Any
    env_seeds: tuple[int, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "python": self.python,
            "numpy": self.numpy,
            "torch": self.torch,
            "env_seeds": list(self.env_seeds),
        }


def read_rng_state(env_seeds: tuple[int, ...] = ()) -> RngState:
    return RngState(
        python=random.getstate(),
        numpy=np.random.get_state(),
        torch=torch.get_rng_state(),
        env_seeds=env_seeds,
    )


def restore_rng_state(state: RngState) -> None:
    random.setstate(state.python)
    np.random.set_state(state.numpy)
    torch.set_rng_state(state.torch)


@dataclass(frozen=True, slots=True)
class CheckpointManifest:
    """What a checkpoint declares about itself."""

    schema: str
    run_id: str
    step_count: int
    created_at: str
    environment_version: str
    feature_hash: str
    reward_revision: str
    algorithm_config: dict[str, Any]
    env_config_hash: str
    artifact_hashes: dict[str, str]
    library_versions: dict[str, str]
    normalizer: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    seeds: tuple[int, ...] = ()
    has_replay_buffer: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "step_count": self.step_count,
            "created_at": self.created_at,
            "environment_version": self.environment_version,
            "feature_hash": self.feature_hash,
            "reward_revision": self.reward_revision,
            "algorithm_config": self.algorithm_config,
            "env_config_hash": self.env_config_hash,
            "artifact_hashes": self.artifact_hashes,
            "library_versions": self.library_versions,
            "normalizer": self.normalizer,
            "metrics": self.metrics,
            "seeds": list(self.seeds),
            "has_replay_buffer": self.has_replay_buffer,
        }


def _library_versions() -> dict[str, str]:
    versions = {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}
    with contextlib.suppress(ImportError):  # pragma: no cover - optional
        import stable_baselines3

        versions["stable_baselines3"] = stable_baselines3.__version__
    with contextlib.suppress(ImportError):  # pragma: no cover - optional
        import gymnasium

        versions["gymnasium"] = gymnasium.__version__
    return versions


def save_checkpoint(
    directory: Path,
    model: Any,
    *,
    run_id: str,
    step_count: int,
    environment_version: str,
    feature_hash: str,
    reward_revision: str,
    algorithm_config: dict[str, Any],
    env_config_hash: str,
    rng: RngState | None = None,
    normalizer: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    seeds: tuple[int, ...] = (),
    save_replay_buffer: bool = True,
) -> Path:
    """Write one checkpoint atomically and return its directory.

    ``model`` is an SB3 algorithm. Its ``save`` writes actor, twin critics,
    target critics, optimiser states and the entropy coefficient into one
    archive; the replay buffer is written separately because SB3 keeps it out of
    the model archive by design.
    """
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=str(directory.parent)))
    try:
        model.save(staging / _MODEL_FILE)
        has_replay = False
        if save_replay_buffer and hasattr(model, "save_replay_buffer"):
            model.save_replay_buffer(staging / _REPLAY_FILE)
            has_replay = (staging / _REPLAY_FILE).is_file()
        torch.save((rng or read_rng_state(seeds)).as_payload(), staging / _RNG_FILE)

        artifacts = {
            path.name: sha256_file(path)
            for path in sorted(staging.iterdir())
            if path.is_file() and path.name != _MANIFEST_FILE
        }
        manifest = CheckpointManifest(
            schema=CHECKPOINT_SCHEMA,
            run_id=run_id,
            step_count=int(step_count),
            created_at=datetime.now(UTC).isoformat(),
            environment_version=environment_version,
            feature_hash=feature_hash,
            reward_revision=reward_revision,
            algorithm_config=dict(algorithm_config),
            env_config_hash=env_config_hash,
            artifact_hashes=artifacts,
            library_versions=_library_versions(),
            normalizer=normalizer,
            metrics=dict(metrics or {}),
            seeds=tuple(seeds),
            has_replay_buffer=has_replay,
        )
        atomic_write_json(staging / _MANIFEST_FILE, manifest.as_dict())

        if directory.exists():
            retired = directory.with_name(f"{directory.name}.retired-{os.getpid()}")
            directory.replace(retired)
            shutil.rmtree(retired, ignore_errors=True)
        staging.replace(directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return directory


def load_checkpoint_manifest(directory: Path) -> CheckpointManifest:
    path = Path(directory) / _MANIFEST_FILE
    if not path.is_file():
        raise CheckpointError(f"{directory} has no {_MANIFEST_FILE}; it is not a checkpoint")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise CheckpointError(f"unrecognised checkpoint schema {payload.get('schema')!r}")
    return CheckpointManifest(
        schema=payload["schema"],
        run_id=payload["run_id"],
        step_count=int(payload["step_count"]),
        created_at=payload["created_at"],
        environment_version=payload["environment_version"],
        feature_hash=payload["feature_hash"],
        reward_revision=payload["reward_revision"],
        algorithm_config=dict(payload["algorithm_config"]),
        env_config_hash=payload["env_config_hash"],
        artifact_hashes=dict(payload["artifact_hashes"]),
        library_versions=dict(payload["library_versions"]),
        normalizer=payload.get("normalizer"),
        metrics=dict(payload.get("metrics") or {}),
        seeds=tuple(int(s) for s in payload.get("seeds") or ()),
        has_replay_buffer=bool(payload.get("has_replay_buffer", True)),
    )


def verify_checkpoint(directory: Path) -> CheckpointManifest:
    """Re-hash every declared artifact before anything is loaded."""
    directory = Path(directory)
    manifest = load_checkpoint_manifest(directory)
    for name, expected in sorted(manifest.artifact_hashes.items()):
        path = directory / name
        if not path.is_file():
            raise CheckpointError(f"checkpoint artifact {name!r} is absent from {directory}")
        actual = sha256_file(path)
        if actual != expected:
            raise CheckpointError(
                f"checkpoint artifact {name!r} hashes to {actual}, but the manifest declares {expected}"
            )
    return manifest


def restore_into(
    directory: Path,
    model: Any,
    *,
    expected_environment_version: str | None = None,
    expected_feature_hash: str | None = None,
    load_replay_buffer: bool = True,
) -> CheckpointManifest:
    """Load weights, replay and RNG state back into ``model``.

    A checkpoint from a different environment revision or feature schema is
    refused: resuming across either would train a critic on transitions whose
    action and observation semantics have changed underneath it.
    """
    directory = Path(directory)
    manifest = verify_checkpoint(directory)
    if (
        expected_environment_version is not None
        and manifest.environment_version != expected_environment_version
    ):
        raise CheckpointError(
            f"checkpoint environment {manifest.environment_version!r} does not match "
            f"{expected_environment_version!r}; the replay buffer is not interchangeable"
        )
    if expected_feature_hash is not None and manifest.feature_hash != expected_feature_hash:
        raise CheckpointError(
            f"checkpoint feature schema {manifest.feature_hash} does not match {expected_feature_hash}"
        )
    model.set_parameters(str(directory / _MODEL_FILE), device=model.device)
    if load_replay_buffer and manifest.has_replay_buffer and hasattr(model, "load_replay_buffer"):
        model.load_replay_buffer(str(directory / _REPLAY_FILE))
    payload = torch.load(directory / _RNG_FILE, map_location="cpu", weights_only=False)
    restore_rng_state(
        RngState(
            python=payload["python"],
            numpy=payload["numpy"],
            torch=payload["torch"],
            env_seeds=tuple(int(s) for s in payload.get("env_seeds") or ()),
        )
    )
    model.num_timesteps = manifest.step_count
    return manifest


def list_checkpoints(root: Path) -> tuple[Path, ...]:
    root = Path(root)
    if not root.is_dir():
        return ()
    return tuple(sorted(p for p in root.iterdir() if p.is_dir() and (p / _MANIFEST_FILE).is_file()))
