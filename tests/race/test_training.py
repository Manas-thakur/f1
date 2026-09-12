from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from afterlap_core.race.environment import RaceEnv
from afterlap_core.race.policy import load_policy, policy_manifest, policy_paths, train_policy
from afterlap_core.race.session import RaceSession
from afterlap_core.race.settings import RaceSettings


def test_policy_paths_preserve_dotted_names():
    expected = Path("run.v1.zip"), Path("run.v1.manifest.json")
    assert policy_paths(Path("run.v1")) == expected
    assert policy_paths(Path("run.v1.zip")) == expected


@pytest.mark.parametrize(
    ("workers", "rollout", "batch"), [(0, 4, 4), (65, 4, 4), (2, 1, 2), (2, 4, 3), (1, 4, 8)]
)
def test_invalid_collection_sizes_fail_before_startup(tmp_path, workers, rollout, batch):
    with pytest.raises(ValueError):
        train_policy(
            RaceSettings(),
            tmp_path / "model",
            steps=4,
            workers=workers,
            rollout_steps=rollout,
            batch_size=batch,
        )


@pytest.mark.parametrize(
    "field", ["model_hash", "own_features", "own_scales", "action_profiles", "observation_size"]
)
def test_missing_and_incompatible_sidecars_fail_before_loading(tmp_path, field):
    session = RaceSession(RaceSettings(cars=1, time_limit_s=1))
    output = tmp_path / "missing.v1"
    with pytest.raises(FileNotFoundError):
        load_policy(output, session)
    _, sidecar = policy_paths(output)
    manifest = policy_manifest(session)
    manifest[field] = "incompatible"
    sidecar.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=field):
        load_policy(output, session)


def test_two_worker_training_repeated_episodes_and_save_load(tmp_path):
    pytest.importorskip("stable_baselines3")
    settings = RaceSettings(cars=1, time_limit_s=1, seed=123)
    output = tmp_path / "policy.v1"
    result = train_policy(settings, output, steps=8, workers=2, rollout_steps=4, batch_size=4)
    assert result["collected_steps"] == 8
    assert result["worker_seeds"] == [123, 124]
    archive, sidecar = policy_paths(output)
    assert archive.is_file()
    assert json.loads(sidecar.read_text())["training"]["workers"] == 2
    sequences = []
    for rank in range(2):
        with (Path(result["monitor_directory"]) / f"{rank}.monitor.csv").open() as stream:
            next(stream)
            rows = list(csv.DictReader(stream))
        seeds = [int(row["episode_seed"]) for row in rows]
        assert len(seeds) == len(set(seeds)) == 4
        assert seeds[0] == 123 + rank
        sequences.append(seeds)
    assert set(sequences[0]).isdisjoint(sequences[1])
    env = RaceEnv(settings)
    observation, _ = env.reset(seed=999)
    assert env.session is not None
    bare = load_policy(output, env.session)
    zipped = load_policy(archive, env.session)
    action = int(bare.predict(observation, deterministic=True)[0])
    assert action == int(zipped.predict(observation, deterministic=True)[0])
    observation, reward, terminated, truncated, info = env.step(action)
    assert np.isfinite(observation).all() and np.isfinite(reward)
    assert truncated and not terminated and info["failure"] is None
    with pytest.raises(FileExistsError):
        train_policy(settings, output, steps=8, workers=2, rollout_steps=4, batch_size=4)
