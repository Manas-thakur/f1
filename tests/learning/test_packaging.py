"""A verified checkpoint becomes a loadable bundle with a card that undersells it.

The point of these tests is that the honest labels survive the packaging step.
A bundle is the artifact a reviewer reads *instead of* the training log, so if a
smoke run can be packaged into something that reads like a trained model, the
whole promotion protocol is decorative. Every test below is either "the label
is present" or "the number was not invented".

No training happens here. A shape-only environment is enough to construct real
SB3 networks and write a real checkpoint, and using the simulator environment
would make a packaging test depend on the physics.
"""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch", reason="a bundle holds torch state dicts")
pytest.importorskip("stable_baselines3", reason="a checkpoint is an SB3 archive")

import gymnasium as gym
import numpy as np

from afterlap_contracts import ApprovalStatus
from afterlap_core.feature_manifest import ENERGY_V1, OBSERVATION_SIZE
from afterlap_core.learning.actions import action_space
from afterlap_core.learning.checkpoints import save_checkpoint
from afterlap_core.learning.config import load_env_config
from afterlap_core.learning.packaging import (
    PackagingError,
    TrainingEvidence,
    code_revision,
    package_checkpoint,
    training_data_hash,
)
from afterlap_core.learning.policy import load_actor
from afterlap_core.learning.serving import load_bundle
from afterlap_core.paths import atomic_write_json

RULE_FAMILY = "synthetic-pack-v1"


class _ShapeOnlyEnv(gym.Env):
    """Spaces only. Nothing is trained and nothing is stepped."""

    def __init__(self) -> None:
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_SIZE,), dtype=np.float32
        )
        self.action_space = action_space()

    def reset(self, *, seed=None, options=None):
        return np.zeros(OBSERVATION_SIZE, dtype=np.float32), {}

    def step(self, action):
        return np.zeros(OBSERVATION_SIZE, dtype=np.float32), 0.0, True, False, {}


def _model():
    from stable_baselines3 import SAC

    return SAC(
        "MlpPolicy",
        _ShapeOnlyEnv(),
        policy_kwargs={"net_arch": [32, 32]},
        buffer_size=64,
        learning_starts=1_000_000,
        seed=7,
        device="cpu",
        verbose=0,
    )


def _write_run(tmp_path, *, status="completed", is_smoke_run=False, seeds=(11,), steps=900):
    """A run directory shaped exactly as ``train`` leaves one."""
    settings = load_env_config()
    run_directory = tmp_path / "learning" / "run-under-test"
    checkpoint_root = run_directory / "checkpoints"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        run_directory / "run_manifest.json",
        {
            "run_id": "run-under-test",
            "seed": seeds[0],
            "requested_timesteps": steps,
            "scenario_id": "two-straight-counterattack",
            "is_smoke_run": is_smoke_run,
            "status": status,
            "result": {
                "status": status,
                "requested_timesteps": steps,
                "completed_timesteps": steps,
                "wall_clock_s": 12.5,
                "transitions_per_second": 4.2,
                "is_smoke_run": is_smoke_run,
                "hardware": "test-hardware",
                "failure_detail": None if status == "completed" else "a recorded failure",
                "metrics": {
                    "optimiser": {
                        "actor_loss": {"mean": 0.25, "count": 100},
                        "critic_loss": {"mean": 1.5, "count": 100},
                    },
                    "episode_return": {"mean": -64.9, "count": 25},
                },
            },
        },
    )
    return save_checkpoint(
        checkpoint_root / "final",
        _model(),
        run_id="run-under-test",
        step_count=steps,
        environment_version=settings.environment_version,
        feature_hash=ENERGY_V1.content_hash(),
        reward_revision="objective-v1",
        algorithm_config={"algorithm": "SAC", "net_arch": [32, 32]},
        env_config_hash=settings.content_hash,
        seeds=seeds,
        save_replay_buffer=False,
    )


@pytest.fixture
def packaged_smoke(tmp_path):
    checkpoint = _write_run(tmp_path, is_smoke_run=True)
    return package_checkpoint(
        checkpoint,
        bundle_directory=tmp_path / "bundle",
        rule_family=RULE_FAMILY,
        deterministic_returns=(),
        deterministic_detail="not requested for this fixture",
    )


@pytest.fixture
def packaged_trained(tmp_path):
    checkpoint = _write_run(tmp_path, is_smoke_run=False, seeds=(11, 29))
    return package_checkpoint(
        checkpoint,
        bundle_directory=tmp_path / "bundle",
        rule_family=RULE_FAMILY,
        deterministic_returns=(-64.5, -65.1),
        deterministic_detail="2 deterministic episodes from seed 101",
    )


