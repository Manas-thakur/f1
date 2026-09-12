"""Dataset collection, and the two ways it must not quietly lie.

Both collectors run the real simulator, so this file is deliberately small and
the episodes are short. The two tests that carry weight are about labelling:

* a forecast whose checkpoint the episode never reached must be *dropped*, not
  labelled false. Labelling it false would drag every forecast down and read as
  systematic overconfidence in the calibration report;
* the realisation must resolve ``pass_before`` and ``ahead_at`` by the same
  definitions ``planning.rollout`` uses to forecast them. A forecast and a label
  that mean different things produce a confident, wrong calibration.
"""

from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("torch", reason="the environment imports the learning stack")
pytest.importorskip("gymnasium", reason="the environment is a Gymnasium env")

import numpy as np

from afterlap_core.learning.config import load_env_config
from afterlap_core.learning.dataset import (
    collect_calibration_samples,
    collect_continuation_samples,
    rollout_enabled_config,
)
from afterlap_core.learning.env import COMPLETED_PASS, EventRealisation


class _Report:
    """A minimal stand-in for the fields ``EventRealisation`` reads."""

    def __init__(self, checkpoints=(), passes=()) -> None:
        self.checkpoints = checkpoints
        self.passes = passes


@dataclasses.dataclass(frozen=True, slots=True)
class _Crossing:
    checkpoint_id: str
    car_id: str
    session_time_s: float


@dataclasses.dataclass(frozen=True, slots=True)
class _Pass:
    session_time_s: float
    overtaking_car_id: str
    overtaken_car_id: str
    kind: str


class TestEventRealisation:
    def test_an_unreached_checkpoint_resolves_to_none_not_false(self) -> None:
        """The distinction that keeps the calibration set unbiased."""
        realisation = EventRealisation()
        assert realisation.pass_before("attack-exit") is None
        assert realisation.ahead_at("attack-exit") is None
        assert realisation.resolve("pass_before(checkpoint=attack-exit)", "attack-exit") is None

    def test_a_pass_at_or_before_the_line_resolves_true(self) -> None:
        realisation = EventRealisation()
        realisation.observe(
            _Report(
                checkpoints=(_Crossing("attack-exit", "own", 12.0),),
                passes=(_Pass(9.0, "own", "rival", COMPLETED_PASS),),
            ),
            ego_car_id="own",
        )
        assert realisation.pass_before("attack-exit") is True

    def test_a_pass_after_the_line_resolves_false(self) -> None:
        realisation = EventRealisation()
        realisation.observe(
            _Report(
                checkpoints=(_Crossing("attack-exit", "own", 8.0),),
                passes=(_Pass(11.0, "own", "rival", COMPLETED_PASS),),
            ),
            ego_car_id="own",
        )
        assert realisation.pass_before("attack-exit") is False

    def test_a_pass_of_another_kind_is_not_a_pass(self) -> None:
        """``rollout`` counts only ``completed_pass``; the label must match."""
        realisation = EventRealisation()
        realisation.observe(
            _Report(
                checkpoints=(_Crossing("attack-exit", "own", 12.0),),
                passes=(_Pass(9.0, "own", "rival", "contact_blocked"),),
            ),
            ego_car_id="own",
        )
        assert realisation.pass_before("attack-exit") is False

    def test_a_pass_by_the_rival_is_not_our_pass(self) -> None:
        realisation = EventRealisation()
        realisation.observe(
            _Report(
                checkpoints=(_Crossing("attack-exit", "own", 12.0),),
                passes=(_Pass(9.0, "rival", "own", COMPLETED_PASS),),
            ),
            ego_car_id="own",
        )
        assert realisation.pass_before("attack-exit") is False

    def test_ahead_at_compares_crossing_times_at_the_same_line(self) -> None:
        realisation = EventRealisation()
        realisation.observe(
            _Report(
                checkpoints=(
                    _Crossing("attack-exit", "own", 10.0),
                    _Crossing("attack-exit", "rival", 11.0),
                )
            ),
            ego_car_id="own",
        )
        assert realisation.ahead_at("attack-exit") is True

    def test_a_rival_that_never_reached_the_line_leaves_us_ahead(self) -> None:
        realisation = EventRealisation()
        realisation.observe(_Report(checkpoints=(_Crossing("attack-exit", "own", 10.0),)), ego_car_id="own")
        assert realisation.ahead_at("attack-exit") is True

    def test_only_the_first_crossing_of_a_line_counts(self) -> None:
        realisation = EventRealisation()
        realisation.observe(_Report(checkpoints=(_Crossing("attack-exit", "own", 10.0),)), ego_car_id="own")
        realisation.observe(_Report(checkpoints=(_Crossing("attack-exit", "own", 40.0),)), ego_car_id="own")
        assert realisation.as_dict()["ego_crossings_s"]["attack-exit"] == 10.0

    def test_an_unknown_event_definition_resolves_to_none(self) -> None:
        realisation = EventRealisation()
        realisation.observe(_Report(checkpoints=(_Crossing("attack-exit", "own", 10.0),)), ego_car_id="own")
        assert realisation.resolve("finish_ahead(checkpoint=attack-exit)", "attack-exit") is None

    def test_a_none_report_is_ignored(self) -> None:
        realisation = EventRealisation()
        realisation.observe(None, ego_car_id="own")
        assert realisation.as_dict()["completed_pass_moments_s"] == []


