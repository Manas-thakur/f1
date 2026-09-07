"""Regulatory context, coverage declaration and independent check results.

The checker reports ``pass``/``fail``/``unknown``. ``unknown`` is a first-class
outcome: a missing applicable condition suppresses advice rather than defaulting
to permission.
"""

from __future__ import annotations

from itertools import pairwise

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import CheckStatus, CoverageStatus, DeploymentProfile, EligibilityState, FlagState


class RuleReference(Contract):
    """Provenance of one machine-implemented regulatory statement."""

    article: str = Field(min_length=1, description="e.g. 'C5.2.7'.")
    source_id: str = Field(min_length=1, description="Source register ID, e.g. 'R02'.")
    source_url: str | None = None
    published_date: str | None = None
    effective_date: str | None = None
    reviewer: str | None = None
    note: str | None = None


class CoverageEntry(Contract):
    """One row of the regulatory coverage matrix."""

    concern: str = Field(min_length=1)
    status: CoverageStatus
    references: tuple[RuleReference, ...] = ()
    test_ids: tuple[str, ...] = ()
    note: str | None = None


class PowerCurvePoint(Contract):
    """One breakpoint of a speed-dependent power ceiling."""

    speed_mps: float = Field(ge=0.0)
    max_power_w: float = Field(ge=0.0)


class PowerCurve(Contract):
    """Piecewise-linear ceiling evaluated at a declared measurement bus."""

    curve_id: str = Field(min_length=1)
    measurement_bus: str = Field(
        min_length=1, description="Where the limit applies, e.g. 'ers_k_dc' — never mixed with battery gain."
    )
    points: tuple[PowerCurvePoint, ...] = Field(min_length=2)
    applies_to_profiles: tuple[DeploymentProfile, ...] = ()
    sector_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _monotonic_speed(self) -> PowerCurve:
        speeds = [p.speed_mps for p in self.points]
        if speeds != sorted(speeds) or len(set(speeds)) != len(speeds):
            raise ValueError("power curve breakpoints must have strictly increasing speed")
        return self

    def ceiling_w(self, speed_mps: float) -> float:
        """Linear interpolation with flat extrapolation at both ends."""
        pts = self.points
        if speed_mps <= pts[0].speed_mps:
            return pts[0].max_power_w
        if speed_mps >= pts[-1].speed_mps:
            return pts[-1].max_power_w
        for low, high in pairwise(pts):
            if low.speed_mps <= speed_mps <= high.speed_mps:
                span = high.speed_mps - low.speed_mps
                frac = 0.0 if span == 0.0 else (speed_mps - low.speed_mps) / span
                return low.max_power_w + frac * (high.max_power_w - low.max_power_w)
        return pts[-1].max_power_w


class DetectionLine(Contract):
    """Track location where eligibility is observed or a permission activates."""

    line_id: str = Field(min_length=1)
    kind: str = Field(pattern="^(detection|activation|checkpoint|timing)$")
    s_m: float = Field(ge=0.0, description="Distance along the centreline within one lap.")


class RuleManifest(VersionedContract):
    """An immutable, reviewed rule pack.

    A synthetic pack must set ``synthetic=True``; it can never masquerade as a
    real Grand Prix pack.
    """

    ruleset_id: str = Field(min_length=1)
    season_revision: str = Field(min_length=1)
    event_pack_id: str | None = None
    synthetic: bool
    reviewed: bool = False
    references: tuple[RuleReference, ...] = ()
    coverage: tuple[CoverageEntry, ...] = ()

    absolute_power_ceiling_w: float = Field(gt=0.0)
    power_curves: tuple[PowerCurve, ...] = ()
    battery_energy_min_j: float = Field(ge=0.0)
    battery_energy_max_j: float = Field(gt=0.0)
    recharge_allowance_per_lap_j: float | None = Field(default=None, ge=0.0)
    recharge_measurement_bus: str = Field(default="cu_k_dc", min_length=1)
    max_power_ramp_w_per_s: float | None = Field(default=None, gt=0.0)
    overtake_profile_extra_power_w: float | None = Field(default=None, ge=0.0)
    detection_lines: tuple[DetectionLine, ...] = ()
    unknown_conditions: tuple[str, ...] = Field(
        default=(),
        description="Referenced conditions that could not be resolved; they force unknown results.",
    )

    @model_validator(mode="after")
    def _consistent_bounds(self) -> RuleManifest:
        if self.battery_energy_min_j >= self.battery_energy_max_j:
            raise ValueError("battery energy window is empty")
        if not self.synthetic and not self.reviewed:
            raise ValueError("a non-synthetic rule pack must be marked reviewed before use")
        return self

    def curve(self, curve_id: str) -> PowerCurve | None:
        for c in self.power_curves:
            if c.curve_id == curve_id:
                return c
        return None

    @property
    def has_unknown_conditions(self) -> bool:
        return len(self.unknown_conditions) > 0


