"""Continuation-ensemble tests: ordinary returns, support gating, disabled paths."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from afterlap_contracts import ReasonCode, RewardManifest, ScenarioOutcome, SupportThresholds
from afterlap_core.feature_manifest import ENERGY_V1, OBSERVATION_SIZE, feature_index
from afterlap_core.learning.config import EnvConfig, ValueConfig
from afterlap_core.learning.features import FeatureEncoder
from afterlap_core.learning.reward import step_reward
from afterlap_core.learning.value import (
    ContinuationEnsemble,
    ContinuationSample,
    PlannerContinuationAdapter,
    SupportReason,
    TargetScaler,
    ValueMember,
    discounted_returns,
    energy_regime_of,
    fit_ensemble,
    samples_from_episode,
)

from .conftest import SMOKE_SCENARIO, context, estimate_with, zero_policy


def synthetic_samples(episodes: int = 8, steps: int = 6, seed: int = 0) -> list[ContinuationSample]:
    """Complete synthetic episodes whose target is a smooth function of energy.

    Deliberately learnable, so a fit test checks the *machinery* rather than
    claiming a model quality result.
    """
    rng = np.random.default_rng(seed)
    out: list[ContinuationSample] = []
    for episode in range(episodes):
        observations = []
        rewards = []
        energy = 0.2 + 0.7 * rng.random()
        for step in range(steps):
            vector = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
            vector[feature_index("own_energy_mean")] = energy
            vector[feature_index("own_speed")] = 0.7
            vector[96:] = 1.0
            observations.append(vector)
            rewards.append(-1.0 - 0.5 * energy)
            energy = max(0.0, energy - 0.05)
            del step
        out.extend(
            samples_from_episode(
                observations,
                rewards,
                gamma=0.9966722160545233,
                episode_id=f"synthetic-{episode}",
                scenario_id="synthetic-track",
                family="synthetic",
                opponent_family="synthetic",
                remaining_distance_m=[float(1000 - 100 * i) for i in range(steps)],
                energy_regimes=["high"] * steps,
            )
        )
    return out


class TestOrdinaryReturns:
    def test_discounted_return_is_hand_computable(self) -> None:
        gamma = 0.9
        rewards = [-1.0, -2.0, -3.0]
        returns = discounted_returns(rewards, gamma)
        assert returns[2] == pytest.approx(-3.0)
        assert returns[1] == pytest.approx(-2.0 + 0.9 * -3.0)
        assert returns[0] == pytest.approx(-1.0 + 0.9 * (-2.0 + 0.9 * -3.0))

    def test_the_return_uses_the_environment_reward_with_no_entropy_term(
        self, reward: RewardManifest
    ) -> None:
        """Labels are built from environment rewards only; SAC entropy never enters."""
        remaining = [30.0, 20.0, 10.0, 0.0]
        rewards = []
        for index in range(len(remaining) - 1):
            last = index == len(remaining) - 2
            rewards.append(
                step_reward(
                    reward,
                    elapsed_s=1.0,
                    instruction_changes=0,
                    remaining_reference_time_s=remaining[index],
                    next_remaining_reference_time_s=remaining[index + 1],
                    terminated=last,
                    finished=last,
                    finish_position=1 if last else None,
                ).total
            )
        returns = discounted_returns(rewards, reward.gamma)
        expected = 0.0
        for value in reversed(rewards):
            expected = value + reward.gamma * expected
        assert returns[0] == pytest.approx(expected)
        # No entropy, no alpha, no log-pi anywhere in the construction.
        assert returns[-1] == pytest.approx(rewards[-1])

    def test_terminal_value_is_zero_at_a_true_finish(self, reward: RewardManifest) -> None:
        """After the last transition of a complete episode there is nothing left."""
        rewards = [-1.0, -1.0, -1.0]
        returns = discounted_returns(rewards, reward.gamma)
        # G[T] does not exist; the continuation *after* the final reward is zero
        # by construction, which is exactly what G[T-1] == r[T-1] states.
        assert returns[-1] == pytest.approx(rewards[-1])

    def test_explicit_plus_terminal_reward_does_not_double_count(self, reward: RewardManifest) -> None:
        """The terminal term appears once, inside the final transition's reward."""
        finish = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=1.0,
            next_remaining_reference_time_s=None,
            terminated=True,
            finished=True,
            finish_position=3,
        )
        rewards = [-1.0, -1.0, finish.total]
        returns = discounted_returns(rewards, reward.gamma)
        # The -60 finish cost is present exactly once in the return.
        without_terminal = discounted_returns(
            [-1.0, -1.0, finish.total - finish.terminal_finish], reward.gamma
        )
        assert returns[0] - without_terminal[0] == pytest.approx(reward.gamma**2 * finish.terminal_finish)

    def test_a_long_episode_is_down_weighted(self) -> None:
        short = samples_from_episode(
            [np.zeros(OBSERVATION_SIZE, dtype=np.float32)] * 2,
            [-1.0, -1.0],
            gamma=0.99,
            episode_id="short",
            scenario_id="s",
            family="f",
            opponent_family="o",
        )
        long = samples_from_episode(
            [np.zeros(OBSERVATION_SIZE, dtype=np.float32)] * 10,
            [-1.0] * 10,
            gamma=0.99,
            episode_id="long",
            scenario_id="s",
            family="f",
            opponent_family="o",
        )
        assert sum(s.weight for s in short) == pytest.approx(1.0)
        assert sum(s.weight for s in long) == pytest.approx(1.0)