class TestTheBundleIsLoadable:
    def test_the_written_bundle_round_trips_through_the_validating_loader(self, packaged_smoke) -> None:
        loaded = load_bundle(packaged_smoke.directory)
        assert loaded.manifest.rule_family == RULE_FAMILY
        assert loaded.manifest.feature_schema_hash == ENERGY_V1.content_hash()
        assert loaded.training_report is not None
        assert loaded.training_report["schema"] == "afterlap.learning.training_report/1"

    def test_the_training_report_is_hash_covered_like_every_other_artifact(self, packaged_smoke) -> None:
        """An unhashed artifact is a claim nothing verifies."""
        payload = json.loads((packaged_smoke.directory / "bundle.json").read_text(encoding="utf-8"))
        assert "training_report.json" in payload["artifact_hashes"]
        report = packaged_smoke.directory / "training_report.json"
        report.write_text("{}", encoding="utf-8")
        with pytest.raises(Exception, match="hashes to"):
            load_bundle(packaged_smoke.directory)

    def test_the_packaged_actor_is_runnable_and_matches_the_checkpoint(self, packaged_smoke) -> None:
        loaded = load_bundle(packaged_smoke.directory)
        policy = load_actor(loaded.actor_state, bundle_id=loaded.manifest.id)
        observation = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        first = policy.act(observation)
        assert first.shape == (2,)
        np.testing.assert_array_equal(policy.act(observation), first)


class TestPackagingIsNotPromotion:
    def test_a_packaged_bundle_is_never_approved(self, packaged_trained) -> None:
        assert packaged_trained.manifest.approval_status is ApprovalStatus.UNEVALUATED
        loaded = load_bundle(packaged_trained.directory)
        assert loaded.approved is False
        assert loaded.learned_contribution_enabled is False

    def test_the_report_says_promotion_was_not_assessed(self, packaged_trained) -> None:
        assert "not assessed by packaging" in packaged_trained.training_report["promotion"]

    def test_packaging_takes_no_argument_that_could_declare_approval(self) -> None:
        import inspect

        parameters = inspect.signature(package_checkpoint).parameters
        assert "approval_status" not in parameters
        assert "approved" not in parameters


