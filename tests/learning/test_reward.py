"""Reward revision ``objective-v1``: hand-computed returns and telescoping."""

from __future__ import annotations

import math

import pytest

from afterlap_contracts import RewardManifest
from afterlap_core.learning.reward import (
    assert_field_size_supported,
    load_reward_manifest,
    objective_content_hash,
    potential,
    step_reward,
)


class TestManifestIsFrozen:
    def test_values_come_from_the_frozen_objective(self, reward: RewardManifest) -> None:
        assert reward.revision == "objective-v1"
        assert reward.elapsed_second_penalty == pytest.approx(1.0)
        assert reward.instruction_change_penalty == pytest.approx(0.1)
        assert reward.finish_position_penalty == pytest.approx(30.0)
        assert reward.terminal_failure_penalty == pytest.approx(1200.0)
        assert reward.potential_reference_time_scale_s == pytest.approx(100.0)
        assert reward.gamma == pytest.approx(math.exp(-1.0 / 300.0))

    def test_objective_hash_is_stable(self) -> None:
        assert objective_content_hash() == objective_content_hash()
        assert objective_content_hash().startswith("sha256:")

    def test_the_failure_bound_is_re_derived_and_enforced(self, reward: RewardManifest) -> None:
        running = (
            reward.elapsed_second_penalty
            + reward.instruction_change_penalty * reward.maximum_charged_instruction_changes_per_s
        ) / (1.0 - reward.gamma)
        position = reward.finish_position_penalty * (reward.maximum_supported_field_size - 1)
        assert reward.terminal_failure_penalty > running + position
        assert running == pytest.approx(331.0, abs=1.0)
        assert position == pytest.approx(570.0)

        with pytest.raises(ValueError, match="terminal_failure_penalty"):
            RewardManifest(
                revision="broken",
                elapsed_second_penalty=1.0,
                instruction_change_penalty=0.1,
                finish_position_penalty=30.0,
                terminal_failure_penalty=100.0,
                potential_reference_time_scale_s=100.0,
                gamma=reward.gamma,
                maximum_supported_field_size=20,
                maximum_charged_instruction_changes_per_s=1.0,
            )

    def test_an_oversized_field_is_rejected(self, reward: RewardManifest) -> None:
        assert_field_size_supported(reward, 20)
        with pytest.raises(ValueError, match="recompute the bound"):
            assert_field_size_supported(reward, 21)


