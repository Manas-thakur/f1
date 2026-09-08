"""Control representation: driver-selectable profile segments over a corridor.

The planner's control variable is **not** a millisecond power trace. It is a
short sequence of coarse, human-executable profile instructions, each carrying a
continuous energy allocation preference. Driver execution delay and instruction
duration live in this frame, not in the objective: a segment carries the lead
time before it starts and the window the driver has to begin it, and a corridor
that cannot be executed in time is suppressed before any optimisation happens.

Only the first instruction is ever executed. The rest exists so that the
allocation of the first one is decided against a horizon that contains the
consequences, and it is replanned from observed outcomes.

Numerical agreement with the independent checker
------------------------------------------------

The frame deliberately reproduces the reintegration model that
``afterlap_core.rules.checker`` declares, so that the two disagree only where
they genuinely disagree (a different speed forecast) rather than because of an
arithmetic convention:

* the frame holds one speed across the corridor, matching a *step*
  :class:`~afterlap_core.rules.state.SpeedProfile` with a single sample. Under a
  held speed the checker's trapezoid is exact, its ceiling-time integral is
  ``C_reg(v) * duration`` and its speed-time integral is ``v * duration``;
* deployment power is therefore constant across a segment and equal to
  ``requested_budget_j / duration_s``;
* harvest is battery **gain** (``handoffs/decisions.md`` D-01); the charge-bus
  ledger is that gain divided by the charge efficiency.

``requested_budget_j`` is energy leaving the battery, per D-01. The checker's
``CheckerState.discharge_efficiency`` is therefore left at ``1.0`` so its battery
ledger is exactly that quantity; its power-ceiling comparison then treats battery
joules as bus joules, which is conservative because bus energy never exceeds
battery energy. See ``handoffs/A06-contract-proposal.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from afterlap_contracts import (
    DeploymentProfile,
    ProfileSegment,
    RuleContext,
    RuleManifest,
    StateEstimate,
)

from ..rules import CheckerState, SpeedProfile, SpeedSample
from ..simulation import DEPLOY_FRACTION, HARVEST_FRACTION

if TYPE_CHECKING:
    from .config import PlannerConfig

__all__ = [
    "SOLVER_HEADROOM",
    "FrameSegment",
    "PlanFrame",
    "build_frame",
    "checker_state_for",
    "held_speed_profile",
    "to_profile_segments",
]

SOLVER_HEADROOM = 1.0e-4
"""Relative headroom kept below every hard bound.

IPOPT converges to its own tolerance, so a solution sitting exactly on a bound
can overshoot it by a few parts in ``1e8``. On a megajoule budget that is enough
to turn the checker's zero-margin *pass* into a small negative *fail*. The
headroom is a numerical allowance, not a safety factor, and it is small enough
that it cannot mask a real infeasibility.
"""


@dataclass(frozen=True, slots=True)
class FrameSegment:
    """One human-executable instruction slot with its feasible allocation box."""

    index: int
    start_progress_m: float
    end_progress_m: float
    profile: DeploymentProfile
    speed_mps: float
    duration_s: float
    execution_window_s: float
    lap_index: int
    regulatory_ceiling_w: float
    derated_ceiling_w: float
    max_deploy_j: float
    max_harvest_j: float
    beta: float
    """``v / (k_drag * L)``: converts net propulsive joules into ``v^3`` units."""

    @property
    def length_m(self) -> float:
        return self.end_progress_m - self.start_progress_m


@dataclass(frozen=True, slots=True)
class PlanFrame:
    """The corridor, its instruction slots and every scalar the solver needs."""

    segments: tuple[FrameSegment, ...]
    start_progress_m: float
    end_progress_m: float
    lead_time_s: float
    horizon_s: float
    speed_mps: float

    initial_energy_j: float
    energy_floor_j: float
    energy_ceiling_j: float
    terminal_target_energy_j: float | None

    charge_efficiency: float
    recharge_allowance_per_lap_j: float | None
    recharge_used_this_lap_j: float

    max_power_ramp_w_per_s: float | None
    current_power_w: float

    min_speed_mps: float
    drivetrain_efficiency: float
    harvest_opportunity_coefficient: float

    continuation_availability: float
    """``0`` at the true finish, ``1`` while the remaining race is long. Multiplies
    the analytic continuation value so unused energy is never rewarded at the flag."""

    checkpoint_progress_m: tuple[tuple[str, float], ...]

    @property
    def baseline_time_s(self) -> float:
        """Corridor traversal time at the held speed with no extra deployment."""
        return sum(segment.duration_s for segment in self.segments)

    @property
    def lap_indices(self) -> tuple[int, ...]:
        return tuple(sorted({segment.lap_index for segment in self.segments}))


def held_speed_profile(estimate: StateEstimate) -> SpeedProfile:
    """A single-sample step profile: the checker's exact-integration case."""
    speed = estimate.own_car.speed_mps.value
    if speed is None or speed <= 0.0:
        raise ValueError("a plan frame needs a positive observed speed")
    progress = estimate.own_car.progress_m.value or 0.0
    return SpeedProfile(samples=(SpeedSample(progress_m=progress, speed_mps=float(speed)),), step=True)


