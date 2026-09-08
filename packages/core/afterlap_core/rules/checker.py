"""The independent constraint checker.

This module deliberately does **not** consume the planner's own integration
result. It reintegrates the accepted power and the energy ledgers along every
proposed :class:`~afterlap_contracts.planning.ProfileSegment` from the car
state and the immutable rule pack, subdividing at

* profile-segment boundaries,
* speed-profile breakpoints,
* power-curve breakpoint crossings,
* lap rollovers (only lap-scoped ledgers reset there),
* detection/activation/checkpoint lines,

and it evaluates every check at interior points, not only at the first and last
state. A converged solver output that dips below the energy floor halfway
through a segment and recovers by the end is therefore rejected.

The reintegration model is stated here so that it can be audited and argued
with, rather than hidden inside the numbers:

* deployment power follows the shape of the applicable ceiling,
  ``P_dep(s) = k_d * C_reg(v(s))``, with ``k_d`` fixed per segment so that the
  time integral of ``P_dep`` equals the segment's ``requested_budget_j``
  measured at the deployment bus;
* battery-gain harvest follows speed, ``P_har(s) = k_h * v(s)``, with ``k_h``
  fixed per segment so the time integral equals ``harvest_target_j``;
* the charge-bus ledger is the battery gain divided by
  ``CheckerState.charge_bus_efficiency`` — the recharge allowance is a
  **charge-bus** figure and is never compared against a battery-gain figure;
* battery drain is ``P_dep`` divided by ``CheckerState.discharge_efficiency``.
  ``requested_budget_j`` is battery-side (decisions.md D-01), so it is scaled
  *by* that efficiency when deriving bus power and divided by it again here;
  the two conversions cancel and the ledger integrates the requested battery
  energy exactly.

``unknown`` is a first-class outcome and always carries ``margin=None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from afterlap_contracts import (
    SCHEMA_VERSION,
    CandidatePlan,
    CheckStatus,
    ConstraintCheck,
    ConstraintResult,
    DeploymentProfile,
    EligibilityState,
    PowerCurve,
    ProfileSegment,
    RuleContext,
    RuleManifest,
)

from .packs import references_for_article
from .state import CheckerState

__all__ = [
    "CHECKER_VERSION",
    "CHECK_ARTICLES",
    "CheckerConfig",
    "PlanTrace",
    "TracePoint",
    "build_trace",
    "check_plan",
]

CHECKER_VERSION = "afterlap-rules-checker-1"

CHECK_ARTICLES: dict[str, tuple[str, ...]] = {
    "power_ceiling": ("C5.2.7", "C5.2.8"),
    "battery_energy_window": ("C5.2.9",),
    "recharge_allowance": ("C5.2.10",),
    "power_ramp": ("C5.12",),
    "thermal_derate": ("synthetic-thermal-derate",),
    "overtake_eligibility": ("B7.2",),
    "execution_lead_time": (),
}
"""Which article family justifies each check. An empty tuple means the check is
an operational constraint of this product, not a transcribed FIA article."""


@dataclass(frozen=True, slots=True)
class CheckerConfig:
    """Numerical settings for the reintegration. All tolerances are absolute."""

    substeps_per_interval: int = 8
    power_tolerance_w: float = 1e-6
    energy_tolerance_j: float = 1e-6
    ramp_tolerance_w_per_s: float = 1e-6
    time_tolerance_s: float = 1e-9
    distance_tolerance_m: float = 1e-9

    def __post_init__(self) -> None:
        if self.substeps_per_interval < 1:
            raise ValueError("substeps_per_interval must be at least 1")


@dataclass(frozen=True, slots=True)
class _CeilingModel:
    """Regulatory and derated ceilings as functions of speed, at the deployment bus."""

    absolute_w: float
    curve: PowerCurve | None
    derate_factor: float | None
    measurement_bus: str

    def regulatory_w(self, speed_mps: float) -> float:
        if self.curve is None:
            return self.absolute_w
        return min(self.absolute_w, self.curve.ceiling_w(speed_mps))

    def derated_w(self, speed_mps: float) -> float | None:
        if self.derate_factor is None:
            return None
        return self.regulatory_w(speed_mps) * self.derate_factor

    def breakpoint_speeds(self) -> tuple[float, ...]:
        return () if self.curve is None else tuple(p.speed_mps for p in self.curve.points)


@dataclass(frozen=True, slots=True)
class TracePoint:
    """One reintegrated state. Points exist at every subdivision boundary."""

    progress_m: float
    session_time_s: float
    speed_mps: float
    segment_index: int
    profile: DeploymentProfile
    deploy_power_w: float
    harvest_power_w: float
    bus_recharge_power_w: float
    regulatory_ceiling_w: float
    derated_ceiling_w: float | None
    battery_energy_j: float
    recharge_ledger_j: float
    lap_index: int


@dataclass(frozen=True, slots=True)
class _Slice:
    start_m: float
    end_m: float
    speed_start_mps: float
    speed_end_mps: float
    duration_s: float


@dataclass(frozen=True, slots=True)
class PlanTrace:
    """The checker's own reintegration of one plan."""

    points: tuple[TracePoint, ...]
    lead_time_s: float
    start_time_s: float
    end_time_s: float
    segment_deploy_scale: tuple[float, ...]
    segment_harvest_scale: tuple[float, ...]
    segment_duration_s: tuple[float, ...]
    ceiling: _CeilingModel = field(repr=False)

    def points_of_segment(self, index: int) -> tuple[TracePoint, ...]:
        return tuple(p for p in self.points if p.segment_index == index)