class TestHandComputedReturns:
    def test_a_plain_second_costs_exactly_one_unit(self, reward: RewardManifest) -> None:
        terms = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=100.0,
            next_remaining_reference_time_s=100.0,
            terminated=False,
        )
        assert terms.elapsed_penalty == pytest.approx(-1.0)
        assert terms.instruction_penalty == 0.0
        assert terms.shaping == pytest.approx(1.0 - reward.gamma)
        assert terms.total == pytest.approx(-1.0 + (1.0 - reward.gamma))

    def test_an_instruction_change_costs_the_declared_penalty(self, reward: RewardManifest) -> None:
        terms = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=1,
            remaining_reference_time_s=50.0,
            next_remaining_reference_time_s=50.0,
            terminated=False,
        )
        assert terms.instruction_penalty == pytest.approx(-0.1)

    def test_a_partial_final_interval_is_charged_its_actual_elapsed_time(
        self, reward: RewardManifest
    ) -> None:
        terms = step_reward(
            reward,
            elapsed_s=0.35,
            instruction_changes=0,
            remaining_reference_time_s=0.35,
            next_remaining_reference_time_s=None,
            terminated=True,
            finished=True,
            finish_position=1,
        )
        assert terms.elapsed_penalty == pytest.approx(-0.35)
        assert terms.terminal_finish == 0.0

    def test_finish_position_cost_is_hand_computable(self, reward: RewardManifest) -> None:
        for position, expected in ((1, 0.0), (2, -30.0), (4, -90.0)):
            terms = step_reward(
                reward,
                elapsed_s=1.0,
                instruction_changes=0,
                remaining_reference_time_s=1.0,
                next_remaining_reference_time_s=None,
                terminated=True,
                finished=True,
                finish_position=position,
            )
            assert terms.terminal_finish == pytest.approx(expected)

    def test_truncation_retains_continuation_value(self, reward: RewardManifest) -> None:
        truncated = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=200.0,
            next_remaining_reference_time_s=199.0,
            terminated=False,
            truncated=True,
        )
        assert truncated.potential_next == pytest.approx(-1.99)
        assert truncated.terminal_finish == 0.0
        assert truncated.terminal_failure == 0.0

    def test_a_true_terminal_zeroes_the_next_potential(self, reward: RewardManifest) -> None:
        terminal = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=200.0,
            next_remaining_reference_time_s=199.0,
            terminated=True,
            finished=True,
            finish_position=1,
        )
        assert terminal.potential_next == 0.0

    def test_potential_is_zero_at_a_true_terminal_state(self, reward: RewardManifest) -> None:
        assert potential(150.0, reward, terminal=True) == 0.0
        assert potential(150.0, reward, terminal=False) == pytest.approx(-1.5)
        assert potential(None, reward, terminal=False) == 0.0

    def test_inconsistent_terminal_flags_are_rejected(self, reward: RewardManifest) -> None:
        with pytest.raises(ValueError, match="both terminated and truncated"):
            step_reward(
                reward,
                elapsed_s=1.0,
                instruction_changes=0,
                remaining_reference_time_s=1.0,
                next_remaining_reference_time_s=None,
                terminated=True,
                truncated=True,
            )
        with pytest.raises(ValueError, match="must set terminated"):
            step_reward(
                reward,
                elapsed_s=1.0,
                instruction_changes=0,
                remaining_reference_time_s=1.0,
                next_remaining_reference_time_s=None,
                terminated=False,
                finished=True,
                finish_position=1,
            )
        with pytest.raises(ValueError, match="record the position"):
            step_reward(
                reward,
                elapsed_s=1.0,
                instruction_changes=0,
                remaining_reference_time_s=1.0,
                next_remaining_reference_time_s=None,
                terminated=True,
                finished=True,
            )


class TestTelescoping:
    """The shaping is potential-based, checked numerically rather than argued."""

    @staticmethod
    def _episode(reward: RewardManifest, remaining: list[float]) -> list:
        """One episode with the given reference-time trace, ending in a finish."""
        terms = []
        for index in range(len(remaining) - 1):
            last = index == len(remaining) - 2
            terms.append(
                step_reward(
                    reward,
                    elapsed_s=1.0,
                    instruction_changes=0,
                    remaining_reference_time_s=remaining[index],
                    next_remaining_reference_time_s=remaining[index + 1],
                    terminated=last,
                    finished=last,
                    finish_position=1 if last else None,
                )
            )
        return terms

    def test_shaping_telescopes_to_minus_the_initial_potential(self, reward: RewardManifest) -> None:
        remaining = [30.0, 27.0, 21.0, 14.0, 6.0, 0.0]
        terms = self._episode(reward, remaining)
        gamma = reward.gamma

        shaped = sum(gamma**k * t.total for k, t in enumerate(terms))
        unshaped = sum(gamma**k * (t.base_reward + t.terminal_term) for k, t in enumerate(terms))
        phi_0 = potential(remaining[0], reward, terminal=False)

        assert shaped - unshaped == pytest.approx(-phi_0, abs=1e-12)

    def test_the_shaping_sum_alone_equals_minus_phi_zero(self, reward: RewardManifest) -> None:
        remaining = [42.0, 35.0, 20.0, 11.0, 0.0]
        terms = self._episode(reward, remaining)
        gamma = reward.gamma
        shaping_sum = sum(gamma**k * t.shaping for k, t in enumerate(terms))
        assert shaping_sum == pytest.approx(-potential(remaining[0], reward, terminal=False), abs=1e-12)

    def test_shaping_does_not_change_the_ordering_of_two_episodes(self, reward: RewardManifest) -> None:
        """Two episodes from the same start: shaping shifts both by the same constant."""
        fast = self._episode(reward, [30.0, 20.0, 10.0, 0.0])
        slow = self._episode(reward, [30.0, 25.0, 18.0, 9.0, 0.0])
        gamma = reward.gamma

        def shaped(terms: list) -> float:
            return sum(gamma**k * t.total for k, t in enumerate(terms))

        def unshaped(terms: list) -> float:
            return sum(gamma**k * (t.base_reward + t.terminal_term) for k, t in enumerate(terms))

        assert (shaped(fast) - shaped(slow)) == pytest.approx(unshaped(fast) - unshaped(slow), abs=1e-12)

    def test_a_missing_reference_time_disables_shaping_and_says_so(self, reward: RewardManifest) -> None:
        terms = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=None,
            next_remaining_reference_time_s=None,
            terminated=False,
        )
        assert terms.shaping == 0.0
        assert terms.shaping_available is False


