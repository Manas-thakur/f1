"""The model registry, and the drift it exists to prevent.

A registry is only worth having if a documented number cannot disagree with the
code. The load-bearing tests here are the two that compare the *document* to the
*generator*: every model the guide names must exist in the registry, and every
parameter count the guide quotes must be the one the registry derives.

The rest are about the distinction the registry exists to keep visible. A
parameter count is architecture that exists. A training loss is a bounded
observed measurement. A promotion threshold is a target gate. Merging any two
of them is how a repository ends up claiming a model is better than it is.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from afterlap_core.feature_manifest import ACTION_SIZE, ENERGY_V1, OBSERVATION_SIZE
from afterlap_core.model_registry import (
    DETERMINISTIC,
    LEARNED,
    REGISTRY_SCHEMA,
    STATISTICAL,
    as_markdown,
    build_registry,
    write_registry,
)

GUIDE = Path("docs/learning/MODEL_REGISTRY.md")


@pytest.fixture(scope="module")
def registry():
    return build_registry()


class TestTheInventoryIsComplete:
    def test_every_model_declares_a_kind_the_registry_knows(self, registry) -> None:
        assert registry.models
        for model in registry.models:
            assert model.kind in (LEARNED, DETERMINISTIC, STATISTICAL)

    def test_both_learned_models_are_present(self, registry) -> None:
        identifiers = {model.identifier for model in registry.learned}
        assert identifiers == {"sac-energy-strategy", "continuation-return-ensemble"}

    def test_the_deterministic_and_statistical_models_are_not_omitted(self, registry) -> None:
        """A reader asking what models exist is owed the ones nobody trained."""
        identifiers = {model.identifier for model in registry.models}
        assert {
            "planner-surrogate",
            "rollout-forecaster",
            "own-car-estimator",
            "rival-belief",
            "independent-rules-checker",
            "reward-objective",
            "probability-calibrator",
        } <= identifiers

    def test_every_model_names_its_module_inputs_and_outputs(self, registry) -> None:
        for model in registry.models:
            assert model.module
            assert model.inputs
            assert model.outputs
            assert model.algorithm
            assert model.purpose

    def test_every_learned_model_names_a_fallback(self, registry) -> None:
        """A model that can be disabled must say what answers instead."""
        for model in registry.learned:
            assert model.fallback

    def test_the_feature_schema_is_recorded_with_the_inventory(self, registry) -> None:
        assert registry.feature_schema_hash == ENERGY_V1.content_hash()
        assert registry.observation_size == OBSERVATION_SIZE
        assert registry.action_size == ACTION_SIZE


class TestCountsAreDerivedNotDeclared:
    def test_the_actor_count_matches_a_hand_computation(self, registry) -> None:
        """192->256->256 with mu and log_std heads, biases included."""
        pytest.importorskip("stable_baselines3", reason="the count is read off a built network")
        expected = (192 * 256 + 256) + (256 * 256 + 256) + 2 * (256 * 2 + 2)
        assert expected == 116_228
        assert registry.named("sac-energy-strategy").trainable_parameters == expected

    def test_the_ensemble_count_matches_a_hand_computation(self, registry) -> None:
        per_member = (192 * 256 + 256) + (256 * 256 + 256) + (256 * 1 + 1)
        assert per_member == 115_457
        assert registry.named("continuation-return-ensemble").trainable_parameters == per_member * 5

    def test_a_deterministic_model_reports_zero_not_none(self, registry) -> None:
        """Zero fitted parameters is a fact; None would mean not counted."""
        for identifier in ("planner-surrogate", "independent-rules-checker", "reward-objective"):
            assert registry.named(identifier).trainable_parameters == 0

    def test_a_non_parametric_model_reports_none_with_a_reason(self, registry) -> None:
        calibrator = registry.named("probability-calibrator")
        assert calibrator.trainable_parameters is None
        assert "non-parametric" in calibrator.parameter_detail

    def test_the_actor_detail_says_the_target_copy_is_excluded(self, registry) -> None:
        detail = registry.named("sac-energy-strategy").parameter_detail
        assert detail is not None
        assert "Polyak" in detail or "not counted" in detail


class TestTheThreeKindsOfClaimStaySeparate:
    def test_no_learned_model_claims_an_observed_metric_in_the_registry(self, registry) -> None:
        """Observed values live with the run that produced them, not here."""
        for model in registry.models:
            assert model.observed == {}

    def test_a_target_gate_is_never_recorded_as_an_observation(self, registry) -> None:
        calibrator = registry.named("probability-calibrator")
        assert "min_support" in calibrator.target_gates
        assert calibrator.observed == {}

    def test_the_notes_state_the_distinction_explicitly(self, registry) -> None:
        joined = " ".join(registry.notes)
        assert "target gate" in joined
        assert "synthetic" in joined.lower()

    def test_no_model_is_recorded_as_promoted(self, registry) -> None:
        """`AGENTS.md` forbids automatic promotion; nothing here may imply one."""
        for model in registry.models:
            assert "promoted" not in model.promotion_status.lower() or (
                "no candidate has been promoted" in model.promotion_status
                or "not applicable" in model.promotion_status
            )


class TestTheBreakdownIsDerivedToo:
    def test_the_sac_record_derives_every_network_it_names(self, registry) -> None:
        pytest.importorskip("stable_baselines3", reason="counts are read off built networks")
        counts = registry.named("sac-energy-strategy").architecture_counts
        assert counts["actor"] == 116_228
        assert counts["critic"] == 231_938
        assert counts["critic_target"] == counts["critic"]
        assert counts["optimiser_updated"] == counts["actor"] + counts["critic"] + 1

    def test_the_optimiser_total_excludes_the_polyak_target(self, registry) -> None:
        """Summing all three networks would count the critic twice."""
        pytest.importorskip("stable_baselines3", reason="counts are read off built networks")
        counts = registry.named("sac-energy-strategy").architecture_counts
        naive = counts["actor"] + counts["critic"] + counts["critic_target"]
        assert counts["optimiser_updated"] < naive

    def test_the_ensemble_breakdown_is_per_member_and_total(self, registry) -> None:
        counts = registry.named("continuation-return-ensemble").architecture_counts
        assert counts["ensemble"] == counts["per_member"] * 5


class TestSerialisation:
    def test_the_report_declares_its_schema_and_round_trips(self, registry, tmp_path) -> None:
        target = write_registry(registry, output=tmp_path / "registry.json")
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["schema"] == REGISTRY_SCHEMA
        assert payload["model_count"] == len(registry.models)
        assert payload["total_trainable_parameters"] == registry.total_trainable_parameters

    def test_the_content_hash_ignores_the_timestamp(self, registry) -> None:
        import dataclasses

        moved = dataclasses.replace(registry, generated_at="1999-01-01T00:00:00Z")
        assert moved.content_hash() == registry.content_hash()

    def test_the_markdown_table_lists_every_model(self, registry) -> None:
        table = as_markdown(registry)
        for model in registry.models:
            assert model.identifier in table


@pytest.fixture(scope="module")
def guide() -> str:
    if not GUIDE.is_file():
        pytest.skip(f"{GUIDE} is not present in this checkout")
    return GUIDE.read_text(encoding="utf-8")


class TestTheGuideCannotDriftFromTheCode:
    """The reason this file exists."""

    def test_the_guide_names_every_model_in_the_registry(self, guide, registry) -> None:
        for model in registry.models:
            assert model.identifier in guide, f"{model.identifier} is missing from {GUIDE}"

    def test_the_guide_names_no_model_the_registry_does_not_have(self, guide, registry) -> None:
        known = {model.identifier for model in registry.models}
        quoted = set(re.findall(r"`([a-z0-9-]+)`", guide))
        invented = {
            name
            for name in quoted
            if name.endswith(("-model", "-ensemble", "-estimator", "-checker")) and name not in known
        }
        assert not invented, f"{GUIDE} names models the registry does not have: {sorted(invented)}"

    def test_every_parameter_count_in_the_guide_is_one_the_registry_derives(self, guide, registry) -> None:
        """A number in prose that the generator does not produce is drift."""
        pytest.importorskip("stable_baselines3", reason="counts need the learning extra")
        derived = {
            model.trainable_parameters for model in registry.models if model.trainable_parameters is not None
        }
        derived.add(registry.total_trainable_parameters)
        for model in registry.models:
            derived.update(model.architecture_counts.values())
        quoted = {int(value.replace(",", "")) for value in re.findall(r"\*\*([\d,]{5,})\*\*", guide)}
        assert quoted, "the guide quotes no parameter count at all"
        assert quoted <= derived, f"the guide quotes counts the registry does not derive: {quoted - derived}"

    def test_the_guide_states_the_feature_schema_hash_the_code_uses(self, guide) -> None:
        assert ENERGY_V1.content_hash() in guide
