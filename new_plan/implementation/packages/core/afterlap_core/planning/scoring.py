"""Ranking, learned reranking and instruction lifecycle.

Ranking uses the frozen objective and nothing else: expected utility, the
poor-tail CVaR term and the instruction-switch cost, each recorded separately on
:class:`~afterlap_contracts.planning.ObjectiveTerms` so no component can hide
inside a single score. The score is dimensionless. Elapsed time, energy,
position and probability are published as their own physical fields.

Learned continuation
--------------------

``07_learning/VALUE_AND_CALIBRATION.md`` is explicit that the analytic terminal
term belongs to **candidate generation** and the learned ensemble belongs to
**reranking of finalists**, and that the two must not both be counted. That is
implemented literally here:

* ``generation_score`` is the score the solver optimised, containing the
  analytic continuation;
* ``final_score`` starts equal to it. When a learned bundle is present *and* in
  support, each rolled-out scenario's analytic terminal value is **removed** and
  the ensemble's value substituted, the tail term is recomputed on the new
  losses, and the configured disagreement penalty is added;
* with no bundle, or one out of support, learned scoring is disabled and
  ``final_score`` is the baseline value *exactly* — the same float, not an
  approximation. ``test_determinism.py`` asserts that by equality.

Chatter and invalidation
------------------------

An improvement threshold and a minimum dwell suppress instruction chatter. They
are overridden without exception by an invalidation: a safety or rule change, an
expiry, or the current instruction ceasing to be legal switches immediately, and
hysteresis never delays that.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Protocol, runtime_checkable

from afterlap_contracts import (
    ActionCode,
    CheckStatus,
    ConstraintResult,
    DeploymentProfile,
    ObjectiveTerms,
    ProbabilityStatement,
    ProfileSegment,
    ReasonCode,
    ScenarioOutcome,
)

from .objective import ObjectiveManifest
from .optimiser import AllocationSolution
from .segments import PlanFrame
from .surrogate import SurrogateWeights, cvar

__all__ = [
    "ActivePlan",
    "ContinuationModel",
    "InvalidationCause",
    "LearnedOutcome",
    "ScoredCandidate",
    "Selection",
    "apply_learned_reranking",
    "build_objective_terms",
    "select_instruction",
    "switch_count_for",
]


@runtime_checkable
class ContinuationModel(Protocol):
    """A frozen learned continuation ensemble, used only to rerank finalists.

    The planner never differentiates through this: it is evaluated outside the
    compiled solver, exactly as ``VALUE_AND_CALIBRATION.md`` requires.
    """

    @property
    def bundle_id(self) -> str: ...

    def in_support(self, features: Mapping[str, float]) -> bool:
        """False disables the learned contribution for this decision."""

    def continuation_value(self, features: Mapping[str, float]) -> tuple[float, float]:
        """``(value, ensemble_disagreement)`` in the objective's utility units."""


class InvalidationCause(StrEnum):
    """Why an outstanding instruction must be replaced regardless of hysteresis."""

    RULESET_CHANGED = "ruleset_changed"
    EXPIRED = "expired"
    UNKNOWN_CONDITION = "unknown_condition"
    NO_LONGER_ADMISSIBLE = "no_longer_admissible"
    SAFETY_STATE = "safety_state"


@dataclass(frozen=True, slots=True)
class ActivePlan:
    """The instruction currently in force, as the planner needs to see it."""

    plan_id: str
    action_code: ActionCode
    selected_at_s: float
    expires_at_s: float
    ruleset_hash: str
    final_score: float
    head_profile: DeploymentProfile


@dataclass(frozen=True, slots=True)
class LearnedOutcome:
    """What the learned reranking did, so it can be audited afterwards."""

    enabled: bool
    bundle_id: str | None
    reason_codes: tuple[ReasonCode, ...]
    disagreement: float


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """One optimised, re-simulated and independently rechecked candidate."""

    candidate_id: str
    action_code: ActionCode
    frame: PlanFrame
    segments: tuple[ProfileSegment, ...]
    solution: AllocationSolution
    scenario_outcomes: tuple[ScenarioOutcome, ...]
    probabilities: tuple[ProbabilityStatement, ...]
    constraint_result: ConstraintResult
    objective: ObjectiveTerms
    reason_codes: tuple[ReasonCode, ...]
    learned: LearnedOutcome

    @property
    def accepted(self) -> bool:
        """Only a plan the independent checker passed may be recommended.

        ``unknown`` is not acceptance. A candidate whose applicable conditions
        could not be resolved is rejected, not downgraded.
        """
        return self.constraint_result.status is CheckStatus.PASS

    @property
    def final_score(self) -> float:
        return self.objective.final_score