# ---------------------------------------------------------------------------
# grid construction
# ---------------------------------------------------------------------------


def _segment_edges(
    segment: ProfileSegment,
    state: CheckerState,
    manifest: RuleManifest | None,
    ceiling: _CeilingModel,
    config: CheckerConfig,
) -> tuple[float, ...]:
    start, end = segment.start_progress_m, segment.end_progress_m
    edges: set[float] = {start, end}
    edges.update(state.speed_profile.breakpoints_within(start, end))
    edges.update(state.lap_boundaries_within(start, end))
    if manifest is not None:
        first_lap = state.lap_index_at(start)
        last_lap = state.lap_index_at(end)
        for lap in range(first_lap, last_lap + 1):
            for line in manifest.detection_lines:
                progress = lap * state.track_length_m + line.s_m
                if start < progress < end:
                    edges.add(progress)
    # Power-curve breakpoint crossings: the ceiling changes slope there, so the
    # deployment power does too and an extremum can sit exactly on one.
    for a, b, va, vb in state.speed_profile.sub_intervals(start, end):
        if va == vb:
            continue
        low, high = (va, vb) if va < vb else (vb, va)
        for speed in ceiling.breakpoint_speeds():
            if low < speed < high:
                progress = a + (speed - va) / (vb - va) * (b - a)
                if start < progress < end:
                    edges.add(progress)
    ordered = sorted(edges)
    return tuple(
        point
        for index, point in enumerate(ordered)
        if index == 0 or point - ordered[index - 1] > config.distance_tolerance_m
    )


def _slices_for(
    segment: ProfileSegment,
    state: CheckerState,
    manifest: RuleManifest | None,
    ceiling: _CeilingModel,
    config: CheckerConfig,
) -> tuple[_Slice, ...]:
    edges = _segment_edges(segment, state, manifest, ceiling, config)
    profile = state.speed_profile
    slices: list[_Slice] = []
    for a, b in pairwise(edges):
        if profile.step:
            held = profile.speed_at(0.5 * (a + b))
            va, vb = held, held
        else:
            va, vb = profile.speed_at(a), profile.speed_at(b)
        width = (b - a) / config.substeps_per_interval
        for index in range(config.substeps_per_interval):
            sa = a + index * width
            sb = b if index == config.substeps_per_interval - 1 else sa + width
            fa = (sa - a) / (b - a)
            fb = (sb - a) / (b - a)
            speed_a = va + fa * (vb - va)
            speed_b = va + fb * (vb - va)
            duration = (sb - sa) / (0.5 * (speed_a + speed_b))
            slices.append(_Slice(sa, sb, speed_a, speed_b, duration))
    return tuple(slices)