class TestHonestLabels:
    def test_a_smoke_run_is_labelled_a_smoke_run_everywhere(self, packaged_smoke) -> None:
        """The label a reviewer would rely on, in every place they might look."""
        assert packaged_smoke.bundle_id.startswith("smoke/")
        card = (packaged_smoke.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Smoke run, not a trained model" in card
        assert "fabricated result" in card
        assert packaged_smoke.training_report["observed"]["is_smoke_run"] is True
        assert any("smoke run" in note.lower() for note in _limitation_lines(card))

    def test_a_trained_run_without_a_benchmark_says_so_rather_than_implying_one(
        self, packaged_trained
    ) -> None:
        card = (packaged_trained.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Trained, not evaluated for promotion" in card
        assert "no benefit over the baseline has been measured" in card
        assert packaged_trained.manifest.benchmark_report_hash is None

    def test_a_failed_run_is_packaged_as_failed(self, tmp_path) -> None:
        checkpoint = _write_run(tmp_path, status="non_finite_loss")
        packaged = package_checkpoint(
            checkpoint, bundle_directory=tmp_path / "bundle", rule_family=RULE_FAMILY
        )
        card = (packaged.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Training did not complete" in card
        assert packaged.evidence.completed is False

    def test_a_single_seed_is_named_as_insufficient(self, packaged_smoke) -> None:
        card = (packaged_smoke.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Only 1 training seed(s) were recorded" in card

    def test_an_absent_ensemble_is_stated_not_implied(self, packaged_smoke) -> None:
        card = (packaged_smoke.directory / "model_card.md").read_text(encoding="utf-8")
        assert "No continuation ensemble is bundled" in card
        assert packaged_smoke.training_report["architecture"]["continuation_ensemble"] is None


class TestObservedMetricsAreObserved:
    def test_the_recorded_losses_reach_the_card_and_the_report(self, packaged_trained) -> None:
        card = (packaged_trained.directory / "model_card.md").read_text(encoding="utf-8")
        assert "actor_loss" in card
        assert "critic_loss" in card
        losses = packaged_trained.training_report["observed"]["losses"]
        assert losses["actor_loss"]["mean"] == 0.25
        assert losses["critic_loss"]["count"] == 100

    def test_a_deterministic_evaluation_that_ran_is_reported_with_its_episodes(
        self, packaged_trained
    ) -> None:
        card = (packaged_trained.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Deterministic evaluation returns (2 episode(s))" in card
        assert "mean -64.8000" in card

    def test_a_deterministic_evaluation_that_did_not_run_is_absent_not_zero(self, packaged_smoke) -> None:
        """The null-not-zero rule, applied to a metric rather than a channel."""
        card = (packaged_smoke.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Deterministic evaluation: not run for this bundle" in card
        assert "0.0" not in card.split("Deterministic evaluation:")[1].split("\n")[0]
        assert packaged_smoke.training_report["observed"]["deterministic_evaluation_returns"] == []

    def test_a_run_with_no_recorded_loss_says_that_rather_than_showing_none(self, tmp_path) -> None:
        evidence = TrainingEvidence(
            run_id="empty", status="completed", requested_timesteps=1, completed_timesteps=1
        )
        assert evidence.losses == {}
        checkpoint = _write_run(tmp_path)
        (checkpoint.parent.parent / "run_manifest.json").unlink()
        packaged = package_checkpoint(
            checkpoint, bundle_directory=tmp_path / "bundle", rule_family=RULE_FAMILY
        )
        card = (packaged.directory / "model_card.md").read_text(encoding="utf-8")
        assert "Observed losses: none recorded" in card


class TestIdentityAndReproducibility:
    def test_the_card_carries_the_optimiser_updated_parameter_count(self, packaged_trained) -> None:
        card = (packaged_trained.directory / "model_card.md").read_text(encoding="utf-8")
        assert "optimiser-updated parameters" in card
        assert f"{packaged_trained.architecture.optimiser_updated_parameters:,}" in card
        assert "`sac/actor`" in card or "sac/actor" in card

    def test_a_dirty_working_tree_is_reported_as_dirty(self) -> None:
        revision = code_revision()
        assert revision
        assert revision.startswith("unknown:") or len(revision.split("-")[0]) == 40

    def test_the_training_data_hash_identifies_the_generator_and_says_so(self, packaged_trained) -> None:
        """There is no dataset file; the hash must not imply one."""
        identity = packaged_trained.training_report["identity"]
        assert identity["training_data_hash"].startswith("sha256:")
        assert "not a stored dataset" in identity["training_data_kind"]
        card = (packaged_trained.directory / "model_card.md").read_text(encoding="utf-8")
        assert identity["training_data_hash"] in card

    def test_the_generator_hash_changes_with_the_seeds_and_the_budget(self) -> None:
        settings = load_env_config()
        base = training_data_hash(
            env_config=settings,
            scenario_id="x",
            seeds=(11,),
            total_timesteps=1000,
            reward_revision="objective-v1",
        )
        assert base != training_data_hash(
            env_config=settings,
            scenario_id="x",
            seeds=(11, 29),
            total_timesteps=1000,
            reward_revision="objective-v1",
        )
        assert base != training_data_hash(
            env_config=settings,
            scenario_id="x",
            seeds=(11,),
            total_timesteps=2000,
            reward_revision="objective-v1",
        )
        assert base == training_data_hash(
            env_config=settings,
            scenario_id="x",
            seeds=(11,),
            total_timesteps=1000,
            reward_revision="objective-v1",
        )


class TestRefusals:
    def test_a_checkpoint_without_a_model_archive_is_refused(self, tmp_path) -> None:
        checkpoint = _write_run(tmp_path)
        (checkpoint / "model.zip").unlink()
        with pytest.raises(Exception, match="checkpoint artifact"):
            package_checkpoint(checkpoint, bundle_directory=tmp_path / "bundle", rule_family=RULE_FAMILY)

    def test_a_checkpoint_from_another_feature_revision_is_refused(self, tmp_path) -> None:
        settings = load_env_config()
        checkpoint_root = tmp_path / "learning" / "other" / "checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        checkpoint = save_checkpoint(
            checkpoint_root / "final",
            _model(),
            run_id="other",
            step_count=10,
            environment_version=settings.environment_version,
            feature_hash="sha256:" + "a" * 64,
            reward_revision="objective-v1",
            algorithm_config={"algorithm": "SAC"},
            env_config_hash=settings.content_hash,
            save_replay_buffer=False,
        )
        with pytest.raises(PackagingError, match="does not match the current"):
            package_checkpoint(checkpoint, bundle_directory=tmp_path / "bundle", rule_family=RULE_FAMILY)

    def test_a_tampered_checkpoint_is_refused_before_anything_is_read(self, tmp_path) -> None:
        checkpoint = _write_run(tmp_path)
        (checkpoint / "rng_state.pt").write_bytes(b"not a tensor")
        with pytest.raises(Exception, match="hash"):
            package_checkpoint(checkpoint, bundle_directory=tmp_path / "bundle", rule_family=RULE_FAMILY)


def _limitation_lines(card: str) -> list[str]:
    if "## Limitations" not in card:
        return []
    tail = card.split("## Limitations", 1)[1]
    return [line.strip("- ").strip() for line in tail.splitlines() if line.startswith("- ")]
