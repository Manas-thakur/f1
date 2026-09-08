"""Bounded tactical enumeration.

Five intentions — maintain, prepare attack, attack, defend and recover — each a
short sequence of driver-selectable profiles over the corridor. The set is fixed
and small on purpose: the continuous solver decides *how much* energy, the
enumerator decides *which shape*, and neither is allowed to grow without bound.

Pruning happens **before** optimisation, and it is a suppression, not a
downgrade. If a required profile is not admissible the candidate disappears
along with a reason code; it is never quietly replaced by a weaker instruction
that the engineer would read as the planner's considered advice. In particular:

* an unresolved applicable condition empties ``RuleContext.admissible_profiles``,
  so *every* candidate is suppressed and the planner reports
  ``PlanningStatus.RULES_UNKNOWN``;
* unknown Overtake eligibility removes the attack candidate entirely;
* an energy floor or a thermal derate that closes the deployment ceiling removes
  the candidates that would have deployed;
* a corridor whose lead time or instruction window no human could execute is
  suppressed with ``INSUFFICIENT_EXECUTION_LEAD``.

The maintain candidate is the validated baseline and is enumerated first, so no
learned proposal can remove a feasible reference from the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from afterlap_contracts import (
    ActionCode,
    DeploymentProfile,
    EligibilityState,
    ReasonCode,
    RuleContext,
    RuleManifest,
    StateEstimate,
)

from ..rules import THERMAL_TEMPERATURE_UNKNOWN
from .segments import PlanFrame, build_frame

if TYPE_CHECKING:
    from .config import PlannerConfig

__all__ = [
    "TEMPLATES",
    "EnumeratedCandidate",
    "EnumerationResult",
    "IntentionTemplate",
    "SuppressedCandidate",
    "enumerate_intentions",
]


@dataclass(frozen=True, slots=True)
class IntentionTemplate:
    """One tactical shape: which profiles, in which zones, and what it needs."""

    action_code: ActionCode
    profiles: tuple[DeploymentProfile, ...]
    requires_rival_ahead: bool
    requires_rival_behind: bool
    display_verb: str
    end_condition: str

    @property
    def required_profiles(self) -> frozenset[DeploymentProfile]:
        return frozenset(self.profiles)


TEMPLATES: tuple[IntentionTemplate, ...] = (
    IntentionTemplate(
        action_code=ActionCode.MAINTAIN,
        profiles=(DeploymentProfile.NEUTRAL,),
        requires_rival_ahead=False,
        requires_rival_behind=False,
        display_verb="Hold neutral deployment",
        end_condition="next planner update",
    ),
    IntentionTemplate(
        action_code=ActionCode.RECOVER,
        profiles=(DeploymentProfile.HARVEST, DeploymentProfile.CONSERVE),
        requires_rival_ahead=False,
        requires_rival_behind=False,
        display_verb="Harvest, then conserve",
        end_condition="end of the planned corridor",
    ),
    IntentionTemplate(
        action_code=ActionCode.PREPARE_ATTACK,
        profiles=(DeploymentProfile.CONSERVE, DeploymentProfile.PUSH),
        requires_rival_ahead=True,
        requires_rival_behind=False,
        display_verb="Conserve into the zone, then push",
        end_condition="end of the planned corridor",
    ),
    IntentionTemplate(
        action_code=ActionCode.ATTACK,
        profiles=(DeploymentProfile.OVERTAKE, DeploymentProfile.CONSERVE),
        requires_rival_ahead=True,
        requires_rival_behind=False,
        display_verb="Overtake in the zone, then conserve",
        end_condition="end of the activation zone",
    ),
    IntentionTemplate(
        action_code=ActionCode.DEFEND,
        profiles=(DeploymentProfile.PUSH, DeploymentProfile.NEUTRAL),
        requires_rival_ahead=False,
        requires_rival_behind=True,
        display_verb="Push to hold position, then neutral",
        end_condition="end of the planned corridor",
    ),
)
"""Enumeration order. ``MAINTAIN`` is first: it is the validated baseline."""


@dataclass(frozen=True, slots=True)
class EnumeratedCandidate:
    """A surviving intention with the corridor it would be executed over."""

    template: IntentionTemplate
    frame: PlanFrame
    candidate_id: str


@dataclass(frozen=True, slots=True)
class SuppressedCandidate:
    """An intention that never reached the optimiser, and exactly why."""

    action_code: ActionCode
    reason_codes: tuple[ReasonCode, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class EnumerationResult:
    candidates: tuple[EnumeratedCandidate, ...]
    suppressed: tuple[SuppressedCandidate, ...]

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        seen: list[ReasonCode] = []
        for entry in self.suppressed:
            for code in entry.reason_codes:
                if code not in seen:
                    seen.append(code)
        return tuple(seen)


def _missing_profile_reason(
    profile: DeploymentProfile,
    context: RuleContext,
    estimate: StateEstimate,
) -> tuple[ReasonCode, str]:
    """Say *why* a profile is unavailable, from the resolved context alone."""
    limits = context.applicable_limits
    if context.unknown_conditions:
        if THERMAL_TEMPERATURE_UNKNOWN in context.unknown_conditions:
            return (
                ReasonCode.THERMAL_DERATE,
                "a thermal derate model is configured but no battery temperature was available",
            )
        return (
            ReasonCode.ELIGIBILITY_UNKNOWN,
            "unresolved applicable conditions: " + ", ".join(context.unknown_conditions),
        )
    if limits.deployment_ceiling_w is not None and limits.deployment_ceiling_w <= 0.0:
        return (ReasonCode.THERMAL_DERATE, "the resolved deployment ceiling is zero")
    energy = estimate.own_car.battery_energy_j.value
    floor = limits.battery_energy_min_j
    if energy is not None and floor is not None and energy <= floor:
        return (
            ReasonCode.ENERGY_FLOOR,
            f"stored energy {energy:.0f} J is at the operating floor {floor:.0f} J",
        )
    if profile is DeploymentProfile.OVERTAKE:
        if context.eligibility is EligibilityState.UNKNOWN:
            return (
                ReasonCode.ELIGIBILITY_UNKNOWN,
                "the overtake permission state has not been resolved by a detection crossing",
            )
        return (
            ReasonCode.ELIGIBILITY_UNKNOWN,
            (
                f"overtake permission is {context.eligibility.value} under flags "
                f"{[flag.value for flag in context.current_flags]}"
            ),
        )
    return (
        ReasonCode.ENERGY_FLOOR,
        (
            f"profile {profile.value} is not in the admissible set "
            f"{[p.value for p in context.admissible_profiles]}"
        ),
    )


def enumerate_intentions(
    estimate: StateEstimate,
    context: RuleContext,
    manifest: RuleManifest,
    config: PlannerConfig,
    *,
    admissible: tuple[DeploymentProfile, ...],
    track_length_m: float | None = None,
    terminal_target_energy_j: float | None = None,
) -> EnumerationResult:
    """Enumerate legal intentions, suppressing the rest with reasons.

    ``admissible`` comes from the rules module — either
    ``RuleContext.admissible_profiles`` or a recomputed
    ``rules.admissible_profiles(context, car_state)``. The enumerator asks; it
    never decides admissibility for itself.
    """
    allowed = set(admissible)
    ahead = estimate.nearest_ahead
    behind = estimate.nearest_behind

    candidates: list[EnumeratedCandidate] = []
    suppressed: list[SuppressedCandidate] = []

    for template in TEMPLATES:
        missing = sorted(template.required_profiles - allowed, key=lambda p: p.value)
        if missing:
            reason, detail = _missing_profile_reason(missing[0], context, estimate)
            suppressed.append(
                SuppressedCandidate(
                    action_code=template.action_code,
                    reason_codes=(reason,),
                    detail=f"requires {[p.value for p in missing]}: {detail}",
                )
            )
            continue
        if template.requires_rival_ahead and ahead is None:
            suppressed.append(
                SuppressedCandidate(
                    action_code=template.action_code,
                    reason_codes=(ReasonCode.GAP_TOO_LARGE,),
                    detail="no rival is believed to be ahead within the modelled field",
                )
            )
            continue
        if template.requires_rival_behind and behind is None:
            suppressed.append(
                SuppressedCandidate(
                    action_code=template.action_code,
                    reason_codes=(ReasonCode.GAP_TOO_LARGE,),
                    detail="no rival is believed to be behind within the modelled field",
                )
            )
            continue
        try:
            frame = build_frame(
                estimate,
                context,
                manifest,
                config,
                template.profiles,
                track_length_m=track_length_m,
                terminal_target_energy_j=terminal_target_energy_j,
            )
        except ValueError as exc:
            suppressed.append(
                SuppressedCandidate(
                    action_code=template.action_code,
                    reason_codes=(ReasonCode.INSUFFICIENT_EXECUTION_LEAD,),
                    detail=str(exc),
                )
            )
            continue
        candidates.append(
            EnumeratedCandidate(
                template=template,
                frame=frame,
                candidate_id=f"plan-{template.action_code.value}-r{estimate.revision}",
            )
        )

    limit = config.budgets.max_candidates
    if len(candidates) > limit:
        for extra in candidates[limit:]:
            suppressed.append(
                SuppressedCandidate(
                    action_code=extra.template.action_code,
                    reason_codes=(ReasonCode.SMALL_EXPECTED_IMPROVEMENT,),
                    detail=(
                        f"candidate budget of {limit} reached; enumeration order keeps the "
                        "validated baseline and the highest-priority tactical shapes"
                    ),
                )
            )
        candidates = candidates[:limit]

    return EnumerationResult(candidates=tuple(candidates), suppressed=tuple(suppressed))