def _ceiling_model(context: RuleContext, manifest: RuleManifest | None) -> _CeilingModel:
    derate = context.applicable_limits.thermal_derate_factor
    if manifest is not None:
        curve = manifest.curve(context.active_curve_id) if context.active_curve_id else None
        return _CeilingModel(
            absolute_w=manifest.absolute_power_ceiling_w,
            curve=curve,
            derate_factor=derate,
            measurement_bus=curve.measurement_bus if curve else "ers_k_dc",
        )
    # Degraded mode: without the pack the checker can only use the single
    # resolved scalar the context carries, and it says so in the check detail.
    derated = context.applicable_limits.deployment_ceiling_w
    if derated is None:
        return _CeilingModel(absolute_w=0.0, curve=None, derate_factor=None, measurement_bus="unknown")
    regulatory = derated if not derate else derated / derate
    return _CeilingModel(absolute_w=regulatory, curve=None, derate_factor=derate, measurement_bus="unknown")


@dataclass(frozen=True, slots=True)
class _SegmentModel:
    """The per-segment scale factors the checker derived for itself."""

    index: int
    segment: ProfileSegment
    slices: tuple[_Slice, ...]
    duration_s: float
    deploy_scale: float
    harvest_scale: float
    uniform_deploy_w: float

    def deploy_w(self, ceiling: _CeilingModel, speed_mps: float) -> float:
        if self.deploy_scale == float("inf"):
            return self.uniform_deploy_w
        return self.deploy_scale * ceiling.regulatory_w(speed_mps)

    def harvest_w(self, speed_mps: float) -> float:
        return self.harvest_scale * speed_mps


def _segment_model(
    index: int,
    segment: ProfileSegment,
    state: CheckerState,
    manifest: RuleManifest | None,
    ceiling: _CeilingModel,
    config: CheckerConfig,
) -> _SegmentModel:
    slices = _slices_for(segment, state, manifest, ceiling, config)
    ceiling_integral = sum(
        0.5 * (ceiling.regulatory_w(s.speed_start_mps) + ceiling.regulatory_w(s.speed_end_mps)) * s.duration_s
        for s in slices
    )
    speed_integral = sum(0.5 * (s.speed_start_mps + s.speed_end_mps) * s.duration_s for s in slices)
    duration = sum(s.duration_s for s in slices)
    if segment.requested_budget_j == 0.0:
        deploy_scale = 0.0
    elif ceiling_integral > 0.0:
        # ``requested_budget_j`` is energy leaving the BATTERY (decisions.md D-01),
        # while ``ceiling_integral`` is bus headroom. Scale by the discharge
        # efficiency here so the resulting bus power is a genuine bus figure; the
        # later ledger step divides that bus power back by the same efficiency to
        # recover battery drain. Converting in only one of the two places drains
        # the modelled battery by 1/eta too much -- 5.3% at eta=0.95.
        deploy_scale = segment.requested_budget_j * state.discharge_efficiency / ceiling_integral
    else:
        # The ceiling is zero across the whole segment. Spread the request
        # uniformly in time so the ceiling check still fails on real numbers.
        deploy_scale = float("inf")
    harvest_scale = (
        0.0
        if segment.harvest_target_j == 0.0 or speed_integral <= 0.0
        else segment.harvest_target_j / speed_integral
    )
    # Uniform fallback is a bus figure too, for the same reason as deploy_scale.
    uniform = segment.requested_budget_j * state.discharge_efficiency / duration if duration > 0.0 else 0.0
    return _SegmentModel(
        index=index,
        segment=segment,
        slices=slices,
        duration_s=duration,
        deploy_scale=deploy_scale,
        harvest_scale=harvest_scale,
        uniform_deploy_w=uniform,
    )


