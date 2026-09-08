"""Resolve the applicable regulatory context at one point in the session.

``resolve_context`` intersects, in this order:

* the absolute electrical DC ceiling at the declared measurement bus;
* the speed-dependent curve, preferring an event/sector curve when one applies;
* the battery physical operating window;
* temperature derating of the deployment ceiling;
* the stateful power-change limit;
* the per-lap recharge allowance ledger, measured on the *charge* bus.

Two rules are load-bearing here:

1. **Buses are never mixed.** The ERS-K DC deployment ceiling and the CU-K DC
   recharge allowance are separate quantities with separate ledgers
   (``contracts/UNITS_TIME.md``).
2. **Overtake eligibility is permission, not energy.** It can only remove
   ``OVERTAKE`` from the admissible set; it never adds joules to the battery.

If any applicable condition is unresolved, the returned context carries a
non-empty ``unknown_conditions`` and an **empty** ``admissible_profiles``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from afterlap_contracts import (
    SCHEMA_VERSION,
    ApplicableLimits,
    DeploymentProfile,
    EligibilityState,
    FlagState,
    PowerCurve,
    RuleContext,
    RuleManifest,
)

from .state import CarState, RaceEvent, RaceEventKind, sorted_race_events

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .packs import RulePack, ThermalDerateSpec, UnknownConditionSpec

__all__ = [
    "RESTRICTIVE_FLAGS",
    "THERMAL_TEMPERATURE_UNKNOWN",
    "ResolvedRaceControl",
    "admissible_profiles",
    "fold_race_events",
    "resolve_context",
    "resolve_pack_context",
    "select_curve",
]

RESTRICTIVE_FLAGS: frozenset[FlagState] = frozenset(
    {FlagState.SAFETY_CAR, FlagState.VIRTUAL_SAFETY_CAR, FlagState.RED, FlagState.DOUBLE_YELLOW}
)
"""Flag states under which no extra-deployment profile is admissible."""

_PROFILE_ORDER: tuple[DeploymentProfile, ...] = (
    DeploymentProfile.HARVEST,
    DeploymentProfile.CONSERVE,
    DeploymentProfile.NEUTRAL,
    DeploymentProfile.PUSH,
    DeploymentProfile.OVERTAKE,
)

THERMAL_TEMPERATURE_UNKNOWN = "thermal_derate_temperature_unavailable"
"""Reason code recorded when a derate model is configured but no temperature exists."""


@dataclass(frozen=True, slots=True)
class ResolvedRaceControl:
    """The folded level-3 race-control state at one session time."""

    flags: tuple[FlagState, ...]
    unknown_conditions: tuple[str, ...]
    last_invalidation_at_s: float | None
    last_invalidation_reason: str | None
    last_lap_reset_at_s: float | None


def fold_race_events(events: Sequence[RaceEvent], session_time_s: float) -> ResolvedRaceControl:
    """Apply every race event at or before ``session_time_s`` in contract order."""
    flags: tuple[FlagState, ...] = (FlagState.UNKNOWN,)
    unknown: set[str] = set()
    last_invalidation_at_s: float | None = None
    last_invalidation_reason: str | None = None
    last_lap_reset_at_s: float | None = None
    for event in sorted_race_events(events):
        if event.at_session_time_s > session_time_s:
            break
        match event.kind:
            case RaceEventKind.FLAG:
                flags = event.flags or (FlagState.UNKNOWN,)
            case RaceEventKind.INVALIDATION:
                last_invalidation_at_s = event.at_session_time_s
                last_invalidation_reason = event.reason
            case RaceEventKind.LAP_RESET:
                last_lap_reset_at_s = event.at_session_time_s
            case RaceEventKind.UNKNOWN_CONDITION:
                if event.condition:
                    unknown.add(event.condition)
    return ResolvedRaceControl(
        flags=flags,
        unknown_conditions=tuple(sorted(unknown)),
        last_invalidation_at_s=last_invalidation_at_s,
        last_invalidation_reason=last_invalidation_reason,
        last_lap_reset_at_s=last_lap_reset_at_s,
    )


def select_curve(manifest: RuleManifest, sector_id: str | None) -> PowerCurve | None:
    """Prefer an event/sector curve; otherwise the first curve with no sector scope."""
    if not manifest.power_curves:
        return None
    if sector_id is not None:
        for curve in manifest.power_curves:
            if sector_id in curve.sector_ids:
                return curve
    for curve in manifest.power_curves:
        if not curve.sector_ids:
            return curve
    return None


def _downgrade_eligibility(
    eligibility: EligibilityState,
    observed_at_s: float | None,
    race_control: ResolvedRaceControl,
) -> tuple[EligibilityState, float | None]:
    """Race control can only remove a permission; it never grants one."""
    if eligibility is EligibilityState.UNKNOWN:
        return eligibility, observed_at_s
    if eligibility not in (EligibilityState.ELIGIBLE_DETECTED, EligibilityState.ACTIVE):
        return eligibility, observed_at_s
    invalidated_at = race_control.last_invalidation_at_s
    if invalidated_at is not None and (observed_at_s is None or invalidated_at >= observed_at_s):
        return EligibilityState.INELIGIBLE, invalidated_at
    if set(race_control.flags) & RESTRICTIVE_FLAGS:
        return EligibilityState.INELIGIBLE, observed_at_s
    return eligibility, observed_at_s


def _profiles_for(
    *,
    limits: ApplicableLimits,
    eligibility: EligibilityState,
    flags: tuple[FlagState, ...],
    unknown_conditions: Sequence[str],
    battery_energy_j: float,
) -> tuple[DeploymentProfile, ...]:
    if unknown_conditions:
        return ()
    if limits.deployment_ceiling_w is None:
        return ()
    flag_set = set(flags)
    if FlagState.UNKNOWN in flag_set:
        return ()
    restricted = bool(flag_set & RESTRICTIVE_FLAGS)
    floor = limits.battery_energy_min_j if limits.battery_energy_min_j is not None else 0.0
    ceiling = limits.battery_energy_max_j
    allowed: list[DeploymentProfile] = []
    if ceiling is None or battery_energy_j < ceiling:
        allowed.append(DeploymentProfile.HARVEST)
    allowed.append(DeploymentProfile.CONSERVE)
    allowed.append(DeploymentProfile.NEUTRAL)
    has_energy = battery_energy_j > floor
    if not restricted and limits.deployment_ceiling_w > 0.0 and has_energy:
        allowed.append(DeploymentProfile.PUSH)
        if eligibility in (EligibilityState.ELIGIBLE_DETECTED, EligibilityState.ACTIVE):
            allowed.append(DeploymentProfile.OVERTAKE)
    return tuple(profile for profile in _PROFILE_ORDER if profile in allowed)


def resolve_context(
    manifest: RuleManifest,
    race_events: Sequence[RaceEvent],
    progress_m: float,
    session_time_s: float,
    car_state: CarState,
    *,
    session_id: str,
    thermal_derate: ThermalDerateSpec | None = None,
    unknown_conditions: Sequence[UnknownConditionSpec] | None = None,
) -> RuleContext:
    """Resolve the applicable limits and admissible profiles at one point.

    ``thermal_derate`` comes from the loaded :class:`~.packs.RulePack`. When a
    derate model is configured but the temperature is unavailable, the derated
    ceiling is ``None`` and the context becomes unknown — a missing measurement
    is never treated as "no derating".

    ``unknown_conditions`` carries the pack's applicability scoping. Omitting it
    fails closed: every condition named on the manifest is then treated as
    applicable, so a caller that forgets to pass the scoping gets the
    conservative answer rather than a permissive one.
    """
    race_control = fold_race_events(race_events, session_time_s)

    eligibility, observed_at_s = _downgrade_eligibility(
        car_state.eligibility, car_state.eligibility_observed_at_s, race_control
    )

    curve = select_curve(manifest, car_state.sector_id)
    curve_ceiling = (
        manifest.absolute_power_ceiling_w if curve is None else curve.ceiling_w(car_state.speed_mps)
    )
    regulatory_ceiling_w = min(manifest.absolute_power_ceiling_w, curve_ceiling)

    if unknown_conditions is None:
        applicable_pack_conditions = set(manifest.unknown_conditions)
    else:
        applicable_pack_conditions = {
            spec.condition for spec in unknown_conditions if spec.applies_to(sector_id=car_state.sector_id)
        }
    unknown: set[str] = applicable_pack_conditions | set(race_control.unknown_conditions)

    derate_factor: float | None = 1.0
    if thermal_derate is not None:
        derate_factor = thermal_derate.factor(car_state.temperature_k)
        if derate_factor is None:
            unknown.add(THERMAL_TEMPERATURE_UNKNOWN)

    deployment_ceiling_w = None if derate_factor is None else regulatory_ceiling_w * derate_factor

    allowance = manifest.recharge_allowance_per_lap_j
    remaining = None if allowance is None else allowance - car_state.recharge_used_this_lap_j

    limits = ApplicableLimits(
        deployment_ceiling_w=deployment_ceiling_w,
        recovery_ceiling_w=manifest.absolute_power_ceiling_w,
        battery_energy_min_j=manifest.battery_energy_min_j,
        battery_energy_max_j=manifest.battery_energy_max_j,
        recharge_allowance_remaining_j=remaining,
        max_power_ramp_w_per_s=manifest.max_power_ramp_w_per_s,
        thermal_derate_factor=derate_factor,
    )

    resolved_unknown = tuple(sorted(unknown))
    profiles = _profiles_for(
        limits=limits,
        eligibility=eligibility,
        flags=race_control.flags,
        unknown_conditions=resolved_unknown,
        battery_energy_j=car_state.battery_energy_j,
    )

    return RuleContext(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        season_revision=manifest.season_revision,
        ruleset_hash=manifest.content_hash(),
        event_pack_hash=None if manifest.event_pack_id is None else manifest.content_hash(),
        resolved_at_s=session_time_s,
        progress_m=progress_m,
        current_flags=race_control.flags,
        eligibility=eligibility,
        eligibility_observed_at_s=observed_at_s,
        active_curve_id=None if curve is None else curve.curve_id,
        applicable_limits=limits,
        admissible_profiles=profiles,
        unknown_conditions=resolved_unknown,
        coverage=manifest.coverage,
    )


def resolve_pack_context(
    pack: RulePack,
    progress_m: float,
    session_time_s: float,
    car_state: CarState,
    *,
    session_id: str,
    race_events: Sequence[RaceEvent] | None = None,
) -> RuleContext:
    """Resolve a context from a loaded pack, wiring in its own scoping.

    Race-control events default to the pack's own timestamped level-3 states up
    to ``session_time_s``; pass ``race_events`` to use a live stream instead.
    """
    events = pack.race_events_until(session_time_s) if race_events is None else race_events
    return resolve_context(
        pack.manifest,
        events,
        progress_m,
        session_time_s,
        car_state,
        session_id=session_id,
        thermal_derate=pack.thermal_derate,
        unknown_conditions=pack.unknown_conditions,
    )


def admissible_profiles(context: RuleContext, state: CarState) -> tuple[DeploymentProfile, ...]:
    """Profiles that are legal right now, recomputed from a resolved context.

    Callable after the context was resolved, so a changed battery level or a
    changed eligibility observation narrows the set without a full re-resolve.
    """
    eligibility = (
        state.eligibility if state.eligibility is not EligibilityState.UNKNOWN else (context.eligibility)
    )
    if context.eligibility is EligibilityState.INELIGIBLE:
        eligibility = EligibilityState.INELIGIBLE
    return _profiles_for(
        limits=context.applicable_limits,
        eligibility=eligibility,
        flags=context.current_flags,
        unknown_conditions=context.unknown_conditions,
        battery_energy_j=state.battery_energy_j,
    )
