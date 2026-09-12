from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..config import Parameter, VerificationStatus

SOURCE = "synthetic:afterlap-wake-v1"

WAKE_RANGE_M = Parameter(
    value=40.0,
    unit="m",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=1.0,
    upper_bound=200.0,
    note=(
        "Declared longitudinal range of the modelled interaction, nose to tail. Beyond it the "
        "multipliers are exactly 1.0 and the follower is treated as being in free air. Chosen as "
        "an order-of-magnitude wake length for a 5-6 m car; not a measured extent."
    ),
)

WAKE_DECAY_LENGTH_M = Parameter(
    value=12.0,
    unit="m",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.5,
    upper_bound=100.0,
    note=(
        "e-folding length of the momentum deficit behind the leader, before the range "
        "truncation is normalised in. Larger values keep a usable tow further back. "
        "Assumption; no calibration behind the number."
    ),
)

WAKE_DRAG_REDUCTION_MAX = Parameter(
    value=0.28,
    unit="1",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.0,
    upper_bound=0.6,
    note=(
        "Fraction of the follower's CdA removed at zero separation, directly in line, above the "
        "speed reference. This is the size of the tow and it is the single most influential "
        "uncalibrated coefficient in the module."
    ),
)

WAKE_DOWNFORCE_LOSS_MAX = Parameter(
    value=0.35,
    unit="1",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.0,
    upper_bound=0.8,
    note=(
        "Fraction of the follower's ClA lost under the same conditions. Deliberately larger than "
        "the drag reduction so that following costs grip as well as saving drag; the ratio is an "
        "assumption, not a measurement."
    ),
)

WAKE_LATERAL_SCALE_M = Parameter(
    value=1.60,
    unit="m",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=0.2,
    upper_bound=10.0,
    note=(
        "Gaussian half-width of the lateral falloff, applied only when the lateral offset is "
        "known. On an unknown corridor the falloff is not evaluated at all and the in-line form "
        "is used instead, which is recorded in the effect's label."
    ),
)

WAKE_SPEED_REFERENCE_MPS = Parameter(
    value=30.0,
    unit="m/s",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=1.0,
    upper_bound=100.0,
    note=(
        "Leader speed at and above which the modelled deficit is at full strength; below it the "
        "shielding ramps linearly to zero, so a stationary or crawling leader casts no wake. "
        "Assumption standing in for the absence of a low-speed wake model."
    ),
)

LABEL_FREE_AIR = "free_air"


LABEL_LATERAL_RESOLVED = "wake:lateral_resolved"


LABEL_INLINE_ASSUMPTION = "wake:unknown_corridor_inline_assumption"


LABEL_DISABLED = "wake:disabled"


@dataclass(frozen=True, slots=True)
class WakeEffect:
    drag_multiplier: float = 1.0
    downforce_multiplier: float = 1.0
    lateral_known: bool = False
    label: str = LABEL_FREE_AIR
    separation_m: float | None = None
    lateral_offset_m: float | None = None
    relative_speed_mps: float | None = None
    leader_speed_mps: float | None = None
    leader_car_id: str | None = None
    shielding: float = 0.0

    @property
    def in_free_air(self) -> bool:
        return self.drag_multiplier == 1.0 and self.downforce_multiplier == 1.0

    @property
    def drag_reduction_fraction(self) -> float:

        return 1.0 - self.drag_multiplier

    @property
    def downforce_loss_fraction(self) -> float:
        return 1.0 - self.downforce_multiplier

    def describe(self) -> dict[str, Any]:

        return {
            "label": self.label,
            "drag_multiplier": self.drag_multiplier,
            "downforce_multiplier": self.downforce_multiplier,
            "shielding": self.shielding,
            "lateral_known": self.lateral_known,
            "separation_m": self.separation_m,
            "lateral_offset_m": self.lateral_offset_m,
            "relative_speed_mps": self.relative_speed_mps,
            "leader_speed_mps": self.leader_speed_mps,
            "leader_car_id": self.leader_car_id,
            "lateral_claims": (
                "available" if self.lateral_known else "refused: no corridor at this position"
            ),
            "calibration": "uncalibrated declared assumption; see wake.py coefficient notes",
        }


FREE_AIR = WakeEffect()


DISABLED = WakeEffect(label=LABEL_DISABLED)