def _trace_point(
    model: _SegmentModel,
    ceiling: _CeilingModel,
    state: CheckerState,
    progress_m: float,
    speed_mps: float,
    session_time_s: float,
    battery_energy_j: float,
    recharge_ledger_j: float,
) -> TracePoint:
    harvest = model.harvest_w(speed_mps)
    return TracePoint(
        progress_m=progress_m,
        session_time_s=session_time_s,
        speed_mps=speed_mps,
        segment_index=model.index,
        profile=model.segment.profile_id,
        deploy_power_w=model.deploy_w(ceiling, speed_mps),
        harvest_power_w=harvest,
        bus_recharge_power_w=harvest / state.charge_bus_efficiency,
        regulatory_ceiling_w=ceiling.regulatory_w(speed_mps),
        derated_ceiling_w=ceiling.derated_w(speed_mps),
        battery_energy_j=battery_energy_j,
        recharge_ledger_j=recharge_ledger_j,
        lap_index=state.lap_index_at(progress_m),
    )


def build_trace(
    plan: CandidatePlan,
    state: CheckerState,
    context: RuleContext,
    *,
    manifest: RuleManifest | None = None,
    config: CheckerConfig = CheckerConfig(),
) -> PlanTrace:
    """Reintegrate the plan independently of whatever produced it."""
    ceiling = _ceiling_model(context, manifest)
    plan_start = plan.profile_segments[0].start_progress_m

    if plan_start >= state.progress_m:
        lead_time_s = state.speed_profile.travel_time_s(state.progress_m, plan_start)
    else:
        lead_time_s = -state.speed_profile.travel_time_s(plan_start, state.progress_m)

    time_s = state.session_time_s + lead_time_s
    energy_j = state.battery_energy_j
    ledger_j = state.recharge_used_this_lap_j

    lap_boundaries: set[float] = set()
    for segment in plan.profile_segments:
        lap_boundaries.update(state.lap_boundaries_within(segment.start_progress_m, segment.end_progress_m))

    models = tuple(
        _segment_model(index, segment, state, manifest, ceiling, config)
        for index, segment in enumerate(plan.profile_segments)
    )

    points: list[TracePoint] = []
    for model in models:
        if not model.slices:
            continue
        first = model.slices[0]
        points.append(
            _trace_point(
                model, ceiling, state, first.start_m, first.speed_start_mps, time_s, energy_j, ledger_j
            )
        )
        for piece in model.slices:
            previous = points[-1]
            if (
                abs(previous.progress_m - piece.start_m) <= config.distance_tolerance_m
                and previous.speed_mps != piece.speed_start_mps
            ):
                # A step speed profile changes speed instantaneously here: no
                # time elapses, so the trapezoid must restart rather than
                # average across the discontinuity.
                previous = _trace_point(
                    model, ceiling, state, piece.start_m, piece.speed_start_mps, time_s, energy_j, ledger_j
                )
                points.append(previous)
            mean_deploy = 0.5 * (previous.deploy_power_w + model.deploy_w(ceiling, piece.speed_end_mps))
            mean_harvest = 0.5 * (previous.harvest_power_w + model.harvest_w(piece.speed_end_mps))
            energy_j += (mean_harvest - mean_deploy / state.discharge_efficiency) * piece.duration_s
            ledger_j += (mean_harvest / state.charge_bus_efficiency) * piece.duration_s
            time_s += piece.duration_s
            points.append(
                _trace_point(
                    model, ceiling, state, piece.end_m, piece.speed_end_mps, time_s, energy_j, ledger_j
                )
            )
            if any(abs(piece.end_m - edge) <= config.distance_tolerance_m for edge in lap_boundaries):
                ledger_j = 0.0

    return PlanTrace(
        points=tuple(points),
        lead_time_s=lead_time_s,
        start_time_s=state.session_time_s + lead_time_s,
        end_time_s=time_s,
        segment_deploy_scale=tuple(m.deploy_scale for m in models),
        segment_harvest_scale=tuple(m.harvest_scale for m in models),
        segment_duration_s=tuple(m.duration_s for m in models),
        ceiling=ceiling,
    )


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------


