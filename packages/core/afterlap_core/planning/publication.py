"""Turning a planning result into the evidence a published payload carries.

The runtime used to build a recommendation from ``planning.accepted[0]`` with
``outcomes=()`` and ``probabilities=()``, discarding everything the planner had
computed. This module is the reduction that was missing, and it exists here
rather than in ``apps/api`` for one reason: the evaluation harness and the
session runtime must publish the *same* derivation of the same result, or a
benchmark would score something other than what an engineer is shown.

Two details are load-bearing.

**The selected plan is ``selected_plan_id``, never ``accepted[0]``.**
``PlanningResult.accepted`` is ordered by generation score;
``selected_plan_id`` comes from :func:`~afterlap_core.planning.scoring.select_instruction`,
which applies hysteresis, minimum dwell and incumbent preference. For the
fixed-schedule baseline the two coincide, which is why reading position zero
never failed before. For the real planner they do not, and taking position zero
would publish a non-selected candidate and silently discard every dwell rule.

**A disabled learned contribution publishes no learned number.** The contract
enforces it, and :func:`learned_contribution` never populates a continuation
value it did not obtain from a model that was in support.
"""

from __future__ import annotations

from collections.abc import Sequence

from afterlap_contracts import (
    ActionCode,
    CalibrationStatus,
    CandidatePlan,
    CheckStatus,
    LearnedContribution,
    OutcomeRange,
    PlanningResult,
    ProbabilityStatement,
    ReasonCode,
    RecommendationAlternative,
)

from .forecast import outcome_ranges

__all__ = [
    "alternatives_for",
    "learned_contribution",
    "probabilities_for",
    "ranges_for",
    "selected_candidate",
]

_CHECKER_REJECTED = "the independent checker did not pass this candidate"
_NOT_SELECTED = "the instruction-selection rule preferred another candidate"


def selected_candidate(result: PlanningResult) -> CandidatePlan | None:
    """The plan the planner actually selected, or ``None``.

    Reads ``selected_plan_id``. Position zero of ``accepted`` is the
    highest-generation-score candidate, which is a different thing.
    """
    if result.selected_plan_id is None:
        return None
    return next((plan for plan in result.accepted if plan.id == result.selected_plan_id), None)


def _terminal_energy_j(plan: CandidatePlan) -> float | None:
    """Weighted mean final energy across the feasible scenarios, or ``None``."""
    rows = [
        (outcome.final_energy_j, outcome.weight)
        for outcome in plan.scenario_outcomes
        if outcome.feasible and outcome.final_energy_j is not None
    ]
    if not rows:
        return plan.terminal_target_energy_j
    total = sum(weight for _, weight in rows)
    if total <= 0.0:
        return None
    return sum(float(value) * weight for value, weight in rows) / total


def _display_text(plan: CandidatePlan) -> str:
    head = plan.profile_segments[0]
    return (
        f"{plan.intention.value.replace('_', ' ')}: {head.profile_id.value} "
        f"from {head.start_progress_m:.0f} m"
    )