def _regulatory_ceiling_w(manifest: RuleManifest, context: RuleContext, speed_mps: float) -> float:
    """``min(absolute ceiling, applicable speed curve)`` — the checker's model."""
    curve = manifest.curve(context.active_curve_id) if context.active_curve_id else None
    if curve is None:
        return manifest.absolute_power_ceiling_w
    return min(manifest.absolute_power_ceiling_w, curve.ceiling_w(speed_mps))


def _boundaries(
    manifest: RuleManifest,
    start_m: float,
    end_m: float,
    track_length_m: float,
    split_m: float | None,
) -> list[float]:
    points: set[float] = {start_m, end_m}
    if split_m is not None and start_m < split_m < end_m:
        points.add(split_m)
    first_lap = int(start_m // track_length_m)
    last_lap = int(end_m // track_length_m)
    for lap in range(first_lap, last_lap + 2):
        boundary = lap * track_length_m
        if start_m < boundary < end_m:
            points.add(boundary)
        for line in manifest.detection_lines:
            if line.kind not in ("activation", "checkpoint"):
                continue
            progress = lap * track_length_m + line.s_m
            if start_m < progress < end_m:
                points.add(progress)
    return sorted(points)


def _thin(points: list[float], minimum_length_m: float, maximum_segments: int) -> list[float]:
    """Drop boundaries that would create an instruction too short to execute.

    Interior points are removed in ascending order of the gap they create, so the
    surviving structure keeps the widest — and therefore most operationally
    meaningful — divisions.
    """
    kept = [points[0]]
    for point in points[1:-1]:
        if point - kept[-1] >= minimum_length_m and points[-1] - point >= minimum_length_m:
            kept.append(point)
    kept.append(points[-1])
    while len(kept) - 1 > maximum_segments:
        gaps = [(kept[i + 1] - kept[i - 1], i) for i in range(1, len(kept) - 1)]
        if not gaps:
            break
        _, index = min(gaps)
        kept.pop(index)
    return kept


def build_frame(
    estimate: StateEstimate,
    context: RuleContext,
    manifest: RuleManifest,
    config: PlannerConfig,
    profiles: tuple[DeploymentProfile, ...],
    *,
    track_length_m: float | None = None,
    terminal_target_energy_j: float | None = None,
    checkpoint_ids: tuple[str, ...] = (),
) -> PlanFrame:
    """Build the corridor for one tactical intention.

    ``profiles`` holds one or two driver-selectable profiles: the first applies
    inside the activation zone (or the first half of the corridor when the pack
    declares no activation line), the second after it.

    Raises ``ValueError`` when the corridor cannot be executed — a missing speed,
    a lead time shorter than the driver's reaction time, or an instruction window
    that no human could act inside. The enumerator turns that into a suppressed
    candidate with a reason code rather than a downgraded one.
    """
    if not profiles:
        raise ValueError("a frame needs at least one profile")
    own = estimate.own_car
    speed = own.speed_mps.value
    if speed is None or speed <= 0.0:
        raise ValueError("the estimate carries no usable speed")
    energy = own.battery_energy_j.value
    if energy is None:
        raise ValueError("the estimate carries no usable battery energy")

    execution = config.execution
    reaction_s = float(execution.driver_reaction_time_s.value)
    lead_s = float(execution.instruction_lead_time_s.value)
    if lead_s < reaction_s:
        raise ValueError(
            f"instruction lead time {lead_s} s is shorter than the driver reaction time {reaction_s} s"
        )

    length_m = float(track_length_m or estimate.race_context.track_length_m)
    progress0 = float(own.progress_m.value or 0.0)
    start_m = progress0 + float(speed) * lead_s
    horizon_s = float(config.horizon.detailed_horizon_s.value)
    end_m = start_m + float(speed) * horizon_s

    activation = [line for line in manifest.detection_lines if line.kind == "activation"]
    checkpoints = sorted(line.s_m for line in manifest.detection_lines if line.kind == "checkpoint")
    split_m: float | None = None
    if len(profiles) > 1:
        if activation:
            lap = int(start_m // length_m)
            following = [c for c in checkpoints if c > activation[0].s_m]
            zone_end_s_m = following[0] if following else length_m
            for candidate_lap in (lap, lap + 1):
                candidate = candidate_lap * length_m + zone_end_s_m
                if start_m < candidate < end_m:
                    split_m = candidate
                    break
        if split_m is None:
            split_m = 0.5 * (start_m + end_m)

    points = _thin(
        _boundaries(manifest, start_m, end_m, length_m, split_m),
        float(config.horizon.min_segment_length_m.value),
        config.horizon.max_segments,
    )
    if len(points) < 2:
        raise ValueError("the corridor is too short to hold a single executable instruction")

    surrogate = config.surrogate
    drag = surrogate.drag_constant_kg_per_m
    derate = context.applicable_limits.thermal_derate_factor
    if derate is None:
        raise ValueError("the thermal derate factor is unresolved; no ceiling can be computed")
    ceiling_w = _regulatory_ceiling_w(manifest, context, float(speed))
    window_s = float(execution.instruction_execution_window_s.value)
    charge_efficiency = float(surrogate.charge_efficiency.value)
    regen = float(surrogate.regen_availability.value)
    harvest_power_w = float(surrogate.max_harvest_power_w.value)

    segments: list[FrameSegment] = []
    for index in range(len(points) - 1):
        a, b = points[index], points[index + 1]
        profile = profiles[0] if split_m is None or b <= split_m + 1e-9 else profiles[-1]
        duration = (b - a) / float(speed)
        execution_window = min(duration, window_s)
        if execution_window < reaction_s:
            raise ValueError(
                f"segment {index} offers a {execution_window:.3f} s execution window against a "
                f"{reaction_s:.3f} s driver reaction time"
            )
        headroom = 1.0 - SOLVER_HEADROOM
        deploy_cap = min(derate, DEPLOY_FRACTION[profile]) * ceiling_w * duration * headroom
        harvest_cap = (
            HARVEST_FRACTION[profile] * regen * harvest_power_w * duration * charge_efficiency * headroom
        )
        segments.append(
            FrameSegment(
                index=index,
                start_progress_m=a,
                end_progress_m=b,
                profile=profile,
                speed_mps=float(speed),
                duration_s=duration,
                execution_window_s=execution_window,
                lap_index=int(a // length_m),
                regulatory_ceiling_w=ceiling_w,
                derated_ceiling_w=ceiling_w * derate,
                max_deploy_j=max(0.0, deploy_cap),
                max_harvest_j=max(0.0, harvest_cap),
                beta=float(speed) / (drag * (b - a)),
            )
        )

    limits = context.applicable_limits
    floor_j = limits.battery_energy_min_j
    cap_j = limits.battery_energy_max_j
    if floor_j is None:
        floor_j = manifest.battery_energy_min_j
    if cap_j is None:
        cap_j = manifest.battery_energy_max_j

    remaining_m = estimate.race_context.remaining_distance_m.value
    scale_m = float(config.horizon.continuation_distance_scale_m.value)
    availability = 1.0 if remaining_m is None else max(0.0, min(1.0, float(remaining_m) / scale_m))

    used_lap = own.recharge_spent_this_lap_j.value
    checkpoint_progress = tuple(
        (
            line.line_id,
            (int(start_m // length_m) + (1 if line.s_m < start_m % length_m else 0)) * length_m + line.s_m,
        )
        for line in manifest.detection_lines
        if line.kind == "checkpoint" and (not checkpoint_ids or line.line_id in checkpoint_ids)
    )

    return PlanFrame(
        segments=tuple(segments),
        start_progress_m=start_m,
        end_progress_m=points[-1],
        lead_time_s=lead_s,
        horizon_s=(points[-1] - start_m) / float(speed),
        speed_mps=float(speed),
        initial_energy_j=float(energy),
        energy_floor_j=float(floor_j),
        energy_ceiling_j=float(cap_j),
        terminal_target_energy_j=terminal_target_energy_j,
        charge_efficiency=charge_efficiency,
        recharge_allowance_per_lap_j=manifest.recharge_allowance_per_lap_j,
        recharge_used_this_lap_j=0.0 if used_lap is None else float(used_lap),
        max_power_ramp_w_per_s=limits.max_power_ramp_w_per_s or manifest.max_power_ramp_w_per_s,
        current_power_w=float(own.electrical_power_w.value or 0.0),
        min_speed_mps=float(surrogate.min_speed_mps.value),
        drivetrain_efficiency=float(surrogate.drivetrain_efficiency.value),
        harvest_opportunity_coefficient=float(surrogate.harvest_opportunity_coefficient.value),
        continuation_availability=availability,
        checkpoint_progress_m=checkpoint_progress,
    )


def to_profile_segments(
    frame: PlanFrame,
    deploy_j: tuple[float, ...],
    harvest_j: tuple[float, ...],
) -> tuple[ProfileSegment, ...]:
    """Turn an allocation into the frozen contract instructions.

    ``requested_budget_j`` is energy leaving the battery and ``harvest_target_j``
    is battery energy gain, exactly as ``handoffs/decisions.md`` D-01 defines
    them. Neither is a bus figure.

    Budgets are rounded to whole joules. A solver residual of a few millijoules
    is not an instruction, and publishing one would suggest a precision the
    reduced model does not have. The rounding is far inside ``SOLVER_HEADROOM``,
    so it cannot push a budget through a bound.
    """
    if len(deploy_j) != len(frame.segments) or len(harvest_j) != len(frame.segments):
        raise ValueError("one deploy and one harvest allocation is needed per frame segment")
    return tuple(
        ProfileSegment(
            start_progress_m=segment.start_progress_m,
            end_progress_m=segment.end_progress_m,
            profile_id=segment.profile,
            requested_budget_j=float(round(max(0.0, deploy_j[segment.index]))),
            harvest_target_j=float(round(max(0.0, harvest_j[segment.index]))),
            execution_window_s=segment.execution_window_s,
        )
        for segment in frame.segments
    )


def checker_state_for(
    estimate: StateEstimate,
    config: PlannerConfig,
    *,
    track_length_m: float | None = None,
    speed_profile: SpeedProfile | None = None,
) -> CheckerState:
    """Build the state the independent checker reintegrates from.

    ``speed_profile`` is the caller's best speed forecast along the corridor.
    When it is omitted the planner falls back to holding the observed speed,
    which is the *same* simplification the frame makes — so the checker then
    agrees with the planner about speed and disagrees only about the rules. A
    caller with a real forecast should supply it: that is precisely the case in
    which an independently rechecked plan can be rejected after the solver
    converged.
    """
    own = estimate.own_car
    energy = own.battery_energy_j.value
    if energy is None:
        raise ValueError("the checker state needs a known battery energy")
    used_lap = own.recharge_spent_this_lap_j.value
    return CheckerState(
        session_time_s=estimate.cutoff_s,
        progress_m=float(own.progress_m.value or 0.0),
        battery_energy_j=float(energy),
        speed_profile=speed_profile or held_speed_profile(estimate),
        track_length_m=float(track_length_m or estimate.race_context.track_length_m),
        current_power_w=float(own.electrical_power_w.value or 0.0),
        recharge_used_this_lap_j=0.0 if used_lap is None else float(used_lap),
        driver_reaction_time_s=float(config.execution.driver_reaction_time_s.value),
        charge_bus_efficiency=float(config.surrogate.charge_efficiency.value),
        discharge_efficiency=1.0,
    )