def _reference(check_id: str, manifest: RuleManifest | None):
    return references_for_article(manifest, CHECK_ARTICLES.get(check_id, ()))


def _check_power_ceiling(
    trace: PlanTrace, manifest: RuleManifest | None, config: CheckerConfig
) -> ConstraintCheck:
    worst = min(trace.points, key=lambda p: p.regulatory_ceiling_w - p.deploy_power_w)
    margin = worst.regulatory_ceiling_w - worst.deploy_power_w
    return ConstraintCheck(
        check_id="power_ceiling",
        status=CheckStatus.PASS if margin >= -config.power_tolerance_w else CheckStatus.FAIL,
        margin=margin,
        unit="W",
        limit=worst.regulatory_ceiling_w,
        observed=worst.deploy_power_w,
        at_progress_m=worst.progress_m,
        at_session_time_s=worst.session_time_s,
        references=_reference("power_ceiling", manifest),
        detail=(
            f"reintegrated deployment power at the {trace.ceiling.measurement_bus} bus against "
            f"min(absolute ceiling, speed curve) at {worst.speed_mps:.3f} m/s"
        ),
    )


def _check_battery_window(
    trace: PlanTrace, context: RuleContext, manifest: RuleManifest | None, config: CheckerConfig
) -> ConstraintCheck:
    limits = context.applicable_limits
    floor = limits.battery_energy_min_j
    ceiling = limits.battery_energy_max_j
    if floor is None and manifest is not None:
        floor = manifest.battery_energy_min_j
    if ceiling is None and manifest is not None:
        ceiling = manifest.battery_energy_max_j
    if floor is None or ceiling is None:
        return ConstraintCheck(
            check_id="battery_energy_window",
            status=CheckStatus.UNKNOWN,
            unit="J",
            references=_reference("battery_energy_window", manifest),
            detail="the loaded pack does not resolve the battery operating window",
        )
    lowest = min(trace.points, key=lambda p: p.battery_energy_j)
    highest = max(trace.points, key=lambda p: p.battery_energy_j)
    floor_margin = lowest.battery_energy_j - floor
    ceiling_margin = ceiling - highest.battery_energy_j
    if floor_margin <= ceiling_margin:
        margin, at, limit, observed = floor_margin, lowest, floor, lowest.battery_energy_j
        detail = "interior minimum of the reintegrated battery trajectory against the operating floor"
    else:
        margin, at, limit, observed = ceiling_margin, highest, ceiling, highest.battery_energy_j
        detail = "interior maximum of the reintegrated battery trajectory against the operating ceiling"
    return ConstraintCheck(
        check_id="battery_energy_window",
        status=CheckStatus.PASS if margin >= -config.energy_tolerance_j else CheckStatus.FAIL,
        margin=margin,
        unit="J",
        limit=limit,
        observed=observed,
        at_progress_m=at.progress_m,
        at_session_time_s=at.session_time_s,
        references=_reference("battery_energy_window", manifest),
        detail=detail,
    )