def alternatives_for(
    result: PlanningResult,
    *,
    recommended_plan_id: str | None = None,
    include_rejected: bool = True,
    limit: int | None = None,
) -> tuple[RecommendationAlternative, ...]:
    """Every candidate considered, ranked, with the recommended one at rank 1.

    ``recommended_plan_id`` is what was actually *published*, which is not the
    same as ``result.selected_plan_id``. The planner selects a candidate; the
    runtime then re-checks it independently and withdraws advice when the
    checker refuses. On a withdrawal there is no recommendation, so nothing is
    marked selected -- the candidates are still listed, because an engineer
    inspecting a withdrawal needs to see what was considered and rejected.

    Passing ``None`` therefore means "no plan was recommended", not "work it out
    from the planner's own choice".

    Rejected candidates are included by default and carry the *checker's*
    verdict rather than the planner's. A candidate the checker refused is a
    different fact from one that lost on score, and an engineer inspecting a
    decision needs to be able to tell them apart.

    The accepted candidates keep **the planner's own order**. They are not
    re-sorted by ``final_score``, because the two planners in this repository
    disagree about its direction: ``scoring.select_instruction`` takes the
    ``min`` -- the core planner's score is a cost -- while
    ``session.baseline_planner`` ranks by ``-final_score``. Re-sorting would
    silently invert one of them, so ``score_delta_vs_selected`` is published as
    the plain arithmetic difference and no ordering claims a direction.
    """
    chosen = (
        next((plan for plan in result.accepted if plan.id == recommended_plan_id), None)
        if recommended_plan_id is not None
        else None
    )
    selected = chosen if chosen is not None and chosen.constraint_result.status is CheckStatus.PASS else None
    ordered: list[CandidatePlan] = []
    if selected is not None:
        ordered.append(selected)
    ordered.extend(plan for plan in result.accepted if selected is None or plan.id != selected.id)
    if include_rejected:
        ordered.extend(sorted(result.rejected, key=lambda plan: plan.id))

    baseline = selected.objective.final_score if selected is not None else None
    rows: list[RecommendationAlternative] = []
    for index, plan in enumerate(ordered if limit is None else ordered[:limit]):
        is_selected = selected is not None and plan.id == selected.id
        passed = plan.constraint_result.status is CheckStatus.PASS
        if is_selected:
            reason = None
        elif not passed:
            reason = _CHECKER_REJECTED
        else:
            reason = _NOT_SELECTED
        rows.append(
            RecommendationAlternative(
                plan_id=plan.id,
                action_code=plan.intention,
                display_text=_display_text(plan),
                rank=index + 1,
                selected=is_selected,
                constraint_status=plan.constraint_result.status,
                final_score=plan.objective.final_score,
                score_delta_vs_selected=(
                    0.0
                    if is_selected
                    else (None if baseline is None else plan.objective.final_score - baseline)
                ),
                expected_utility=plan.objective.expected_utility,
                cvar_loss=plan.objective.cvar_loss,
                terminal_energy_j=_terminal_energy_j(plan),
                switch_count=plan.objective.switch_count,
                switching_penalty=plan.objective.lambda_switch * plan.objective.switch_count,
                rejected_reason=reason,
                reason_codes=plan.reason_codes,
            )
        )
    return tuple(rows)


def probabilities_for(result: PlanningResult) -> tuple[ProbabilityStatement, ...]:
    """The selected plan's event probabilities. Empty when nothing was selected."""
    selected = selected_candidate(result)
    return () if selected is None else selected.probabilities


def ranges_for(result: PlanningResult) -> tuple[OutcomeRange, ...]:
    """The selected plan's per-checkpoint spread across the ensemble."""
    selected = selected_candidate(result)
    return () if selected is None else outcome_ranges(selected.scenario_outcomes)


def learned_contribution(
    result: PlanningResult,
    *,
    baseline_identity: str,
    bundle_id: str | None = None,
    weights_hash: str | None = None,
    calibrator_id: str | None = None,
    continuation_value: float | None = None,
    disagreement: float | None = None,
    member_count: int | None = None,
    in_support: bool = False,
    support_reason: str | None = None,
    extra_reason_codes: Sequence[ReasonCode] = (),
) -> LearnedContribution:
    """The per-decision learned verdict, with nothing published from off.

    ``continuation_value`` is dropped whenever the contribution is disabled or
    out of support, because the contract refuses it and because a value from a
    model that did not contribute would misattribute the decision.
    """
    selected = selected_candidate(result)
    codes = list(extra_reason_codes)
    if selected is not None:
        codes.extend(selected.reason_codes)
    codes.extend(result.reason_codes)
    enabled = bool(result.learned_contribution_enabled)
    usable = enabled and in_support

    calibration = CalibrationStatus.UNAVAILABLE
    if selected is not None and selected.probabilities:
        statuses = {statement.calibration_status for statement in selected.probabilities}
        if statuses == {CalibrationStatus.CALIBRATED}:
            calibration = CalibrationStatus.CALIBRATED
        elif CalibrationStatus.UNCALIBRATED in statuses:
            calibration = CalibrationStatus.UNCALIBRATED

    return LearnedContribution(
        enabled=enabled,
        bundle_id=bundle_id if enabled else None,
        weights_hash=weights_hash,
        in_support=usable,
        support_reason=support_reason,
        continuation_value=continuation_value if usable else None,
        disagreement=None if disagreement is None else abs(float(disagreement)),
        member_count=member_count,
        calibrator_id=calibrator_id,
        calibration_status=calibration,
        baseline_identity=baseline_identity,
        reason_codes=tuple(dict.fromkeys(code for code in codes if isinstance(code, ReasonCode))),
    )


def withdrawal_action() -> ActionCode:
    """The action code a withdrawal publishes. Named so it cannot drift."""
    return ActionCode.WITHDRAW_ADVICE


__all__ += ["withdrawal_action"]