class TestNoRewardHacks:
    def test_passing_and_being_repassed_earns_nothing(self, reward: RewardManifest) -> None:
        """No term depends on a pass, so a pass cycle cannot be farmed."""
        quiet = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=100.0,
            next_remaining_reference_time_s=99.0,
            terminated=False,
        )
        again = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=100.0,
            next_remaining_reference_time_s=99.0,
            terminated=False,
        )
        assert quiet.total == pytest.approx(again.total)
        assert quiet.total < 0.0

    def test_a_repeated_pass_cycle_accumulates_only_time_cost(self, reward: RewardManifest) -> None:
        """Ten seconds of swapping places costs ten seconds and gains nothing."""
        total = 0.0
        for index in range(10):
            total += step_reward(
                reward,
                elapsed_s=1.0,
                instruction_changes=0,
                remaining_reference_time_s=100.0 - index,
                next_remaining_reference_time_s=99.0 - index,
                terminated=False,
            ).total
        assert total < 0.0
        shaping = (sum(100 - i for i in range(10)) - reward.gamma * sum(99 - i for i in range(10))) / 100.0
        assert total == pytest.approx(-10.0 + shaping, abs=1e-12)

    def test_unused_finish_energy_earns_nothing(self, reward: RewardManifest) -> None:
        """The reward has no energy argument, so a hoarded battery pays nothing."""
        finish = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=1.0,
            next_remaining_reference_time_s=None,
            terminated=True,
            finished=True,
            finish_position=1,
        )
        assert finish.terminal_finish == 0.0
        assert finish.total == pytest.approx(-1.0 + 0.01)
        assert "energy" not in finish.as_dict()

    def test_a_deliberate_dnf_is_worse_than_safe_continuation(self, reward: RewardManifest) -> None:
        """Retiring must never beat running the worst legal race to the end."""
        gamma = reward.gamma
        failure = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=300.0,
            next_remaining_reference_time_s=None,
            terminated=True,
            failed=True,
        )

        worst_running = -(
            reward.elapsed_second_penalty
            + reward.instruction_change_penalty * reward.maximum_charged_instruction_changes_per_s
        ) / (1.0 - gamma)
        worst_position = -reward.finish_position_penalty * (reward.maximum_supported_field_size - 1)
        worst_safe_continuation = worst_running + worst_position

        assert failure.total < worst_safe_continuation
        assert failure.terminal_failure == pytest.approx(-1200.0)

    def test_failing_is_worse_than_finishing_last(self, reward: RewardManifest) -> None:
        last = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=10.0,
            next_remaining_reference_time_s=None,
            terminated=True,
            finished=True,
            finish_position=reward.maximum_supported_field_size,
        )
        failure = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=0,
            remaining_reference_time_s=10.0,
            next_remaining_reference_time_s=None,
            terminated=True,
            failed=True,
        )
        assert failure.total < last.total


class TestDecomposition:
    def test_total_is_the_sum_of_its_reported_parts(self, reward: RewardManifest) -> None:
        terms = step_reward(
            reward,
            elapsed_s=1.0,
            instruction_changes=2,
            remaining_reference_time_s=80.0,
            next_remaining_reference_time_s=79.0,
            terminated=False,
        )
        payload = terms.as_dict()
        rebuilt = (
            payload["elapsed_penalty"]
            + payload["instruction_penalty"]
            + payload["terminal_finish"]
            + payload["terminal_failure"]
            + payload["shaping"]
        )
        assert rebuilt == pytest.approx(payload["total"])

    def test_the_default_manifest_matches_the_configured_one(self) -> None:
        assert load_reward_manifest() == load_reward_manifest("objective-v1")