def switch_count_for(
    segments: Sequence[ProfileSegment],
    active_profile: DeploymentProfile | None,
) -> int:
    """Instruction changes the engineer would have to call for this plan.

    One for taking the car off whatever it is doing now, plus one for each
    profile transition inside the plan. This is the quantity
    ``objective-v1.yaml`` charges ``lambda_switch`` against.
    """
    if not segments:
        return 0
    count = 0
    if active_profile is None or segments[0].profile_id is not active_profile:
        count += 1
    for previous, following in pairwise(segments):
        if previous.profile_id is not following.profile_id:
            count += 1
    return count


def build_objective_terms(
    solution: AllocationSolution,
    objective: ObjectiveManifest,
    *,
    switch_count: int,
) -> ObjectiveTerms:
    """The generation-time objective decomposition.

    ``final_score`` is set equal to ``generation_score``. It only ever moves in
    :func:`apply_learned_reranking`, and only when a learned bundle is present
    and in support.
    """
    score = (
        solution.expected_utility
        + objective.lambda_tail * solution.cvar_loss
        + objective.lambda_switch * switch_count
    )
    return ObjectiveTerms(
        objective_version=objective.objective_id,
        expected_utility=solution.expected_utility,
        tail_alpha=objective.tail_alpha,
        cvar_loss=solution.cvar_loss,
        lambda_tail=objective.lambda_tail,
        switch_count=switch_count,
        lambda_switch=objective.lambda_switch,
        disagreement_penalty=0.0,
        generation_score=score,
        final_score=score,
    )


def _terminal_features(
    outcome: ScenarioOutcome,
    frame: PlanFrame,
    weights: SurrogateWeights,
) -> dict[str, float]:
    """Belief state at the end of the explicit horizon, for the ensemble."""
    return {
        "own_energy_j": float(outcome.final_energy_j or 0.0),
        "horizon_s": frame.horizon_s,
        "continuation_availability": frame.continuation_availability,
        "initial_advantage_s": weights.initial_advantage_s,
        "speed_mps": frame.speed_mps,
        "energy_floor_j": frame.energy_floor_j,
        "energy_ceiling_j": frame.energy_ceiling_j,
    }


def apply_learned_reranking(
    terms: ObjectiveTerms,
    outcomes: Sequence[ScenarioOutcome],
    frame: PlanFrame,
    weights: SurrogateWeights,
    objective: ObjectiveManifest,
    model: ContinuationModel | None,
    *,
    disagreement_weight: float,
) -> tuple[ObjectiveTerms, tuple[ScenarioOutcome, ...], LearnedOutcome]:
    """Rerank one candidate's finalists with the learned continuation ensemble.

    Returns the terms, the outcomes (with their terminal value and source
    rewritten when the ensemble was used) and an audit record. When the model is
    absent or out of support the terms and outcomes are returned **unchanged
    objects**, so the disabled path is bit-for-bit the baseline path.
    """
    if model is None:
        return (
            terms,
            tuple(outcomes),
            LearnedOutcome(
                enabled=False,
                bundle_id=None,
                reason_codes=(ReasonCode.LEARNED_MODEL_DISABLED, ReasonCode.BASELINE_FALLBACK),
                disagreement=0.0,
            ),
        )
    if not outcomes:
        return (
            terms,
            tuple(outcomes),
            LearnedOutcome(
                enabled=False,
                bundle_id=model.bundle_id,
                reason_codes=(ReasonCode.LEARNED_MODEL_DISABLED, ReasonCode.BASELINE_FALLBACK),
                disagreement=0.0,
            ),
        )

    features = [_terminal_features(outcome, frame, weights) for outcome in outcomes]
    if not all(model.in_support(feature) for feature in features):
        return (
            terms,
            tuple(outcomes),
            LearnedOutcome(
                enabled=False,
                bundle_id=model.bundle_id,
                reason_codes=(ReasonCode.LEARNED_MODEL_OUT_OF_SUPPORT, ReasonCode.BASELINE_FALLBACK),
                disagreement=0.0,
            ),
        )

    rewritten: list[ScenarioOutcome] = []
    losses: list[float] = []
    probabilities: list[float] = []
    worst_disagreement = 0.0
    for outcome, feature in zip(outcomes, features, strict=True):
        value, disagreement = model.continuation_value(feature)
        worst_disagreement = max(worst_disagreement, float(disagreement))
        analytic = float(outcome.terminal_value or 0.0)
        # Remove the analytic continuation before adding the learned one, so the
        # two are never both counted.
        utility = outcome.utility + analytic - float(value)
        losses.append(utility)
        probabilities.append(outcome.weight)
        rewritten.append(
            outcome.model_copy(
                update={
                    "utility": utility,
                    "terminal_value": float(value),
                    "terminal_value_source": model.bundle_id,
                }
            )
        )

    total = sum(probabilities) or 1.0
    normalised = [p / total for p in probabilities]
    expected = sum(p * loss for p, loss in zip(normalised, losses, strict=True))
    cvar_value, _, _ = cvar(losses, normalised, objective.tail_alpha)
    penalty = disagreement_weight * worst_disagreement
    score = (
        expected + objective.lambda_tail * cvar_value + objective.lambda_switch * terms.switch_count + penalty
    )
    updated = terms.model_copy(
        update={
            "expected_utility": expected,
            "cvar_loss": cvar_value,
            "disagreement_penalty": penalty,
            "final_score": score,
        }
    )
    return (
        updated,
        tuple(rewritten),
        LearnedOutcome(
            enabled=True,
            bundle_id=model.bundle_id,
            reason_codes=(),
            disagreement=worst_disagreement,
        ),
    )