def _check_recharge_allowance(
    trace: PlanTrace,
    state: CheckerState,
    context: RuleContext,
    manifest: RuleManifest | None,
    config: CheckerConfig,
) -> ConstraintCheck:
    allowance: float | None = None
    bus = "cu_k_dc"
    if manifest is not None:
        allowance = manifest.recharge_allowance_per_lap_j
        bus = manifest.recharge_measurement_bus
    elif context.applicable_limits.recharge_allowance_remaining_j is not None:
        allowance = context.applicable_limits.recharge_allowance_remaining_j + state.recharge_used_this_lap_j
    if allowance is None:
        return ConstraintCheck(
            check_id="recharge_allowance",
            status=CheckStatus.UNKNOWN,
            unit="J",
            references=_reference("recharge_allowance", manifest),
            detail="the loaded pack declares no per-lap recharge allowance",
        )
    worst = max(trace.points, key=lambda p: p.recharge_ledger_j)
    margin = allowance - worst.recharge_ledger_j
    return ConstraintCheck(
        check_id="recharge_allowance",
        status=CheckStatus.PASS if margin >= -config.energy_tolerance_j else CheckStatus.FAIL,
        margin=margin,
        unit="J",
        limit=allowance,
        observed=worst.recharge_ledger_j,
        at_progress_m=worst.progress_m,
        at_session_time_s=worst.session_time_s,
        references=_reference("recharge_allowance", manifest),
        detail=(
            f"cumulative per-lap ledger measured on the {bus} bus "
            f"(battery gain / charge_bus_efficiency={state.charge_bus_efficiency}); resets at a lap rollover"
        ),
    )


def _check_power_ramp(
    plan: CandidatePlan,
    trace: PlanTrace,
    state: CheckerState,
    context: RuleContext,
    manifest: RuleManifest | None,
    config: CheckerConfig,
) -> ConstraintCheck:
    limit = manifest.max_power_ramp_w_per_s if manifest else None
    if limit is None:
        limit = context.applicable_limits.max_power_ramp_w_per_s
    if limit is None:
        return ConstraintCheck(
            check_id="power_ramp",
            status=CheckStatus.UNKNOWN,
            unit="W/s",
            references=_reference("power_ramp", manifest),
            detail="the loaded pack declares no power-change limit",
        )

    transitions: list[tuple[float, float, TracePoint, str]] = []
    first = trace.points[0]
    transitions.append(
        (
            abs(first.deploy_power_w - state.current_power_w),
            plan.profile_segments[0].execution_window_s,
            first,
            "entry into the first segment",
        )
    )
    for index in range(len(plan.profile_segments) - 1):
        before = trace.points_of_segment(index)
        after = trace.points_of_segment(index + 1)
        if not before or not after:
            continue
        transitions.append(
            (
                abs(after[0].deploy_power_w - before[-1].deploy_power_w),
                plan.profile_segments[index + 1].execution_window_s,
                after[0],
                f"transition {plan.profile_segments[index].profile_id.value}"
                f" -> {plan.profile_segments[index + 1].profile_id.value}",
            )
        )

    worst_margin = float("inf")
    worst: tuple[float, float, TracePoint, str] | None = None
    for delta, window, point, label in transitions:
        rate = delta / window
        margin = limit - rate
        if margin < worst_margin:
            worst_margin, worst = margin, (rate, window, point, label)
    assert worst is not None
    rate, window, point, label = worst
    return ConstraintCheck(
        check_id="power_ramp",
        status=CheckStatus.PASS if worst_margin >= -config.ramp_tolerance_w_per_s else CheckStatus.FAIL,
        margin=worst_margin,
        unit="W/s",
        limit=limit,
        observed=rate,
        at_progress_m=point.progress_m,
        at_session_time_s=point.session_time_s,
        references=_reference("power_ramp", manifest),
        detail=f"{label}: demanded change over its {window} s execution window",
    )