class TestFitting:
    def test_an_incomplete_episode_is_refused(self, value_config: ValueConfig) -> None:
        samples = synthetic_samples(episodes=3)
        broken = [dataclasses.replace(samples[0], complete_episode=False), *samples[1:]]
        with pytest.raises(ValueError, match="complete episode"):
            fit_ensemble(broken, value_config, return_definition_hash="sha256:test")

    def test_the_split_is_by_episode_not_by_row(self, value_config: ValueConfig) -> None:
        config = dataclasses.replace(value_config, max_epochs=3, patience=1, members=2)
        _, report = fit_ensemble(
            synthetic_samples(episodes=6), config, return_definition_hash="sha256:test", seed=1
        )
        assert set(report.train_episodes).isdisjoint(report.tuning_episodes)
        assert report.train_episodes and report.tuning_episodes

    def test_bootstrap_is_over_complete_episodes(self, value_config: ValueConfig) -> None:
        config = dataclasses.replace(value_config, max_epochs=2, patience=1, members=3)
        _, report = fit_ensemble(
            synthetic_samples(episodes=6), config, return_definition_hash="sha256:test", seed=2
        )
        assert len(report.bootstrap_episode_ids) == 3
        for drawn in report.bootstrap_episode_ids:
            assert set(drawn) <= set(report.train_episodes)
            assert len(drawn) == len(report.train_episodes)

    def test_targets_are_standardised_on_training_only_and_inverted(self, value_config: ValueConfig) -> None:
        config = dataclasses.replace(value_config, max_epochs=8, patience=3, members=2)
        samples = synthetic_samples(episodes=8, seed=3)
        ensemble, report = fit_ensemble(samples, config, return_definition_hash="sha256:test", seed=3)
        assert report.target_scaler.fitted_on == "train"
        train_targets = [s.target for s in samples if s.episode_id in report.train_episodes]
        assert report.target_scaler.mean == pytest.approx(float(np.mean(train_targets)))

        # Predictions come back in the target's own units, not standardised ones.
        predicted, _ = ensemble.predict(np.stack([s.observation for s in samples[:4]]))
        assert np.all(predicted < 0.0), "returns here are negative; an uninverted scale would not be"

    def test_grouped_metrics_are_reported(self, value_config: ValueConfig) -> None:
        config = dataclasses.replace(value_config, max_epochs=4, patience=2, members=2)
        _, report = fit_ensemble(
            synthetic_samples(episodes=6), config, return_definition_hash="sha256:test", seed=4
        )
        groups = {g.group for g in report.groups}
        assert groups == {"remaining_distance", "energy_regime", "track", "opponent_family"}
        assert report.overall.count == report.tuning_samples
        assert np.isfinite(report.overall.mae)
        assert np.isfinite(report.overall.rmse)

    def test_the_report_names_its_controller_and_hashes(self, value_config: ValueConfig) -> None:
        config = dataclasses.replace(value_config, max_epochs=2, patience=1, members=2)
        ensemble, report = fit_ensemble(
            synthetic_samples(episodes=4), config, return_definition_hash="sha256:return-def", seed=5
        )
        assert report.continuation_controller == config.continuation_controller
        assert report.return_definition_hash == "sha256:return-def"
        assert report.feature_hash == ENERGY_V1.content_hash()
        assert ensemble.continuation_controller == config.continuation_controller


