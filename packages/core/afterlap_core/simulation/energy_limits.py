"""Electrical deployment and recovery ceilings for one car at one instant.

``RACE_CONDITION_MODEL.md`` ("Energy deployment and regeneration") asks for

```text
P_ers_drive_dc    = commanded electrical drive power after applicable limits
P_ers_recharge_dc = recoverable braking power after motor, grip, battery and rule limits
```

This module is the single place those *limits* are assembled. The engine
asks :class:`ElectricalLimits` for a deployment ceiling and a harvest ceiling
and hands the answers to :class:`~.battery.EnergyLedger`, which remains the
only place battery energy changes. Nothing here moves energy.

Three sources feed a limit and every limit says which one bound it:

* ``car_document`` -- the car configuration (DC ceilings, regen share, the
  thermal derate ramp, optional charge-acceptance ramp).
* ``event_curve_confirmed`` -- the event Power Unit Information curve, but only
  when :func:`~afterlap_core.tracks.fia_overlay.overlay_effective_values`
  returns it, i.e. two distinct reviewers confirmed the overlay and the curve
  is not in ``unknown_fields``.
* ``event_curve_unknown`` -- an overlay exists but its curve is unknown
  (unreviewed, recalled, or chart-only). Unknown never widens a limit: the car
  document ceiling applies unchanged.

Every coefficient that is not a car-document field is a
:class:`~afterlap_core.config.Parameter` with ``synthetic_assumption``
provenance. None of them has been calibrated against a real car.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import inf
from typing import TYPE_CHECKING, Any

from ..config import Parameter, VerificationStatus
from .physics import derate_factor

if TYPE_CHECKING:  # pragma: no cover - typing only; the engine must not import the tracks package eagerly
    from ..tracks.package import EventOverlay
    from .config import CarConfig

KPH_PER_MPS = 3.6
W_PER_KW = 1000.0
J_PER_MJ = 1.0e6

SOURCE = "synthetic:afterlap-energy-limits-v1"

REGEN_GRIP_FLOOR = Parameter(
    value=0.3,
    unit="1",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.0,
    upper_bound=0.99,
    note=(
        "Grip multiplier at or below which no regenerative braking is usable: rear-axle "
        "recovery torque is assumed to destabilise the car once surface grip has fallen this far. "
        "Order-of-magnitude assumption for a wet surface; not a measured stability limit."
    ),
)
"""Default of the grip/stability regen law when the car document does not set one."""

REGEN_GRIP_EXPONENT = Parameter(
    value=1.0,
    unit="1",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.25,
    upper_bound=4.0,
    note="Shape of the usable-regen law between the grip floor and dry reference; 1.0 is linear.",
)

LABEL_CAR = "car_document"
LABEL_EVENT_CONFIRMED = "event_curve_confirmed"
LABEL_EVENT_UNKNOWN = "event_curve_unknown"

_Curve = tuple[tuple[float, ...], tuple[float, ...]]
"""Speeds in m/s (strictly increasing) and DC power in W, ready for interpolation."""


def _curve_si(rows: list[Any] | None) -> _Curve | None:
    """Sort and convert confirmed ``(speed_kph, power_kw)`` rows; ``None`` stays unknown.

    A confirmed *empty* list is knowledge ("no curve defined for this event"); it
    is returned as an empty curve, which imposes no limit.
    """
    if rows is None:
        return None
    pairs = sorted((float(kph) / KPH_PER_MPS, float(kw) * W_PER_KW) for kph, kw in rows)
    speeds = tuple(s for s, _ in pairs)
    powers = tuple(p for _, p in pairs)
    return speeds, powers


def interpolate_curve(curve: _Curve, speed_mps: float) -> float:
    """Piecewise-linear power at ``speed_mps`` with flat extrapolation at both ends."""
    speeds, powers = curve
    if not speeds:
        return inf
    if speed_mps <= speeds[0]:
        return powers[0]
    if speed_mps >= speeds[-1]:
        return powers[-1]
    index = bisect_right(speeds, speed_mps) - 1
    low_s, high_s = speeds[index], speeds[index + 1]
    span = high_s - low_s
    frac = 0.0 if span <= 0.0 else (speed_mps - low_s) / span
    return powers[index] + frac * (powers[index + 1] - powers[index])


@dataclass(frozen=True, slots=True)
class EventEnergyLimits:
    """The event-specific electrical values the rules allow us to use.

    Built once per simulator reset from an :class:`EventOverlay` through
    :func:`overlay_effective_values`, so the two-reviewer gate is applied
    exactly once and the per-step object only reads tuples.
    """

    event_id: str | None
    review_status: str | None
    standard_curve: _Curve | None
    overtake_curve: _Curve | None
    recharge_allowance_j: float | None

    @classmethod
    def none(cls) -> EventEnergyLimits:
        """No overlay at all: every limit comes from the car document."""
        return cls(None, None, None, None, None)

    @classmethod
    def from_overlay(cls, overlay: EventOverlay | None) -> EventEnergyLimits:
        if overlay is None:
            return cls.none()
        from ..tracks.fia_overlay import overlay_effective_values

        values = overlay_effective_values(overlay)
        allowance = values["recharge_allowance_mj"]
        return cls(
            event_id=values["event_id"],
            review_status=values["review_status"],
            standard_curve=_curve_si(values["standard_curve"]),
            overtake_curve=_curve_si(values["overtake_curve"]),
            recharge_allowance_j=None if allowance is None else float(allowance) * J_PER_MJ,
        )

    @property
    def present(self) -> bool:
        return self.event_id is not None

    def curve_label(self, curve: _Curve | None) -> str:
        if not self.present:
            return LABEL_CAR
        if curve is None:
            return LABEL_EVENT_UNKNOWN
        return LABEL_EVENT_CONFIRMED if curve[0] else LABEL_CAR


def usable_regen_fraction(grip_multiplier: float, floor: float, exponent: float) -> float:
    """Share of the regen route the driver can use at this grip; 1.0 at the dry reference.

    ``((g - floor) / (1 - floor)) ** exponent`` clipped to [0, 1]. Exactly 1.0 at
    ``g >= 1`` so a dry run is bit-identical to a run without this law.
    """
    if grip_multiplier >= 1.0:
        return 1.0
    if grip_multiplier <= floor:
        return 0.0
    base = (grip_multiplier - floor) / (1.0 - floor)
    return base if exponent == 1.0 else base**exponent


@dataclass(frozen=True, slots=True)
class ElectricalLimits:
    """Deployment and recovery ceilings for one car, one instant, one location.

    Cheap to construct (four attribute stores), so the engine builds one per
    car per force evaluation and keeps the last one for :meth:`describe`.
    """

    car: CarConfig
    event: EventEnergyLimits
    battery_temperature_k: float
    grip_multiplier: float

    @classmethod
    def build(
        cls,
        car: CarConfig,
        overlay: EventOverlay | None,
        *,
        battery_temperature_k: float,
        grip_multiplier: float = 1.0,
    ) -> ElectricalLimits:
        """Convenience for callers holding a raw overlay (tests, tools)."""
        return cls(car, EventEnergyLimits.from_overlay(overlay), battery_temperature_k, grip_multiplier)

    def thermal_derate(self) -> float:
        car = self.car
        return derate_factor(
            self.battery_temperature_k,
            float(car.derate_start_temperature_k.value),
            float(car.derate_end_temperature_k.value),
        )

    def charge_acceptance(self) -> float:
        """Battery acceptance factor in [0, 1]; 1.0 when the car document sets no ramp."""
        car = self.car
        start = car.charge_acceptance_start_temperature_k
        end = car.charge_acceptance_end_temperature_k
        if start is None or end is None:
            return 1.0
        return derate_factor(self.battery_temperature_k, float(start.value), float(end.value))

    def regen_grip_fraction(self, grip_multiplier: float | None = None) -> float:
        grip = self.grip_multiplier if grip_multiplier is None else grip_multiplier
        floor_param = self.car.regen_grip_floor
        floor = float(REGEN_GRIP_FLOOR.value if floor_param is None else floor_param.value)
        return usable_regen_fraction(grip, floor, float(REGEN_GRIP_EXPONENT.value))

    def applied_curve(self, *, overtake_eligible: bool) -> _Curve | None:
        """The event curve that governs this car: ``None`` when unknown.

        An eligible car uses the Overtake curve only when that curve is
        confirmed *and has rows*; a confirmed "none defined" or an unknown
        Overtake curve falls back to the standard curve. Unknown never widens.
        """
        event = self.event
        overtake = event.overtake_curve
        if overtake_eligible and overtake is not None and overtake[0]:
            return overtake
        return event.standard_curve

    def event_deploy_curve_w(self, speed_mps: float, *, overtake_eligible: bool) -> float:
        """Event curve at this speed, or ``inf`` when unknown or none defined."""
        curve = self.applied_curve(overtake_eligible=overtake_eligible)
        if curve is None:
            return inf
        return interpolate_curve(curve, speed_mps)

    def deploy_ceiling_dc_w(self, speed_mps: float, *, overtake_eligible: bool = False) -> float:
        """DC-bus deployment ceiling: min(car ceiling x thermal derate, event curve)."""
        car_w = self.thermal_derate() * float(self.car.max_deploy_power_w.value)
        return min(car_w, self.event_deploy_curve_w(speed_mps, overtake_eligible=overtake_eligible))

    def harvest_ceiling_dc_w(
        self,
        speed_mps: float,
        mechanical_brake_w: float,
        grip_multiplier: float | None = None,
    ) -> float:
        """DC-bus recovery ceiling for the braking power currently applied.

        ``min(max_harvest, regen_share * P_brake, grip_fraction * regen_share * P_brake,
        acceptance * max_harvest)``. Braking power not admitted here stays on the
        friction brakes; the ledger records it as mechanical rejection, so no
        wheel work is counted twice.
        """
        car = self.car
        max_harvest_w = float(car.max_harvest_power_w.value)
        regen_route_w = float(car.regen_share.value) * mechanical_brake_w
        return min(
            max_harvest_w,
            regen_route_w,
            self.regen_grip_fraction(grip_multiplier) * regen_route_w,
            self.charge_acceptance() * max_harvest_w,
        )

    def recharge_allowance_j(self) -> float | None:
        """Event recharge allowance in joules; ``None`` when unknown."""
        return self.event.recharge_allowance_j

    def describe(self) -> dict[str, Any]:
        """Which source bound each limit, plus the factors that were in force."""
        event = self.event
        acceptance_declared = (
            self.car.charge_acceptance_start_temperature_k is not None
            and self.car.charge_acceptance_end_temperature_k is not None
        )
        if not event.present:
            allowance_label = LABEL_CAR
        elif event.recharge_allowance_j is None:
            allowance_label = LABEL_EVENT_UNKNOWN
        else:
            allowance_label = LABEL_EVENT_CONFIRMED
        return {
            "event_id": event.event_id,
            "review_status": event.review_status,
            "deploy_standard": event.curve_label(self.applied_curve(overtake_eligible=False)),
            "deploy_overtake": event.curve_label(self.applied_curve(overtake_eligible=True)),
            "recharge_allowance": allowance_label,
            "recharge_allowance_j": event.recharge_allowance_j,
            "harvest_max": LABEL_CAR,
            "harvest_regen_share": LABEL_CAR,
            "harvest_grip_law": (
                LABEL_CAR if self.car.regen_grip_floor is not None else f"{SOURCE}:regen_grip_floor"
            ),
            "harvest_acceptance": LABEL_CAR if acceptance_declared else "none_declared",
            "thermal_derate_factor": self.thermal_derate(),
            "charge_acceptance_factor": self.charge_acceptance(),
            "regen_grip_fraction": self.regen_grip_fraction(),
            "grip_multiplier": self.grip_multiplier,
            "battery_temperature_k": self.battery_temperature_k,
        }


__all__ = [
    "LABEL_CAR",
    "LABEL_EVENT_CONFIRMED",
    "LABEL_EVENT_UNKNOWN",
    "REGEN_GRIP_EXPONENT",
    "REGEN_GRIP_FLOOR",
    "ElectricalLimits",
    "EventEnergyLimits",
    "interpolate_curve",
    "usable_regen_fraction",
]
