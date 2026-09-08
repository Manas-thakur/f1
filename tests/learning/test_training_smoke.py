"""SMOKE test. Not a trained product, and never to be reported as one.

``SAC_IMPLEMENTATION.md`` step 2: *"Run a 10,000-transition smoke job solely to
verify finite losses, checkpoints, resume and complete episodes. It is not a
trained product."* These tests run a much shorter version of exactly that job.

**Nothing here measures model quality.** A reward number produced by these tests
is the reward of an almost-untrained network over a handful of episodes on one
synthetic scenario. It is not evidence of anything and it must never appear in a
release report as a training result.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import numpy as np
import pytest

from afterlap_core.learning.checkpoints import (
    CheckpointError,
    list_checkpoints,
    load_checkpoint_manifest,
    verify_checkpoint,
)
from afterlap_core.learning.config import EnvConfig, SacConfig, load_sac_config
from afterlap_core.learning.train_sac import (
    SMOKE_WARNING,
    TrainingStatus,
    benchmark_throughput,
    deterministic_evaluation,
    smoke_run,
)

from .conftest import SMOKE_SCENARIO

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def smoke_config(request: pytest.FixtureRequest) -> EnvConfig:
    from afterlap_core.learning.config import load_env_config

    del request
    # A short episode cap so a few thousand transitions cover many complete
    # episodes rather than one long one.
    return dataclasses.replace(load_env_config(), max_episode_steps=20)


@pytest.fixture(scope="module")
def smoke_algorithm() -> SacConfig:
    return load_sac_config()


@pytest.fixture(scope="module")
def smoke_result(smoke_config: EnvConfig, smoke_algorithm: SacConfig, tmp_path_factory):
    root = tmp_path_factory.mktemp("smoke-root")
    return smoke_run(
        transitions=600,
        seed=11,
        scenario_id=SMOKE_SCENARIO,
        config=smoke_config,
        algorithm=smoke_algorithm,
        root=root,
        n_envs=1,
        learning_starts=100,
        checkpoint_every=200,
    ), root


class TestThroughputBenchmark:
    def test_a_short_benchmark_reports_a_real_rate(self, smoke_config: EnvConfig) -> None:
        """A budget is chosen from a measurement, never from a guess."""
        measured = benchmark_throughput(smoke_config, transitions=40, scenario_id=SMOKE_SCENARIO, seed=11)
        assert measured["transitions"] == 40
        assert measured["wall_clock_s"] > 0.0
        assert measured["transitions_per_second"] > 0.0
        # Reset cost is reported separately: the declared warm-up is scenario
        # setup, not a scored transition, and folding it into one rate would
        # misrepresent the steady-state cost of a policy step.
        assert measured["step_transitions_per_second"] >= measured["transitions_per_second"]
        assert measured["resets"] >= 1
        assert measured["reset_wall_clock_s"] > 0.0
        assert measured["planner_mode"] == smoke_config.planner_mode
        assert "not a trained-model figure" in measured["note"]
        assert measured["hardware"]


class TestSmokeRun:
    def test_the_run_completes_and_is_labelled_a_smoke_run(self, smoke_result) -> None:
        result, _ = smoke_result
        assert result.status is TrainingStatus.COMPLETED, result.failure_detail
        assert result.is_smoke_run is True
        assert result.warning == SMOKE_WARNING
        assert "NOT a trained model" in result.warning
        assert result.completed_timesteps >= 600
        assert result.transitions_per_second > 0.0

    def test_losses_stayed_finite(self, smoke_result) -> None:
        result, _ = smoke_result
        # The guard stops the run the moment a tracked statistic goes non-finite.
        assert result.status is not TrainingStatus.NON_FINITE_LOSS
        terms = result.metrics["reward_terms"]
        for name, stats in terms.items():
            if stats is None:
                continue
            assert math.isfinite(stats["mean"]), name
        # Critic loss, actor loss and the entropy coefficient are read back from
        # SB3's own logger, so a finite-loss claim rests on the library's numbers
        # rather than on a re-derivation here.
        optimiser = result.metrics["optimiser"]
        assert "critic_loss" in optimiser and optimiser["critic_loss"] is not None
        assert "ent_coef" in optimiser and optimiser["ent_coef"] is not None
        for name, stats in optimiser.items():
            assert math.isfinite(stats["mean"]), name

    def test_complete_episodes_were_produced(self, smoke_result) -> None:
        result, _ = smoke_result
        metrics = result.metrics
        assert metrics["episode_return"] is not None
        assert metrics["episode_return"]["count"] >= 1
        assert metrics["finished_episodes"] + metrics["truncated_episodes"] >= 1

    def test_physical_outcomes_are_reported_beside_the_utility(self, smoke_result) -> None:
        result, _ = smoke_result
        metrics = result.metrics
        # Position, elapsed time and energy are separate fields; the
        # dimensionless return never stands in for them.
        assert "finish_position" in metrics
        assert "elapsed_time_s" in metrics
        assert "final_energy_j" in metrics
        # The withdrawal rate sits beside the reward on purpose.
        assert 0.0 <= metrics["withdrawal_rate"] <= 1.0

    def test_the_run_manifest_records_what_produced_it(self, smoke_result) -> None:
        result, _ = smoke_result
        manifest = json.loads((result.run_directory / "run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["is_smoke_run"] is True
        assert manifest["status"] == "completed"
        assert manifest["environment_version"] == result.environment_version
        assert manifest["feature_hash"] == result.feature_hash
        assert manifest["objective_hash"].startswith("sha256:")
        assert manifest["hardware"]
        assert manifest["algorithm"]["net_arch"] == [256, 256]


class TestCheckpointing:
    def test_checkpoints_were_written_and_verify(self, smoke_result) -> None:
        result, _ = smoke_result
        assert result.checkpoints, "a smoke run must produce at least one checkpoint"
        for path in result.checkpoints:
            manifest = verify_checkpoint(path)
            assert manifest.environment_version == result.environment_version
            assert manifest.feature_hash == result.feature_hash
            assert manifest.reward_revision == "objective-v1"
            assert manifest.step_count >= 0
            assert manifest.library_versions["torch"]

    def test_the_final_checkpoint_carries_actor_critic_replay_and_rng(self, smoke_result) -> None:
        result, _ = smoke_result
        final = result.checkpoints[-1]
        names = set(load_checkpoint_manifest(final).artifact_hashes)
        assert {"model.zip", "replay_buffer.pkl", "rng_state.pt"} <= names
        assert load_checkpoint_manifest(final).has_replay_buffer is True

    def test_a_tampered_checkpoint_fails_verification(self, smoke_result, tmp_path: Path) -> None:
        import shutil

        result, _ = smoke_result
        copy = tmp_path / "tampered"
        shutil.copytree(result.checkpoints[-1], copy)
        (copy / "rng_state.pt").write_bytes(b"not a tensor payload")
        with pytest.raises(CheckpointError, match="hashes to"):
            verify_checkpoint(copy)

    def test_checkpoints_are_discoverable(self, smoke_result) -> None:
        result, _ = smoke_result
        found = list_checkpoints(result.run_directory / "checkpoints")
        assert set(result.checkpoints) <= set(found)


class TestResume:
    def test_resume_reproduces_a_deterministic_evaluation(
        self, smoke_result, smoke_config: EnvConfig, smoke_algorithm: SacConfig
    ) -> None:
        """A resumed model and the original agree on a deterministic rollout.

        Bitwise equivalence across platforms is not promised and is not claimed
        here; what is checked is that the same weights, on this machine, from the
        same seed, give the same returns.
        """
        from stable_baselines3 import SAC

        from afterlap_core.learning.checkpoints import restore_into
        from afterlap_core.learning.train_sac import build_vec_env

        result, _ = smoke_result
        final = result.checkpoints[-1]

        vec = build_vec_env(smoke_config, n_envs=1, seed=11, scenario_id=SMOKE_SCENARIO)
        try:
            model = SAC(
                smoke_algorithm.policy,
                vec,
                policy_kwargs={"net_arch": list(smoke_algorithm.net_arch)},
                gamma=smoke_algorithm.gamma,
                seed=11,
                device="cpu",
                verbose=0,
                buffer_size=1000,
            )
            manifest = restore_into(
                final,
                model,
                expected_environment_version=result.environment_version,
                expected_feature_hash=result.feature_hash,
            )
            assert manifest.step_count == model.num_timesteps

            first = deterministic_evaluation(model, config=smoke_config, scenario_id=SMOKE_SCENARIO, seed=101)
            second = deterministic_evaluation(
                model, config=smoke_config, scenario_id=SMOKE_SCENARIO, seed=101
            )
            assert first == second

            reloaded = SAC(
                smoke_algorithm.policy,
                vec,
                policy_kwargs={"net_arch": list(smoke_algorithm.net_arch)},
                gamma=smoke_algorithm.gamma,
                seed=11,
                device="cpu",
                verbose=0,
                buffer_size=1000,
            )
            restore_into(
                final,
                reloaded,
                expected_environment_version=result.environment_version,
                expected_feature_hash=result.feature_hash,
            )
            third = deterministic_evaluation(
                reloaded, config=smoke_config, scenario_id=SMOKE_SCENARIO, seed=101
            )
            assert third == pytest.approx(first, abs=1e-9)
        finally:
            vec.close()

    def test_resuming_across_environment_revisions_is_refused(
        self, smoke_result, smoke_config: EnvConfig, smoke_algorithm: SacConfig
    ) -> None:
        from stable_baselines3 import SAC

        from afterlap_core.learning.checkpoints import restore_into
        from afterlap_core.learning.train_sac import build_vec_env

        result, _ = smoke_result
        vec = build_vec_env(smoke_config, n_envs=1, seed=11, scenario_id=SMOKE_SCENARIO)
        try:
            model = SAC(
                smoke_algorithm.policy,
                vec,
                policy_kwargs={"net_arch": list(smoke_algorithm.net_arch)},
                gamma=smoke_algorithm.gamma,
                seed=11,
                device="cpu",
                verbose=0,
                buffer_size=1000,
            )
            with pytest.raises(CheckpointError, match="not interchangeable"):
                restore_into(
                    result.checkpoints[-1],
                    model,
                    expected_environment_version="afterlap-learning-env/env-v9/planner=full",
                )
        finally:
            vec.close()


class TestThisIsNotATrainedProduct:
    def test_the_result_refuses_to_present_itself_as_trained(self, smoke_result) -> None:
        result, _ = smoke_result
        payload = result.as_dict()
        assert payload["is_smoke_run"] is True
        assert "NOT a trained model" in payload["warning"]
        assert "held-out evaluation" in payload["warning"]

    def test_no_benchmark_report_is_produced_by_a_smoke_run(self, smoke_result) -> None:
        result, _ = smoke_result
        # A smoke run creates no evidence, so promotion has nothing to read.
        assert not list((result.run_directory).glob("**/benchmark*.json"))
        assert np.isfinite(result.transitions_per_second)