@dataclass(frozen=True, slots=True)
class WakeModel:
    range_m: float = float(WAKE_RANGE_M.value)
    decay_length_m: float = float(WAKE_DECAY_LENGTH_M.value)
    drag_reduction_max: float = float(WAKE_DRAG_REDUCTION_MAX.value)
    downforce_loss_max: float = float(WAKE_DOWNFORCE_LOSS_MAX.value)
    lateral_scale_m: float = float(WAKE_LATERAL_SCALE_M.value)
    speed_reference_mps: float = float(WAKE_SPEED_REFERENCE_MPS.value)

    def __post_init__(self) -> None:
        for name, value, lower in (
            ("range_m", self.range_m, 0.0),
            ("decay_length_m", self.decay_length_m, 0.0),
            ("lateral_scale_m", self.lateral_scale_m, 0.0),
            ("speed_reference_mps", self.speed_reference_mps, 0.0),
        ):
            if not value > lower:
                raise ValueError(f"{name} must be greater than {lower}; got {value}")
        for name, value in (
            ("drag_reduction_max", self.drag_reduction_max),
            ("downforce_loss_max", self.downforce_loss_max),
        ):
            if not 0.0 <= value < 1.0:
                raise ValueError(
                    f"{name} is the fraction removed at full shielding and must lie in [0, 1); "
                    f"got {value}. A multiplier of zero or less is not a wake, it is a stopped car."
                )

    def decay(self, separation_m: float) -> float:

        if not math.isfinite(separation_m) or separation_m >= self.range_m:
            return 0.0
        x = max(0.0, separation_m)
        edge = math.exp(-self.range_m / self.decay_length_m)
        return (math.exp(-x / self.decay_length_m) - edge) / (1.0 - edge)

    def lateral_falloff(self, lateral_offset_m: float) -> float:

        ratio = lateral_offset_m / self.lateral_scale_m
        return math.exp(-(ratio * ratio))

    def speed_gate(self, leader_speed_mps: float) -> float:

        if not math.isfinite(leader_speed_mps) or leader_speed_mps <= 0.0:
            return 0.0
        return min(1.0, leader_speed_mps / self.speed_reference_mps)

    def evaluate(
        self,
        *,
        separation_m: float | None,
        lateral_offset_m: float | None,
        relative_speed_mps: float,
        leader_speed_mps: float,
        leader_car_id: str | None = None,
    ) -> WakeEffect:

        if (
            leader_car_id is None
            or separation_m is None
            or not math.isfinite(separation_m)
            or separation_m < 0.0
            or separation_m >= self.range_m
        ):
            return WakeEffect(
                label=LABEL_FREE_AIR,
                lateral_known=lateral_offset_m is not None,
                separation_m=separation_m,
                lateral_offset_m=lateral_offset_m,
                relative_speed_mps=relative_speed_mps,
                leader_speed_mps=leader_speed_mps,
                leader_car_id=leader_car_id,
            )

        if lateral_offset_m is None:
            falloff = 1.0
            lateral_known = False
            label = LABEL_INLINE_ASSUMPTION
        elif not math.isfinite(lateral_offset_m):
            falloff = 1.0
            lateral_known = False
            label = LABEL_INLINE_ASSUMPTION
            lateral_offset_m = None
        else:
            falloff = self.lateral_falloff(lateral_offset_m)
            lateral_known = True
            label = LABEL_LATERAL_RESOLVED

        shielding = self.decay(separation_m) * falloff * self.speed_gate(leader_speed_mps)
        return WakeEffect(
            drag_multiplier=1.0 - self.drag_reduction_max * shielding,
            downforce_multiplier=1.0 - self.downforce_loss_max * shielding,
            lateral_known=lateral_known,
            label=label,
            separation_m=separation_m,
            lateral_offset_m=lateral_offset_m,
            relative_speed_mps=relative_speed_mps,
            leader_speed_mps=leader_speed_mps,
            leader_car_id=leader_car_id,
            shielding=shielding,
        )

    def coefficients(self) -> dict[str, dict[str, Any]]:

        declared = {
            "range_m": (self.range_m, WAKE_RANGE_M),
            "decay_length_m": (self.decay_length_m, WAKE_DECAY_LENGTH_M),
            "drag_reduction_max": (self.drag_reduction_max, WAKE_DRAG_REDUCTION_MAX),
            "downforce_loss_max": (self.downforce_loss_max, WAKE_DOWNFORCE_LOSS_MAX),
            "lateral_scale_m": (self.lateral_scale_m, WAKE_LATERAL_SCALE_M),
            "speed_reference_mps": (self.speed_reference_mps, WAKE_SPEED_REFERENCE_MPS),
        }
        return {
            name: {
                "value": value,
                "unit": template.unit,
                "source": template.source,
                "verification": template.verification.value,
                "note": template.note,
                "default": template.value,
            }
            for name, (value, template) in declared.items()
        }

    @property
    def describes(self) -> str:
        return (
            f"wake: range-truncated exponential, R={self.range_m:g} m, L={self.decay_length_m:g} m, "
            f"drag -{self.drag_reduction_max:.0%} / downforce -{self.downforce_loss_max:.0%} at full "
            "shielding; uncalibrated declared assumption"
        )


DEFAULT_WAKE = WakeModel()


__all__ = [
    "DEFAULT_WAKE",
    "DISABLED",
    "FREE_AIR",
    "LABEL_DISABLED",
    "LABEL_FREE_AIR",
    "LABEL_INLINE_ASSUMPTION",
    "LABEL_LATERAL_RESOLVED",
    "SOURCE",
    "WAKE_DECAY_LENGTH_M",
    "WAKE_DOWNFORCE_LOSS_MAX",
    "WAKE_DRAG_REDUCTION_MAX",
    "WAKE_LATERAL_SCALE_M",
    "WAKE_RANGE_M",
    "WAKE_SPEED_REFERENCE_MPS",
    "WakeEffect",
    "WakeModel",
]