@dataclass(frozen=True, slots=True)
class Selection:
    """Which instruction the planner published and why."""

    chosen: ScoredCandidate | None
    switched: bool
    invalidation: InvalidationCause | None
    reason_codes: tuple[ReasonCode, ...]
    improvement: float | None
    detail: str


def select_instruction(
    candidates: Sequence[ScoredCandidate],
    objective: ObjectiveManifest,
    *,
    current: ActivePlan | None,
    now_s: float,
    invalidation: InvalidationCause | None = None,
) -> Selection:
    """Choose between the incumbent instruction and the best new candidate.

    Hysteresis applies only while the incumbent is still legal and unexpired.
    Any invalidation overrides both the improvement threshold and the minimum
    dwell, without exception.
    """
    accepted = [candidate for candidate in candidates if candidate.accepted]
    if not accepted:
        return Selection(
            chosen=None,
            switched=False,
            invalidation=invalidation,
            reason_codes=(),
            improvement=None,
            detail="no candidate passed the independent checker",
        )
    best = min(accepted, key=lambda candidate: (candidate.final_score, candidate.candidate_id))

    if current is None:
        return Selection(
            chosen=best,
            switched=True,
            invalidation=None,
            reason_codes=(),
            improvement=None,
            detail="no instruction was in force",
        )
    if invalidation is not None:
        return Selection(
            chosen=best,
            switched=True,
            invalidation=invalidation,
            reason_codes=(),
            improvement=None,
            detail=f"immediate invalidation ({invalidation.value}) overrides hysteresis",
        )

    incumbent = next(
        (candidate for candidate in accepted if candidate.action_code is current.action_code), None
    )
    if incumbent is None:
        return Selection(
            chosen=best,
            switched=True,
            invalidation=InvalidationCause.NO_LONGER_ADMISSIBLE,
            reason_codes=(),
            improvement=None,
            detail="the instruction in force is no longer a legal candidate",
        )

    improvement = incumbent.final_score - best.final_score
    dwell_s = now_s - current.selected_at_s
    if dwell_s < objective.minimum_dwell_s:
        return Selection(
            chosen=incumbent,
            switched=False,
            invalidation=None,
            reason_codes=(ReasonCode.SWITCH_COST_DOMINATES,),
            improvement=improvement,
            detail=(
                f"minimum dwell {objective.minimum_dwell_s:.2f} s not met "
                f"({dwell_s:.2f} s elapsed since the instruction was selected)"
            ),
        )
    if improvement < objective.improvement_threshold:
        return Selection(
            chosen=incumbent,
            switched=False,
            invalidation=None,
            reason_codes=(ReasonCode.SMALL_EXPECTED_IMPROVEMENT,),
            improvement=improvement,
            detail=(
                f"expected improvement {improvement:.4f} is below the declared threshold "
                f"{objective.improvement_threshold:.4f}"
            ),
        )
    return Selection(
        chosen=best,
        switched=best.candidate_id != incumbent.candidate_id,
        invalidation=None,
        reason_codes=(),
        improvement=improvement,
        detail=f"expected improvement {improvement:.4f} clears the declared threshold",
    )
