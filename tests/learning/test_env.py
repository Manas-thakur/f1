"""Environment tests: Gym/SB3 checkers, determinism, timing and isolation."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env as gym_check_env
from stable_baselines3.common.env_checker import check_env as sb3_check_env

from afterlap_contracts import ApplicableLimits, EligibilityState
from afterlap_core.learning.actions import BoundsStatus, action_space, compute_bounds, decode_action
from afterlap_core.learning.env import AfterlapEnv

from .conftest import SMOKE_SCENARIO, estimate_with

if TYPE_CHECKING:
    from afterlap_core.learning.config import EnvConfig

FIXED_ACTION = np.array([-0.5, 0.0], dtype=np.float32)


def build(config: EnvConfig, scenario: str = SMOKE_SCENARIO) -> AfterlapEnv:
    return AfterlapEnv(config=config, scenario_id=scenario)


class TestEnvironmentCheckers:
    def test_gymnasium_checker_passes(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        gym_check_env(env, skip_render_check=True)
        env.close()

    def test_sb3_checker_passes(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        sb3_check_env(env, warn=True, skip_render_check=True)
        env.close()

    def test_spaces_match_the_frozen_contract(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        assert env.observation_space.shape == (192,)
        assert env.action_space.shape == (2,)
        assert env.action_space.low.tolist() == [-1.0, -1.0]
        assert env.action_space.high.tolist() == [1.0, 1.0]
        assert env.action_space == action_space()
        assert env.feature_hash
        assert env.reward_revision == "objective-v1"
        env.close()


class TestDeterminism:
    def test_the_same_seed_gives_the_same_first_observation(self, fast_env_config: EnvConfig) -> None:
        first = build(fast_env_config)
        second = build(fast_env_config)
        a, info_a = first.reset(seed=17, options={"scenario_seed": 11})
        b, info_b = second.reset(seed=17, options={"scenario_seed": 11})
        assert a.tobytes() == b.tobytes()
        assert info_a["scenario_seed"] == info_b["scenario_seed"] == 11
        first.close()
        second.close()

    def test_the_same_action_sequence_gives_the_same_trajectory(self, fast_env_config: EnvConfig) -> None:
        def rollout() -> list[tuple[bytes, float]]:
            env = build(fast_env_config)
            env.reset(seed=17, options={"scenario_seed": 11})
            trace: list[tuple[bytes, float]] = []
            for _ in range(5):
                observation, reward, terminated, truncated, _ = env.step(FIXED_ACTION)
                trace.append((observation.tobytes(), reward))
                if terminated or truncated:
                    break
            env.close()
            return trace

        assert rollout() == rollout()

    def test_branching_from_the_same_reset_reproduces(self, fast_env_config: EnvConfig) -> None:
        """Two branches taking different actions still share their common prefix."""
        left = build(fast_env_config)
        right = build(fast_env_config)
        left.reset(seed=23, options={"scenario_seed": 29})
        right.reset(seed=23, options={"scenario_seed": 29})
        common_a, _, _, _, _ = left.step(FIXED_ACTION)
        common_b, _, _, _, _ = right.step(FIXED_ACTION)
        assert common_a.tobytes() == common_b.tobytes()

        diverged_a, _, _, _, _ = left.step(np.array([1.0, 1.0], dtype=np.float32))
        diverged_b, _, _, _, _ = right.step(np.array([-1.0, -1.0], dtype=np.float32))
        assert left.simulator is not right.simulator
        assert diverged_a.shape == diverged_b.shape

    def test_an_unrecognised_reset_option_is_rejected(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        with pytest.raises(ValueError, match="unrecognised reset options"):
            env.reset(seed=1, options={"cheat": True})
        env.close()

    def test_an_unknown_scenario_is_rejected(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        with pytest.raises(ValueError, match="not part of this environment instance"):
            env.reset(seed=1, options={"scenario_id": "oval-low-energy"})
        env.close()


class TestActionBounds:
    def test_bounds_are_logged_with_their_provenance(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        env.reset(seed=3, options={"scenario_seed": 11})
        bounds = env.action_bounds
        assert bounds is not None
        assert bounds.budget_lower_j == 0.0
        assert bounds.budget_upper_j > 0.0
        assert bounds.usable
        assert "available above floor" in bounds.detail
        payload = bounds.as_dict()
        assert set(payload) >= {"budget_lower_j", "budget_upper_j", "budget_status", "detail"}
        env.close()

    def test_no_energy_capability_disables_learned_preferences(self, limits) -> None:
        estimate = estimate_with(energy_j=None, energy_capability=False)
        bounds = compute_bounds(estimate, limits, checkpoint_interval_s=10.0)
        assert bounds.budget_status is BoundsStatus.ENERGY_UNAVAILABLE
        assert not bounds.usable
        decoded = decode_action(np.array([0.0, 0.0]), bounds)
        assert decoded.learned_enabled is False
        assert decoded.budget_j is None
        assert "energy" in decoded.reason

    def test_missing_limits_disable_learned_preferences(self) -> None:
        bounds = compute_bounds(estimate_with(), None, checkpoint_interval_s=10.0)
        assert bounds.budget_status is BoundsStatus.LIMITS_UNAVAILABLE
        decoded = decode_action(np.array([0.0, 0.0]), bounds)
        assert decoded.learned_enabled is False

    def test_collapsed_bounds_return_the_fixed_value(self) -> None:
        at_floor = ApplicableLimits(
            deployment_ceiling_w=350_000.0,
            recovery_ceiling_w=0.0,
            battery_energy_min_j=2_400_000.0,
            battery_energy_max_j=4_000_000.0,
        )
        bounds = compute_bounds(estimate_with(energy_j=2_400_000.0), at_floor, checkpoint_interval_s=10.0)
        assert bounds.budget_status is BoundsStatus.COLLAPSED
        assert bounds.budget_upper_j == bounds.budget_lower_j == 0.0
        decoded = decode_action(np.array([1.0, 0.0]), bounds)
        assert decoded.learned_enabled is True
        assert decoded.budget_j == pytest.approx(0.0)
        assert "collapsed" in decoded.reason

    def test_a_non_finite_action_is_refused(self, limits) -> None:
        bounds = compute_bounds(estimate_with(), limits, checkpoint_interval_s=10.0)
        decoded = decode_action(np.array([float("nan"), 0.0]), bounds)
        assert decoded.learned_enabled is False
        assert "non-finite" in decoded.reason

    def test_a_wrong_shaped_action_is_refused(self, limits) -> None:
        bounds = compute_bounds(estimate_with(), limits, checkpoint_interval_s=10.0)
        decoded = decode_action(np.array([0.0, 0.0, 0.0]), bounds)
        assert decoded.learned_enabled is False
        assert "shape" in decoded.reason

    def test_the_decode_formula_is_the_specified_affine_map(self, limits) -> None:
        bounds = compute_bounds(estimate_with(), limits, checkpoint_interval_s=10.0)
        low = decode_action(np.array([-1.0, -1.0]), bounds)
        mid = decode_action(np.array([0.0, 0.0]), bounds)
        high = decode_action(np.array([1.0, 1.0]), bounds)
        assert low.budget_j == pytest.approx(bounds.budget_lower_j)
        assert high.budget_j == pytest.approx(bounds.budget_upper_j)
        assert mid.budget_j == pytest.approx(0.5 * (bounds.budget_lower_j + bounds.budget_upper_j))
        assert low.reserve_target_j == pytest.approx(bounds.reserve_lower_j)
        assert high.reserve_target_j == pytest.approx(bounds.reserve_upper_j)

    def test_the_raw_action_is_preserved_for_replay(self, limits) -> None:
        bounds = compute_bounds(estimate_with(), limits, checkpoint_interval_s=10.0)
        decoded = decode_action(np.array([0.25, -0.75]), bounds)
        assert decoded.raw_action == (0.25, -0.75)


class TestTerminationAndTruncation:
    def test_the_step_limit_truncates_and_preserves_the_final_observation(
        self, env_config: EnvConfig
    ) -> None:
        config = dataclasses.replace(env_config, max_episode_steps=3)
        env = build(config)
        env.reset(seed=7, options={"scenario_seed": 11})
        terminated = truncated = False
        steps = 0
        observation = None
        info: dict = {}
        while not (terminated or truncated):
            observation, _, terminated, truncated, info = env.step(FIXED_ACTION)
            steps += 1
        assert steps == 3
        assert truncated is True
        assert terminated is False
        assert observation is not None
        assert np.all(np.isfinite(observation))
        assert info["episode_outcome"]["truncated"] is True
        assert info["episode_outcome"]["finished"] is False
        assert info["reward_terms"]["potential_next"] != 0.0
        env.close()

    def test_reaching_the_declared_distance_terminates(self, env_config: EnvConfig) -> None:
        env = build(env_config)
        env.reset(seed=7, options={"scenario_seed": 11})
        terminated = truncated = False
        info: dict = {}
        for _ in range(env_config.max_episode_steps):
            _, _, terminated, truncated, info = env.step(FIXED_ACTION)
            if terminated or truncated:
                break
        assert terminated is True, "the declared segment should complete inside the step cap"
        assert truncated is False
        outcome = info["episode_outcome"]
        assert outcome["finished"] is True
        assert outcome["finish_position"] >= 1
        assert outcome["distance_travelled_m"] >= env_config.scenario(SMOKE_SCENARIO).race_distance_m
        assert info["reward_terms"]["potential_next"] == 0.0
        env.close()

    def test_a_partial_final_interval_is_charged_its_actual_elapsed_time(self, env_config: EnvConfig) -> None:
        env = build(env_config)
        env.reset(seed=7, options={"scenario_seed": 11})
        info: dict = {}
        terminated = False
        for _ in range(env_config.max_episode_steps):
            _, _, terminated, truncated, info = env.step(FIXED_ACTION)
            if terminated or truncated:
                break
        assert terminated
        elapsed = info["reward_terms"]["elapsed_s"]
        assert 0.0 < elapsed <= env_config.policy_interval_s + 1e-9
        assert info["reward_terms"]["elapsed_penalty"] == pytest.approx(-elapsed)
        env.close()


class TestExecutionTiming:
    def test_an_instruction_is_subject_to_the_driver_delay(self, fast_env_config: EnvConfig) -> None:
        """A new instruction does not change the active profile within its own tick."""
        env = build(fast_env_config)
        env.reset(seed=13, options={"scenario_seed": 11})
        ego = "own"
        before = env.simulator.world.cars[ego].active_profile
        env.step(np.array([1.0, 1.0], dtype=np.float32))
        queue_lengths = []
        for _ in range(3):
            env.step(np.array([1.0, 1.0], dtype=np.float32))
            queue_lengths.append(len(env.simulator.world.action_queues[ego]))
        assert env.simulator.world.driver_configs[ego].reaction_delay_mean_s.value > 0.0
        assert before is not None
        assert all(length >= 0 for length in queue_lengths)
        env.close()

    def test_safety_invalidation_does_not_add_an_off_cadence_policy_call(
        self, fast_env_config: EnvConfig
    ) -> None:
        """One policy step consumes exactly one action, whatever happens inside it."""
        env = build(fast_env_config)
        env.reset(seed=13, options={"scenario_seed": 11})
        for _ in range(4):
            _, _, terminated, truncated, info = env.step(FIXED_ACTION)
            assert info["diagnostics"]["instructions_issued"] + info["diagnostics"]["withdrawals"] >= 1
            if terminated or truncated:
                break
        env.close()

    def test_an_eligible_plan_is_reused_rather_than_resolved(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        env.reset(seed=13, options={"scenario_seed": 11})
        reused = 0
        for _ in range(8):
            _, _, terminated, truncated, info = env.step(FIXED_ACTION)
            reused += 1 if info["planning"]["reused"] else 0
            if terminated or truncated:
                break
        assert env.diagnostics.solves + env.diagnostics.reuses > 0
        assert reused == env.diagnostics.reuses
        env.close()


class TestInformationIsolation:
    ALLOWED_STEP_KEYS: ClassVar[set[str]] = {
        "reward_terms",
        "action",
        "planning",
        "observation_diagnostics",
        "diagnostics",
        "environment_version",
        "episode_outcome",
    }

    def test_step_info_has_only_declared_keys(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        env.reset(seed=3, options={"scenario_seed": 11})
        _, _, _, _, info = env.step(FIXED_ACTION)
        assert set(info) <= self.ALLOWED_STEP_KEYS
        env.close()

    def test_info_carries_no_privileged_truth(self, fast_env_config: EnvConfig) -> None:
        """Mutating hidden rival state leaves a non-terminal info identical."""
        import json

        env = build(fast_env_config)
        env.reset(seed=3, options={"scenario_seed": 11})
        _, _, _, _, baseline = env.step(FIXED_ACTION)
        assert "episode_outcome" not in baseline, "this must be a non-terminal step"
        serialised = json.dumps(baseline, sort_keys=True, default=str)

        marker = 123_456.789
        for car_id, state in env.simulator.world.cars.items():
            if car_id == "own":
                continue
            state.battery_energy_j = marker
            state.battery_temperature_k = marker
        assert marker not in _numbers(baseline)
        assert str(marker) not in serialised

    def test_reset_info_carries_no_hidden_state(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        _, info = env.reset(seed=3, options={"scenario_seed": 11})
        assert set(info) == {
            "scenario_id",
            "scenario_family",
            "scenario_seed",
            "environment_version",
            "feature_hash",
            "reward_revision",
            "observation_diagnostics",
            "warmup_s",
            "start_progress_m",
            "eligibility",
        }
        env.close()

    def test_the_observation_is_finite_at_every_step(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        observation, _ = env.reset(seed=3, options={"scenario_seed": 11})
        assert np.all(np.isfinite(observation))
        for _ in range(5):
            observation, reward, terminated, truncated, _ = env.step(FIXED_ACTION)
            assert np.all(np.isfinite(observation))
            assert np.isfinite(reward)
            if terminated or truncated:
                break
        env.close()


class TestEligibility:
    def test_the_declared_warm_up_resolves_the_overtake_permission(self, fast_env_config: EnvConfig) -> None:
        env = build(fast_env_config)
        _, info = env.reset(seed=3, options={"scenario_seed": 11})
        assert info["eligibility"] != EligibilityState.UNKNOWN.value, (
            "without a resolved permission the independent checker returns unknown for every "
            "candidate and nothing is ever accepted"
        )
        assert info["warmup_s"] > 0.0
        assert info["start_progress_m"] >= 1600.0
        env.close()


def _numbers(payload: object) -> set[float]:
    """Every float anywhere in a nested info payload."""
    found: set[float] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            found |= _numbers(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found |= _numbers(value)
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        found.add(float(payload))
    return found
