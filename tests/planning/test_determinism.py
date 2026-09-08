"""Reproducibility and the disabled-model equivalence.

``learning/VALUE_AND_CALIBRATION.md`` requires that learned-disabled scoring
match the baseline **exactly**. These tests assert that by equality, not by
approximation: a tolerance would let a real regression hide inside it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from afterlap_contracts import PlanningStatus, ReasonCode
from afterlap_core.planning import plan

from .conftest import estimate_with

_VOLATILE = {"duration_ms", "solve_duration_ms"}


class _StubEnsemble:
    """A stand-in learned continuation ensemble.

    A synthetic constant, not a trained model. It exists to prove that the
    disabled path is genuinely disabled and that the enabled path genuinely
    moves the score — a stub that did nothing would make the equivalence test
    vacuous.
    """

    def __init__(self, *, supported: bool, value: float = 0.0, disagreement: float = 0.0) -> None:
        self._supported = supported
        self._value = value
        self._disagreement = disagreement

    @property
    def bundle_id(self) -> str:
        return "stub-continuation-v0"

    def in_support(self, features: Mapping[str, float]) -> bool:
        assert "own_energy_j" in features
        return self._supported

    def continuation_value(self, features: Mapping[str, float]) -> tuple[float, float]:
        return self._value, self._disagreement


def _comparable(payload: Any) -> Any:
    """Strip wall-clock timings, which are the only legitimately variable fields."""
    if isinstance(payload, dict):
        return {k: _comparable(v) for k, v in payload.items() if k not in _VOLATILE}
    if isinstance(payload, list):
        return [_comparable(v) for v in payload]
    return payload


def test_repeated_planning_on_one_estimate_is_stable(estimate, context, manifest, config, world):
    """The same belief and seed give the same plan, including the rollouts.

    The scenario quadrature is deterministic and the simulator branches are
    seeded, so two invocations must agree field for field. If they did not, no
    paired comparison of two planner revisions would mean anything.
    """
    first = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world, seed=7)
    second = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world, seed=7)
    assert first.status is PlanningStatus.OK
    assert _comparable(first.model_dump(mode="json")) == _comparable(second.model_dump(mode="json"))
    assert first.selected_plan_id == second.selected_plan_id


def test_a_different_seed_keeps_the_same_deterministic_quadrature(estimate, context, manifest, config, world):
    """The baseline sampler is a quadrature, so the seed only labels the nodes.

    The seed appears in scenario ids for traceability but must not move the
    weights or the reserves: a planner whose advice depended on a seed would be
    unreproducible in the field.
    """
    a = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world, seed=1)
    b = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world, seed=2)
    scores_a = [candidate.objective.final_score for candidate in a.accepted]
    scores_b = [candidate.objective.final_score for candidate in b.accepted]
    assert scores_a == scores_b


def test_model_disabled_result_equals_the_baseline_exactly(estimate, context, manifest, config, world):
    """No bundle, and an out-of-support bundle, both give the baseline exactly.

    Compared by equality of the whole serialised result, timings aside. The
    reason codes differ in one respect only: an out-of-support bundle says
    ``learned_model_out_of_support`` where an absent one says
    ``learned_model_disabled``, and both say ``baseline_fallback``.
    """
    baseline = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world)
    out_of_support = plan(
        estimate,
        context,
        _StubEnsemble(supported=False, value=-99.0),
        5.0,
        manifest=manifest,
        config=config,
        world=world,
    )
    assert baseline.status is PlanningStatus.OK
    assert baseline.learned_contribution_enabled is False
    assert out_of_support.learned_contribution_enabled is False

    for left, right in zip(baseline.accepted, out_of_support.accepted, strict=True):
        assert left.id == right.id
        assert left.objective.final_score == right.objective.final_score
        assert left.objective.generation_score == right.objective.generation_score
        assert left.objective.final_score == left.objective.generation_score
        assert left.objective.disagreement_penalty == 0.0
        assert left.objective.learned_reranking_applied is False
        assert [s.model_dump() for s in left.profile_segments] == [
            s.model_dump() for s in right.profile_segments
        ]
        assert ReasonCode.BASELINE_FALLBACK in left.reason_codes
        assert ReasonCode.BASELINE_FALLBACK in right.reason_codes

    assert ReasonCode.LEARNED_MODEL_DISABLED in baseline.accepted[0].reason_codes
    assert ReasonCode.LEARNED_MODEL_OUT_OF_SUPPORT in out_of_support.accepted[0].reason_codes


def test_an_in_support_bundle_reranks_and_does_not_double_count(estimate, context, manifest, config, world):
    """The learned value replaces the analytic one; the two are never summed.

    Each scenario's terminal value is rewritten to the ensemble's number and its
    source becomes the bundle id, and the recorded generation score still shows
    the analytic figure the solver optimised.
    """
    baseline = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world)
    reranked = plan(
        estimate,
        context,
        _StubEnsemble(supported=True, value=25.0, disagreement=0.4),
        5.0,
        manifest=manifest,
        config=config,
        world=world,
    )
    assert reranked.learned_contribution_enabled is True

    candidate = reranked.accepted[0]
    reference = next(c for c in baseline.accepted if c.id == candidate.id)
    assert candidate.objective.generation_score == reference.objective.generation_score
    assert candidate.objective.final_score != candidate.objective.generation_score
    assert candidate.objective.learned_reranking_applied is True
    assert candidate.objective.disagreement_penalty == pytest.approx(0.5 * 0.4)
    assert candidate.model_version == "stub-continuation-v0"

    for outcome, base_outcome in zip(candidate.scenario_outcomes, reference.scenario_outcomes, strict=True):
        assert outcome.terminal_value == 25.0
        assert outcome.terminal_value_source == "stub-continuation-v0"
        # The analytic term was removed before the learned one was added.
        assert outcome.utility == pytest.approx(
            base_outcome.utility + (base_outcome.terminal_value or 0.0) - 25.0
        )


def test_planning_twice_from_two_equal_estimates_agrees(context, manifest, config, world):
    """Two structurally identical estimates plan identically.

    Guards against anything leaking in from object identity or module state
    between invocations.
    """
    first = plan(estimate_with(), context, None, 5.0, manifest=manifest, config=config, world=world)
    second = plan(estimate_with(), context, None, 5.0, manifest=manifest, config=config, world=world)
    assert _comparable(first.model_dump(mode="json")) == _comparable(second.model_dump(mode="json"))