class TestRolloutEnabledConfig:
    def test_the_environment_revision_records_the_change(self) -> None:
        base = load_env_config()
        flipped = rollout_enabled_config(base)
        assert base.planner_mode == "no_rollout"
        assert flipped.planner_mode == "full"
        assert flipped.environment_version.endswith("planner=full")
        assert flipped.environment_version != base.environment_version

    def test_it_is_idempotent(self) -> None:
        once = rollout_enabled_config(load_env_config())
        assert rollout_enabled_config(once) is once

    def test_a_raised_deadline_is_applied(self) -> None:
        raised = rollout_enabled_config(load_env_config(), planner_deadline_s=5.0)
        assert raised.planner_deadline_s == pytest.approx(5.0)


class TestCollectorRefusals:
    def test_calibration_without_rollouts_is_refused_not_returned_empty(self) -> None:
        """An empty set returned quietly looks like a scenario with no events."""
        with pytest.raises(ValueError, match="planner_mode='full'"):
            collect_calibration_samples(
                load_env_config(),
                policy=lambda _obs: np.zeros(2, dtype=np.float32),
                policy_identity="test",
                episodes=1,
            )

    def test_a_non_callable_policy_is_refused(self) -> None:
        with pytest.raises(TypeError, match="callable"):
            collect_calibration_samples(
                rollout_enabled_config(load_env_config()),
                policy="not a policy",
                policy_identity="test",
                episodes=1,
            )


@pytest.mark.slow
class TestContinuationCollectionRunsTheSimulator:
    def test_complete_episodes_become_samples_with_their_policy_identity(self) -> None:
        collection = collect_continuation_samples(
            load_env_config(),
            policy=lambda _obs: np.zeros(2, dtype=np.float32),
            policy_identity="held-neutral/action-zero",
            episodes=2,
            gamma=0.99,
            seed=0,
            scenario_id="two-straight-counterattack",
        )
        assert collection.complete_episode_count == 2
        assert collection.samples
        assert all(sample.complete_episode for sample in collection.samples)
        assert collection.policy_identity == "held-neutral/action-zero"
        assert collection.as_dict()["environment_version"].endswith("planner=no_rollout")

    def test_a_truncated_episode_is_not_admitted_as_complete(self) -> None:
        """``fit_ensemble`` refuses incomplete episodes; they must be flagged here."""
        config = dataclasses.replace(load_env_config(), max_episode_steps=3)
        collection = collect_continuation_samples(
            config,
            policy=lambda _obs: np.zeros(2, dtype=np.float32),
            policy_identity="held-neutral/action-zero",
            episodes=1,
            gamma=0.99,
            seed=0,
            scenario_id="two-straight-counterattack",
        )
        assert collection.complete_episode_count == 0
        assert all(not sample.complete_episode for sample in collection.samples)