def _check_thermal_derate(
    trace: PlanTrace, context: RuleContext, manifest: RuleManifest | None, config: CheckerConfig
) -> ConstraintCheck:
    factor = context.applicable_limits.thermal_derate_factor
    if factor is None:
        return ConstraintCheck(
            check_id="thermal_derate",
            status=CheckStatus.UNKNOWN,
            unit="W",
            references=_reference("thermal_derate", manifest),
            detail="the derate model is configured but no temperature was available",
        )
    candidates = [p for p in trace.points if p.derated_ceiling_w is not None]
    if not candidates:
        return ConstraintCheck(
            check_id="thermal_derate",
            status=CheckStatus.UNKNOWN,
            unit="W",
            references=_reference("thermal_derate", manifest),
            detail="no derated ceiling could be computed along the plan",
        )
    worst = min(candidates, key=lambda p: (p.derated_ceiling_w or 0.0) - p.deploy_power_w)
    limit = worst.derated_ceiling_w or 0.0
    margin = limit - worst.deploy_power_w
    return ConstraintCheck(
        check_id="thermal_derate",
        status=CheckStatus.PASS if margin >= -config.power_tolerance_w else CheckStatus.FAIL,
        margin=margin,
        unit="W",
        limit=limit,
        observed=worst.deploy_power_w,
        at_progress_m=worst.progress_m,
        at_session_time_s=worst.session_time_s,
        references=_reference("thermal_derate", manifest),
        detail=f"regulatory ceiling multiplied by the derate factor {factor}",
    )


def _overtake_zone(
    progress_m: float, state: CheckerState, manifest: RuleManifest
) -> tuple[float, float] | None:
    """The activation zone containing ``progress_m``, if the pack declares one."""
    activations = [line for line in manifest.detection_lines if line.kind == "activation"]
    checkpoints = sorted(line.s_m for line in manifest.detection_lines if line.kind == "checkpoint")
    if not activations:
        return None
    lap = state.lap_index_at(progress_m)
    for lap_index in (lap - 1, lap):
        if lap_index < 0:
            continue
        for activation in activations:
            start = lap_index * state.track_length_m + activation.s_m
            following = [c for c in checkpoints if c > activation.s_m]
            end = (
                lap_index * state.track_length_m + following[0]
                if following
                else (lap_index + 1) * state.track_length_m
            )
            if start <= progress_m <= end:
                return start, end
    return None


def _check_overtake_eligibility(
    plan: CandidatePlan,
    state: CheckerState,
    context: RuleContext,
    manifest: RuleManifest | None,
    config: CheckerConfig,
) -> ConstraintCheck:
    references = _reference("overtake_eligibility", manifest)
    if context.unknown_conditions:
        return ConstraintCheck(
            check_id="overtake_eligibility",
            status=CheckStatus.UNKNOWN,
            unit="m",
            references=references,
            detail=("unresolved applicable conditions: " + ", ".join(context.unknown_conditions)),
        )
    if context.eligibility is EligibilityState.UNKNOWN:
        return ConstraintCheck(
            check_id="overtake_eligibility",
            status=CheckStatus.UNKNOWN,
            unit="m",
            references=references,
            detail="the overtake permission state has not been resolved by a detection crossing",
        )
    overtake = [s for s in plan.profile_segments if s.profile_id is DeploymentProfile.OVERTAKE]
    if not overtake:
        return ConstraintCheck(
            check_id="overtake_eligibility",
            status=CheckStatus.PASS,
            unit="m",
            references=references,
            detail="the plan requests no overtake profile, so no permission is required",
        )
    if DeploymentProfile.OVERTAKE not in context.admissible_profiles:
        requested = sum(s.length_m for s in overtake)
        return ConstraintCheck(
            check_id="overtake_eligibility",
            status=CheckStatus.FAIL,
            margin=-requested,
            unit="m",
            limit=0.0,
            observed=requested,
            at_progress_m=overtake[0].start_progress_m,
            references=references,
            detail=(
                f"overtake profile is not admissible (eligibility={context.eligibility.value}, "
                f"flags={[f.value for f in context.current_flags]}); "
                f"{requested:.1f} m of the plan lie outside any permitted zone"
            ),
        )
    if manifest is None:
        return ConstraintCheck(
            check_id="overtake_eligibility",
            status=CheckStatus.PASS,
            unit="m",
            references=references,
            detail="permission granted; zone geometry unavailable without the rule pack",
        )
    worst_margin = float("inf")
    worst_segment = overtake[0]
    for segment in overtake:
        zone = _overtake_zone(segment.start_progress_m, state, manifest)
        margin = -segment.length_m if zone is None else zone[1] - segment.end_progress_m
        if margin < worst_margin:
            worst_margin, worst_segment = margin, segment
    return ConstraintCheck(
        check_id="overtake_eligibility",
        status=CheckStatus.PASS if worst_margin >= -config.distance_tolerance_m else CheckStatus.FAIL,
        margin=worst_margin,
        unit="m",
        limit=0.0,
        observed=worst_segment.end_progress_m,
        at_progress_m=worst_segment.end_progress_m,
        references=references,
        detail="metres of permitted activation zone remaining after the requested overtake use",
    )