class ApplicableLimits(Contract):
    """Resolved numeric limits for the current position and state."""

    deployment_ceiling_w: float | None = None
    recovery_ceiling_w: float | None = None
    battery_energy_min_j: float | None = None
    battery_energy_max_j: float | None = None
    recharge_allowance_remaining_j: float | None = None
    max_power_ramp_w_per_s: float | None = None
    thermal_derate_factor: float | None = Field(default=None, ge=0.0, le=1.0)


class RuleContext(VersionedContract):
    """Resolved regulatory state at one progress point and session time."""

    session_id: str = Field(min_length=1)
    season_revision: str = Field(min_length=1)
    ruleset_hash: str = Field(min_length=1)
    event_pack_hash: str | None = None
    resolved_at_s: float = Field(ge=0.0)
    progress_m: float = Field(ge=0.0)
    current_flags: tuple[FlagState, ...] = (FlagState.UNKNOWN,)
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    eligibility_observed_at_s: float | None = None
    active_curve_id: str | None = None
    applicable_limits: ApplicableLimits = ApplicableLimits()
    admissible_profiles: tuple[DeploymentProfile, ...] = ()
    unknown_conditions: tuple[str, ...] = ()
    coverage: tuple[CoverageEntry, ...] = ()

    @property
    def has_unknown_critical_condition(self) -> bool:
        return len(self.unknown_conditions) > 0

    def permits(self, profile: DeploymentProfile) -> bool:
        return profile in self.admissible_profiles


class ConstraintCheck(Contract):
    """One independently calculated check with its margin."""

    check_id: str = Field(min_length=1)
    status: CheckStatus
    margin: float | None = Field(
        default=None,
        description="Signed slack in the check's own unit; positive is feasible. None when unknown.",
    )
    unit: str | None = None
    limit: float | None = None
    observed: float | None = None
    at_progress_m: float | None = None
    at_session_time_s: float | None = None
    references: tuple[RuleReference, ...] = ()
    detail: str | None = None

    @model_validator(mode="after")
    def _unknown_has_no_false_margin(self) -> ConstraintCheck:
        if self.status is CheckStatus.UNKNOWN and self.margin is not None:
            raise ValueError("an unknown check cannot report a numeric margin")
        return self


class ConstraintResult(VersionedContract):
    """Aggregate verdict for one plan, computed by the independent checker."""

    status: CheckStatus
    checks: tuple[ConstraintCheck, ...] = ()
    ruleset_hash: str = Field(min_length=1)
    checked_at_s: float = Field(ge=0.0)
    checker_version: str = Field(min_length=1)
    unresolved_conditions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _aggregate_matches_worst_check(self) -> ConstraintResult:
        if not self.checks:
            return self
        statuses = {c.status for c in self.checks}
        expected = (
            CheckStatus.FAIL
            if CheckStatus.FAIL in statuses
            else CheckStatus.UNKNOWN
            if CheckStatus.UNKNOWN in statuses
            else CheckStatus.PASS
        )
        if self.status is not expected:
            raise ValueError(
                f"aggregate status {self.status} disagrees with worst individual check {expected}"
            )
        return self

    @property
    def margins(self) -> dict[str, float]:
        return {c.check_id: c.margin for c in self.checks if c.margin is not None}

    @property
    def failed_checks(self) -> tuple[ConstraintCheck, ...]:
        return tuple(c for c in self.checks if c.status is CheckStatus.FAIL)


__all__ = [
    "ApplicableLimits",
    "ConstraintCheck",
    "ConstraintResult",
    "CoverageEntry",
    "DetectionLine",
    "PowerCurve",
    "PowerCurvePoint",
    "RuleContext",
    "RuleManifest",
    "RuleReference",
]
