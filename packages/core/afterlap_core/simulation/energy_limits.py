from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import inf
from typing import TYPE_CHECKING, Any

from ..config import Parameter, VerificationStatus
from .physics import derate_factor

if TYPE_CHECKING:
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


def interpolate_curve(curve: _Curve, speed_mps: float) -> float:

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
    event_id: str | None
    review_status: str | None
    standard_curve: _Curve | None
    overtake_curve: _Curve | None
    recharge_allowance_j: float | None

    @classmethod
    def none(cls) -> EventEnergyLimits:

        return cls(None, None, None, None, None)

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

    if grip_multiplier >= 1.0:
        return 1.0
    if grip_multiplier <= floor:
        return 0.0
    base = (grip_multiplier - floor) / (1.0 - floor)
    return base if exponent == 1.0 else base**exponent


@dataclass(frozen=True, slots=True)
class ElectricalLimits:
    car: CarConfig
    event: EventEnergyLimits
    battery_temperature_k: float
    grip_multiplier: float

    def thermal_derate(self) -> float:
        car = self.car
        return derate_factor(
            self.battery_temperature_k,
            float(car.derate_start_temperature_k.value),
            float(car.derate_end_temperature_k.value),
        )

    def charge_acceptance(self) -> float:

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

    def applied_curve(self, overtake_eligible: bool) -> _Curve | None:

        event = self.event
        overtake = event.overtake_curve
        if overtake_eligible and overtake is not None and overtake[0]:
            return overtake
        return event.standard_curve

    def event_deploy_curve_w(self, speed_mps: float, overtake_eligible: bool) -> float:

        curve = self.applied_curve(overtake_eligible)
        if curve is None:
            return inf
        return interpolate_curve(curve, speed_mps)

    def deploy_ceiling_dc_w(self, speed_mps: float, overtake_eligible: bool = False) -> float:

        car_w = self.thermal_derate() * float(self.car.max_deploy_power_w.value)
        return min(car_w, self.event_deploy_curve_w(speed_mps, overtake_eligible))

    def harvest_ceiling_dc_w(
        self,
        speed_mps: float,
        mechanical_brake_w: float,
        grip_multiplier: float | None = None,
    ) -> float:

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

        return self.event.recharge_allowance_j

    def describe(self) -> dict[str, Any]:

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
            "deploy_standard": event.curve_label(self.applied_curve(False)),
            "deploy_overtake": event.curve_label(self.applied_curve(True)),
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