class TestInference:
    @pytest.fixture(scope="class")
    @staticmethod
    def ensemble() -> ContinuationEnsemble:
        return ContinuationEnsemble(
            [ValueMember() for _ in range(5)],
            TargetScaler(mean=-40.0, std=5.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e9,
                max_clip_fraction=1.0,
                min_known_mask_fraction=0.0,
            ),
        )

    def test_batch_and_single_inference_agree(self, ensemble: ContinuationEnsemble) -> None:
        rng = np.random.default_rng(0)
        batch = rng.normal(size=(7, OBSERVATION_SIZE)).astype(np.float32)
        batch_mean, batch_spread = ensemble.predict(batch)
        for index in range(batch.shape[0]):
            single_mean, single_spread = ensemble.predict(batch[index])
            assert single_mean[0] == pytest.approx(batch_mean[index], abs=1e-6)
            assert single_spread[0] == pytest.approx(batch_spread[index], abs=1e-6)

    def test_prediction_is_independent_of_hidden_truth(
        self, ensemble: ContinuationEnsemble, encoder: FeatureEncoder
    ) -> None:
        encoded = encoder.encode(estimate_with(), context())
        first = ensemble.score(encoded)
        second = ensemble.score(encoder.encode(estimate_with(), context()))
        assert first.value == pytest.approx(second.value)
        assert first.disagreement == pytest.approx(second.disagreement)

    def test_a_wrong_feature_hash_disables_with_a_reason_code(
        self, ensemble: ContinuationEnsemble, encoder: FeatureEncoder
    ) -> None:
        encoded = encoder.encode(estimate_with(), context())
        wrong = dataclasses.replace(encoded, feature_hash="sha256:not-the-frozen-schema")
        score = ensemble.score(wrong)
        assert score.in_support is False
        assert score.reason is SupportReason.FEATURE_HASH_MISMATCH

    def test_excess_clipping_disables_with_a_reason_code(self, encoder: FeatureEncoder) -> None:
        strict = ContinuationEnsemble(
            [ValueMember() for _ in range(2)],
            TargetScaler(mean=0.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e9, max_clip_fraction=0.0, min_known_mask_fraction=0.0
            ),
        )
        clipped = encoder.encode(estimate_with(speed_mps=900.0), context())
        assert clipped.clip_count > 0
        score = strict.score(clipped)
        assert score.in_support is False
        assert score.reason is SupportReason.CLIP_FRACTION_EXCEEDED

    def test_a_thin_known_mask_disables_with_a_reason_code(self, encoder: FeatureEncoder) -> None:
        strict = ContinuationEnsemble(
            [ValueMember() for _ in range(2)],
            TargetScaler(mean=0.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e9, max_clip_fraction=1.0, min_known_mask_fraction=0.99
            ),
        )
        from afterlap_core.learning.features import FeatureContext

        sparse = encoder.encode(estimate_with(), FeatureContext(track_length_m=5200.0))
        score = strict.score(sparse)
        assert score.in_support is False
        assert score.reason is SupportReason.KNOWN_MASK_TOO_LOW

    def test_excess_disagreement_disables_with_a_reason_code(self, encoder: FeatureEncoder) -> None:
        strict = ContinuationEnsemble(
            [ValueMember() for _ in range(5)],
            TargetScaler(mean=0.0, std=1e6, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e-9,
                max_clip_fraction=1.0,
                min_known_mask_fraction=0.0,
            ),
        )
        score = strict.score(encoder.encode(estimate_with(), context()))
        assert score.in_support is False
        assert score.reason is SupportReason.DISAGREEMENT_EXCEEDED

    def test_energy_regime_labels_the_masked_case_unknown(self, encoder: FeatureEncoder) -> None:
        known = encoder.encode(estimate_with(energy_j=3_600_000.0), context())
        unknown = encoder.encode(estimate_with(energy_j=None, energy_capability=False), context())
        assert energy_regime_of(known) == "high"
        assert energy_regime_of(unknown) == "unknown"


class TestPersistence:
    def test_round_trip_preserves_predictions(self, tmp_path: Path) -> None:
        ensemble = ContinuationEnsemble(
            [ValueMember() for _ in range(3)],
            TargetScaler(mean=-12.5, std=3.25, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="named-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=5.0, max_clip_fraction=0.1, min_known_mask_fraction=0.6
            ),
        )
        ensemble.save(tmp_path)
        restored = ContinuationEnsemble.load(tmp_path)

        rng = np.random.default_rng(1)
        batch = rng.normal(size=(4, OBSERVATION_SIZE)).astype(np.float32)
        before, _ = ensemble.predict(batch)
        after, _ = restored.predict(batch)
        np.testing.assert_allclose(before, after, rtol=0, atol=0)
        assert restored.continuation_controller == "named-controller"
        assert restored.target_scaler.mean == pytest.approx(-12.5)
        assert restored.support.min_known_mask_fraction == pytest.approx(0.6)


