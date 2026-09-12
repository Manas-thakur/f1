"""Architecture description and trainable-parameter counting.

The counts here are the ones a model card publishes and a reviewer compares
against a baseline, so the tests are about *not overstating*. The load-bearing
one is
:func:`test_the_polyak_tracked_target_copy_is_excluded_from_the_model_size`:
Stable-Baselines3 leaves ``requires_grad=True`` on the target critic, so naively
summing trainable parameters across the policy reports the critic twice and
inflates the published size by two thirds.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

torch = pytest.importorskip("torch", reason="the architecture report walks torch modules")
pytest.importorskip("stable_baselines3", reason="the SAC description walks an SB3 policy")

import gymnasium as gym
import numpy as np
from torch import nn

from afterlap_core.feature_manifest import ACTION_SIZE, OBSERVATION_SIZE
from afterlap_core.learning.actions import action_space
from afterlap_core.learning.architecture import (
    ArchitectureReport,
    describe_ensemble,
    describe_module,
    describe_sac,
    parameter_totals,
)


def _tiny_mlp() -> nn.Module:
    return nn.Sequential(nn.Linear(4, 8), nn.ReLU(), nn.Linear(8, 1))


class TestCountsAreReadOffTheModule:
    def test_a_hand_counted_network_matches_the_report(self) -> None:
        described = describe_module(_tiny_mlp(), identity="test/mlp")
        expected = (4 * 8 + 8) + (8 * 1 + 1)
        assert expected == 49
        assert described.trainable_parameters == expected
        assert described.frozen_parameters == 0
        assert described.total_parameters == expected
        assert described.input_size == 4
        assert described.output_size == 1
        assert described.activation == "ReLU"

    def test_only_parameterised_leaves_become_rows(self) -> None:
        described = describe_module(_tiny_mlp(), identity="test/mlp")
        assert [layer.kind for layer in described.layers] == ["Linear", "Linear"]
        assert sum(layer.parameter_count for layer in described.layers) == 49

    def test_a_frozen_parameter_is_counted_separately_not_dropped(self) -> None:
        module = _tiny_mlp()
        first = cast("Any", module)[0]
        first.weight.requires_grad_(False)
        first.bias.requires_grad_(False)
        described = describe_module(module, identity="test/mlp")
        assert described.frozen_parameters == 4 * 8 + 8
        assert described.trainable_parameters == 8 * 1 + 1
        assert described.total_parameters == 49
        assert [layer.trainable for layer in described.layers] == [False, True]

    def test_buffers_are_reported_but_never_folded_into_a_parameter_count(self) -> None:
        module = nn.BatchNorm1d(6)
        trainable, frozen, buffers = parameter_totals(module)
        assert trainable == 12
        assert frozen == 0
        assert buffers > 0
        described = describe_module(module, identity="test/norm")
        assert described.total_parameters == 12
        assert described.buffer_elements == buffers

    def test_the_report_states_its_own_absence(self) -> None:
        empty = ArchitectureReport()
        assert empty.trainable_parameters == 0
        assert "itself a defect" in empty.as_markdown()


class _ShapeOnlyEnv(gym.Env):
    """The observation and action spaces alone, so SAC can build its networks.

    Nothing is trained against this and nothing is stepped: the architecture
    report only needs the constructed modules, and building them against the
    real simulator environment would make an architecture test depend on the
    physics.
    """

    def __init__(self) -> None:
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_SIZE,), dtype=np.float32
        )
        self.action_space = action_space()

    def reset(self, *, seed=None, options=None):
        return np.zeros(OBSERVATION_SIZE, dtype=np.float32), {}

    def step(self, action):
        return np.zeros(OBSERVATION_SIZE, dtype=np.float32), 0.0, True, False, {}


@pytest.fixture(scope="module")
def sac_model():
    from stable_baselines3 import SAC

    return SAC(
        "MlpPolicy",
        _ShapeOnlyEnv(),
        policy_kwargs={"net_arch": [32, 32]},
        buffer_size=32,
        learning_starts=1_000_000,
        seed=3,
        device="cpu",
        verbose=0,
    )


class TestSacDescription:
    def test_every_network_is_described(self, sac_model) -> None:
        report = describe_sac(sac_model)
        assert [net.identity for net in report.networks] == [
            "sac/actor",
            "sac/critic",
            "sac/critic_target",
        ]
        actor = report.named("sac/actor")
        assert actor is not None
        assert actor.input_size == OBSERVATION_SIZE
        assert actor.output_size == ACTION_SIZE

    def test_the_polyak_tracked_target_copy_is_excluded_from_the_model_size(self, sac_model) -> None:
        """The distinction that stops a published count being inflated.

        SB3 2.9.0 builds ``critic_target`` as a full copy of the critic and does
        not clear ``requires_grad``, while the optimiser is built over
        ``critic.parameters()`` alone. Summing ``requires_grad`` tensors across
        the policy therefore counts the critic twice.
        """
        report = describe_sac(sac_model)
        critic = report.named("sac/critic")
        target = report.named("sac/critic_target")
        assert critic is not None
        assert target is not None

        assert target.trainable_parameters == critic.trainable_parameters
        assert target.optimiser_updated is False
        assert target.update_rule == "polyak_average_of_critic"
        assert target.optimiser_updated_parameters == 0

        actor = report.named("sac/actor")
        assert actor is not None
        assert report.optimiser_updated_parameters == (
            actor.trainable_parameters + critic.trainable_parameters
        )
        assert report.trainable_parameters == (
            report.optimiser_updated_parameters + target.trainable_parameters
        )
        assert report.optimiser_updated_parameters < report.trainable_parameters

    def test_the_optimiser_really_excludes_the_target_parameters(self, sac_model) -> None:
        """The claim above is checked against the library, not assumed."""
        optimised = {
            id(parameter)
            for group in sac_model.critic.optimizer.param_groups
            for parameter in group["params"]
        }
        target_ids = {id(parameter) for parameter in sac_model.critic_target.parameters()}
        assert optimised.isdisjoint(target_ids)
        assert optimised == {id(p) for p in sac_model.critic.parameters()}

    def test_the_counting_note_travels_with_the_numbers(self, sac_model) -> None:
        payload = describe_sac(sac_model).as_dict()
        assert "counts a Polyak-tracked target copy a second time" in payload["counting_note"]
        assert "polyak" in describe_sac(sac_model).as_markdown().lower()

    def test_a_learned_entropy_coefficient_is_named_and_not_silently_folded_in(self, sac_model) -> None:
        report = describe_sac(sac_model)
        assert sac_model.log_ent_coef is not None
        assert any("entropy coefficient is learned" in note for note in report.notes)
        assert any("not included in the network totals" in note for note in report.notes)

    def test_a_model_without_a_policy_is_refused(self) -> None:
        with pytest.raises(TypeError, match="\\.policy"):
            describe_sac(object())


class TestEnsembleDescription:
    def test_members_are_counted_individually_not_multiplied(self) -> None:
        from afterlap_contracts import SupportThresholds
        from afterlap_core.feature_manifest import ENERGY_V1
        from afterlap_core.learning.value import ContinuationEnsemble, TargetScaler, ValueMember

        members = [ValueMember(hidden=(16, 16)) for _ in range(3)]
        ensemble = ContinuationEnsemble(
            members,
            TargetScaler(mean=0.0, std=1.0, fitted_on="train"),
            feature_hash=ENERGY_V1.content_hash(),
            continuation_controller="test",
            return_definition_hash="sha256:test",
            support=SupportThresholds(
                max_ensemble_disagreement=5.0,
                max_clip_fraction=0.1,
                min_known_mask_fraction=0.6,
            ),
            hidden=(16, 16),
        )
        report = describe_ensemble(ensemble)
        assert len(report.networks) == 3
        per_member = describe_module(members[0], identity="probe").trainable_parameters
        assert report.optimiser_updated_parameters == 3 * per_member
        assert any("spread is not a calibrated uncertainty" in note for note in report.notes)

    def test_something_that_is_not_an_ensemble_is_refused(self) -> None:
        with pytest.raises(TypeError, match="ContinuationEnsemble"):
            describe_ensemble(object())
