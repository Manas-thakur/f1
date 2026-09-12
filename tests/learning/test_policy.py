"""Rebuilding the frozen actor from bundle weights.

A mapping of tensors is not a policy. The tests that matter here are the ones
that would catch a *plausible* wrong answer: an actor rebuilt with the wrong
squashing convention produces well-formed actions in range from correct
weights, and nothing downstream could tell. So the reconstruction is compared
action-for-action against the module the weights came from, and every shape or
revision mismatch is required to refuse rather than to reinitialise.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="the actor is a torch module")
pytest.importorskip("stable_baselines3", reason="the actor is rebuilt with the library's own class")

import numpy as np
from tests.learning.conftest import sb3_actor_state

from afterlap_core.feature_manifest import ACTION_SIZE, OBSERVATION_SIZE
from afterlap_core.learning.actions import ACTION_HIGH, ACTION_LOW, compute_bounds
from afterlap_core.learning.policy import ActorPolicy, PolicyLoadError, load_actor


@pytest.fixture(scope="module")
def source_and_state():
    return sb3_actor_state(hidden=(32, 32), seed=5)


@pytest.fixture(scope="module")
def rebuilt(source_and_state) -> ActorPolicy:
    _, state = source_and_state
    return load_actor(state, bundle_id="test/actor")


def _observation(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = rng.normal(size=OBSERVATION_SIZE // 2).astype(np.float32)
    mask = np.ones(OBSERVATION_SIZE // 2, dtype=np.float32)
    return np.concatenate([values, mask])


class TestReconstructionIsFaithful:
    def test_the_rebuilt_actor_reproduces_the_source_action_exactly(self, source_and_state, rebuilt) -> None:
        """The test that catches a wrong squashing or ordering convention."""
        source, _ = source_and_state
        for seed in range(5):
            observation = _observation(seed)
            with torch.inference_mode():
                expected = (
                    source(torch.from_numpy(observation).unsqueeze(0), deterministic=True).numpy().reshape(-1)
                )
            np.testing.assert_array_equal(rebuilt.act(observation), expected.astype(np.float64))

    def test_the_width_is_recovered_from_the_weights_not_from_a_config(self, rebuilt) -> None:
        assert rebuilt.net_arch == (32, 32)
        assert rebuilt.observation_size == OBSERVATION_SIZE
        assert rebuilt.action_size == ACTION_SIZE

    def test_inference_is_deterministic_and_repeatable(self, rebuilt) -> None:
        observation = _observation(11)
        first = rebuilt.act(observation)
        for _ in range(3):
            np.testing.assert_array_equal(rebuilt.act(observation), first)

    def test_the_action_stays_inside_the_declared_space(self, rebuilt) -> None:
        for seed in range(8):
            action = rebuilt.act(_observation(seed))
            assert action.shape == (ACTION_SIZE,)
            assert np.all(action >= ACTION_LOW)
            assert np.all(action <= ACTION_HIGH)

    def test_the_actor_is_frozen_and_carries_no_gradient(self, rebuilt) -> None:
        assert not any(parameter.requires_grad for parameter in rebuilt.module.parameters())
        assert rebuilt.module.training is False

    def test_calling_the_policy_is_the_same_as_acting(self, rebuilt) -> None:
        observation = _observation(3)
        np.testing.assert_array_equal(rebuilt(observation), rebuilt.act(observation))


class TestRefusals:
    def test_an_empty_state_dict_is_refused(self) -> None:
        with pytest.raises(PolicyLoadError, match="no actor weights"):
            load_actor({}, bundle_id="test/empty")

    def test_weights_that_are_not_an_sb3_actor_are_refused(self) -> None:
        state = {"synthetic.linear.weight": torch.zeros(4, 192), "synthetic.linear.bias": torch.zeros(4)}
        with pytest.raises(PolicyLoadError, match="not a Stable-Baselines3 SAC actor"):
            load_actor(state, bundle_id="test/foreign")

    def test_an_actor_without_a_mean_head_is_refused(self, source_and_state) -> None:
        _, state = source_and_state
        mutated = {key: value.clone() for key, value in state.items() if not key.startswith("mu.")}
        with pytest.raises(PolicyLoadError, match="no `mu` head"):
            load_actor(mutated, bundle_id="test/headless")

    def test_a_different_observation_size_is_refused_not_reinitialised(self, source_and_state) -> None:
        """A silently reinitialised network would look like a working one."""
        _, state = source_and_state
        mutated = {key: value.clone() for key, value in state.items()}
        mutated["latent_pi.0.weight"] = torch.zeros(32, 64)
        with pytest.raises(PolicyLoadError, match="feature revisions differ"):
            load_actor(mutated, bundle_id="test/wrong-observation")

    def test_a_different_action_size_is_refused(self, source_and_state) -> None:
        _, state = source_and_state
        mutated = {key: value.clone() for key, value in state.items()}
        mutated["mu.weight"] = torch.zeros(3, 32)
        mutated["mu.bias"] = torch.zeros(3)
        with pytest.raises(PolicyLoadError, match="action manifest declares"):
            load_actor(mutated, bundle_id="test/wrong-action")

    def test_a_layer_whose_shape_does_not_fit_is_refused(self, source_and_state) -> None:
        _, state = source_and_state
        mutated = {key: value.clone() for key, value in state.items()}
        mutated["latent_pi.2.weight"] = torch.zeros(32, 31)
        with pytest.raises(PolicyLoadError, match="do not fit the rebuilt network"):
            load_actor(mutated, bundle_id="test/bad-layer")

    def test_a_missing_key_is_refused_rather_than_defaulted(self, source_and_state) -> None:
        _, state = source_and_state
        mutated = {key: value.clone() for key, value in state.items() if key != "log_std.bias"}
        with pytest.raises(PolicyLoadError, match="do not fit the rebuilt network"):
            load_actor(mutated, bundle_id="test/missing-key")

    def test_a_wrong_shaped_observation_is_refused_at_inference(self, rebuilt) -> None:
        with pytest.raises(PolicyLoadError, match="expects a"):
            rebuilt.act(np.zeros(7, dtype=np.float32))

    def test_a_non_finite_observation_is_refused_not_sanitised(self, rebuilt) -> None:
        observation = _observation(1)
        observation[4] = np.nan
        with pytest.raises(PolicyLoadError, match="non-finite"):
            rebuilt.act(observation)


class TestPreferences:
    def test_unresolved_limits_disable_the_learned_preference(self, rebuilt, estimate) -> None:
        """Bounds are the gate, not the actor: no resolved limits, no preference."""
        bounds = compute_bounds(estimate, None, checkpoint_interval_s=20.0)
        decoded = rebuilt.preferences(_observation(2), bounds)
        assert decoded.learned_enabled is False
        assert decoded.budget_j is None
        assert decoded.reserve_target_j is None
        assert decoded.reason

    def test_resolved_limits_project_the_action_into_the_reachable_range(
        self, rebuilt, estimate, limits
    ) -> None:
        bounds = compute_bounds(estimate, limits, checkpoint_interval_s=20.0)
        observation = _observation(2)
        decoded = rebuilt.preferences(observation, bounds)
        assert decoded.learned_enabled is bounds.usable
        if bounds.usable:
            assert decoded.budget_j is not None
            assert bounds.budget_lower_j - 1e-6 <= decoded.budget_j <= bounds.budget_upper_j + 1e-6

    def test_the_raw_action_is_recorded_alongside_any_projection(self, rebuilt, estimate, limits) -> None:
        bounds = compute_bounds(estimate, limits, checkpoint_interval_s=20.0)
        observation = _observation(2)
        decoded = rebuilt.preferences(observation, bounds)
        np.testing.assert_allclose(np.asarray(decoded.raw_action, dtype=np.float64), rebuilt.act(observation))