class TestPlannerIntegration:
    """Learned-disabled scoring must equal the baseline exactly."""

    @staticmethod
    def _outcomes() -> tuple[ScenarioOutcome, ...]:
        return (
            ScenarioOutcome(
                scenario_id="s1",
                weight=0.5,
                utility=-12.0,
                terminal_value=-3.0,
                final_energy_j=1_500_000.0,
            ),
            ScenarioOutcome(
                scenario_id="s2",
                weight=0.5,
                utility=-14.0,
                terminal_value=-4.0,
                final_energy_j=900_000.0,
            ),
        )

    def test_an_out_of_support_model_is_bit_for_bit_the_baseline(self, encoder: FeatureEncoder) -> None:
        from afterlap_core.planning import apply_learned_reranking
        from afterlap_core.planning.objective import load_objective

        objective = load_objective()
        outcomes = self._outcomes()
        terms = _objective_terms(objective)
        frame, weights = _frame_and_weights()

        baseline_terms, baseline_outcomes, baseline_learned = apply_learned_reranking(
            terms, outcomes, frame, weights, objective, None, disagreement_weight=0.5
        )

        ensemble = ContinuationEnsemble(
            [ValueMember() for _ in range(2)],
            TargetScaler(mean=0.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e-9,  # always out of support
                max_clip_fraction=1.0,
                min_known_mask_fraction=0.0,
            ),
        )
        adapter = PlannerContinuationAdapter(ensemble)
        adapter.set_reference(encoder.encode(estimate_with(), context()))

        disabled_terms, disabled_outcomes, disabled_learned = apply_learned_reranking(
            terms, outcomes, frame, weights, objective, adapter, disagreement_weight=0.5
        )

        # The same float, not an approximation.
        assert disabled_terms.final_score == baseline_terms.final_score
        assert disabled_terms == baseline_terms == terms
        assert disabled_outcomes == baseline_outcomes == tuple(outcomes)
        assert disabled_learned.enabled is False
        assert baseline_learned.enabled is False
        assert ReasonCode.BASELINE_FALLBACK in disabled_learned.reason_codes

    def test_an_in_support_model_changes_the_score_and_names_itself(self, encoder: FeatureEncoder) -> None:
        from afterlap_core.planning import apply_learned_reranking
        from afterlap_core.planning.objective import load_objective

        objective = load_objective()
        outcomes = self._outcomes()
        terms = _objective_terms(objective)
        frame, weights = _frame_and_weights()

        ensemble = ContinuationEnsemble(
            [ValueMember() for _ in range(3)],
            TargetScaler(mean=-5.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e9, max_clip_fraction=1.0, min_known_mask_fraction=0.0
            ),
        )
        adapter = PlannerContinuationAdapter(ensemble)
        adapter.set_reference(encoder.encode(estimate_with(), context()))

        updated, rewritten, learned = apply_learned_reranking(
            terms, outcomes, frame, weights, objective, adapter, disagreement_weight=0.5
        )
        assert learned.enabled is True
        assert learned.bundle_id == ensemble.bundle_id
        assert updated.final_score != terms.final_score
        # The analytic terminal term was removed before the learned one entered,
        # so nothing is counted twice.
        for original, new in zip(outcomes, rewritten, strict=True):
            assert new.terminal_value != original.terminal_value
            assert new.terminal_value_source == ensemble.bundle_id
            assert new.utility == pytest.approx(
                original.utility + (original.terminal_value or 0.0) - (new.terminal_value or 0.0)
            )

    def test_the_adapter_refuses_without_a_reference_encoding(self) -> None:
        ensemble = ContinuationEnsemble(
            [ValueMember()],
            TargetScaler(mean=0.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test-controller",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=1e9, max_clip_fraction=1.0, min_known_mask_fraction=0.0
            ),
        )
        adapter = PlannerContinuationAdapter(ensemble)
        assert adapter.in_support({"own_energy_j": 1_000_000.0}) is False
        assert adapter.last_reason is SupportReason.KNOWN_MASK_TOO_LOW