def _check_execution_lead_time(
    plan: CandidatePlan,
    trace: PlanTrace,
    state: CheckerState,
    manifest: RuleManifest | None,
    config: CheckerConfig,
) -> ConstraintCheck:
    required = state.driver_reaction_time_s
    candidates: list[tuple[float, float, float, str]] = [
        (
            trace.lead_time_s - required,
            trace.lead_time_s,
            required,
            "time available before the first segment starts",
        )
    ]
    candidates.extend(
        (
            segment.execution_window_s - required,
            segment.execution_window_s,
            required,
            f"execution window of segment {index} ({segment.profile_id.value})",
        )
        for index, segment in enumerate(plan.profile_segments)
    )
    margin, observed, limit, label = min(candidates, key=lambda item: item[0])
    return ConstraintCheck(
        check_id="execution_lead_time",
        status=CheckStatus.PASS if margin >= -config.time_tolerance_s else CheckStatus.FAIL,
        margin=margin,
        unit="s",
        limit=limit,
        observed=observed,
        at_progress_m=plan.profile_segments[0].start_progress_m,
        at_session_time_s=trace.start_time_s,
        references=_reference("execution_lead_time", manifest),
        detail=f"{label}; driver reaction time {required} s",
    )


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def check_plan(
    plan: CandidatePlan,
    state: CheckerState,
    context: RuleContext,
    *,
    manifest: RuleManifest | None = None,
    config: CheckerConfig = CheckerConfig(),
) -> ConstraintResult:
    """Independently verify one candidate plan.

    ``manifest`` is the immutable pack the context was resolved from. It is
    optional only so that a caller holding just a context can still run a
    degraded check; supplying it enables the speed-curve, zone-geometry and
    allowance checks to use their own numbers rather than one resolved scalar.
    """
    trace = build_trace(plan, state, context, manifest=manifest, config=config)
    checks = (
        _check_power_ceiling(trace, manifest, config),
        _check_battery_window(trace, context, manifest, config),
        _check_recharge_allowance(trace, state, context, manifest, config),
        _check_power_ramp(plan, trace, state, context, manifest, config),
        _check_thermal_derate(trace, context, manifest, config),
        _check_overtake_eligibility(plan, state, context, manifest, config),
        _check_execution_lead_time(plan, trace, state, manifest, config),
    )
    statuses = {check.status for check in checks}
    aggregate = (
        CheckStatus.FAIL
        if CheckStatus.FAIL in statuses
        else CheckStatus.UNKNOWN
        if CheckStatus.UNKNOWN in statuses
        else CheckStatus.PASS
    )
    return ConstraintResult(
        schema_version=SCHEMA_VERSION,
        status=aggregate,
        checks=checks,
        ruleset_hash=context.ruleset_hash,
        checked_at_s=max(context.resolved_at_s, 0.0),
        checker_version=CHECKER_VERSION,
        # Report every condition the pack could not resolve, applicable or not.
        # Only the applicable ones drive the status; hiding the rest would let a
        # consumer read a PASS as complete coverage.
        unresolved_conditions=tuple(
            sorted(
                set(context.unknown_conditions)
                | set(manifest.unknown_conditions if manifest is not None else ())
            )
        ),
    )