class TestCollectedGroupingKeys:
    """Every required reporting group must be populated, not silently "unknown".

    ``VALUE_AND_CALIBRATION.md`` asks for MAE/RMSE and bias *by remaining
    distance, energy regime, track and opponent family*. A collector that reads
    the scenario identity from the step info rather than the reset info gets
    ``unknown`` for three of those four and the requirement quietly evaporates,
    so it is asserted here rather than trusted.
    """

    def test_a_collected_episode_carries_all_four_grouping_keys(self, env_config: EnvConfig) -> None:
        from afterlap_core.learning.env import AfterlapEnv
        from afterlap_core.learning.value import collect_episodes

        # The shipped step cap, not a shortened one: a truncated episode yields
        # no complete-return samples, and the sample assertions below would then
        # never run.
        env = AfterlapEnv(config=env_config, scenario_id=SMOKE_SCENARIO)
        samples, records = collect_episodes(
            env, policy=zero_policy, episodes=1, gamma=0.9966722160545233, seed=4242
        )
        env.close()

        assert records, "one episode should have been recorded"
        record = records[0]
        assert record["scenario_id"] == SMOKE_SCENARIO
        assert record["family"] != "unknown"
        assert record["opponent_family"] not in ("unknown", "none")

        assert samples, "a complete episode must produce ordinary-return samples"
        for sample in samples:
            assert sample.scenario_id == SMOKE_SCENARIO
            assert sample.family != "unknown"
            assert sample.opponent_family not in ("unknown", "none")
            assert sample.remaining_distance_m is not None
            assert sample.remaining_distance_m >= 0.0
            assert sample.energy_regime != "unknown"

    def test_remaining_distance_is_read_back_in_metres(self, encoder: FeatureEncoder) -> None:
        from afterlap_core.learning.value import remaining_distance_of

        encoded = encoder.encode(estimate_with(remaining_distance_m=1_500.0), context())
        assert remaining_distance_of(encoded) == pytest.approx(1_500.0, rel=1e-6)

        masked = encoder.encode(estimate_with(remaining_distance_m=None), context())
        assert remaining_distance_of(masked) is None


def _objective_terms(objective):
    from afterlap_contracts import ObjectiveTerms

    return ObjectiveTerms(
        objective_version=objective.objective_id,
        expected_utility=-13.0,
        tail_alpha=objective.tail_alpha,
        cvar_loss=-11.0,
        lambda_tail=objective.lambda_tail,
        switch_count=1,
        lambda_switch=objective.lambda_switch,
        disagreement_penalty=0.0,
        generation_score=-15.5,
        final_score=-15.5,
    )


def _frame_and_weights():
    """A hand-built plan frame and loss weights, so the reranking has a corridor."""
    from afterlap_contracts import DeploymentProfile
    from afterlap_core.planning.segments import FrameSegment, PlanFrame
    from afterlap_core.planning.surrogate import SurrogateWeights

    segment = FrameSegment(
        index=0,
        start_progress_m=0.0,
        end_progress_m=700.0,
        profile=DeploymentProfile.NEUTRAL,
        speed_mps=70.0,
        duration_s=10.0,
        execution_window_s=3.0,
        lap_index=0,
        regulatory_ceiling_w=350_000.0,
        derated_ceiling_w=350_000.0,
        max_deploy_j=3_500_000.0,
        max_harvest_j=3_500_000.0,
        beta=1.0,
    )
    frame = PlanFrame(
        segments=(segment,),
        start_progress_m=0.0,
        end_progress_m=700.0,
        lead_time_s=1.0,
        horizon_s=10.0,
        speed_mps=70.0,
        initial_energy_j=2_400_000.0,
        energy_floor_j=0.0,
        energy_ceiling_j=4_000_000.0,
        terminal_target_energy_j=None,
        charge_efficiency=0.9,
        recharge_allowance_per_lap_j=8_000_000.0,
        recharge_used_this_lap_j=0.0,
        max_power_ramp_w_per_s=700_000.0,
        current_power_w=0.0,
        min_speed_mps=20.0,
        drivetrain_efficiency=0.95,
        harvest_opportunity_coefficient=0.5,
        continuation_availability=1.0,
        checkpoint_progress_m=(),
    )
    weights = SurrogateWeights(
        elapsed_second_penalty=1.0,
        position_penalty=30.0,
        energy_value_rate=1.0e-6,
        gap_logistic_scale_s=0.5,
        counterattack_rate_s_per_j=1.0e-7,
        counterattack_energy_scale_j=1.0e6,
        initial_advantage_s=0.5,
        discount=0.9,
        marginal_time_per_joule_s=1.0e-7,
    )
    return frame, weights
