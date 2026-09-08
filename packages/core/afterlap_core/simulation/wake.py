"""Aerodynamic interaction between a follower and the car ahead.

``RACE_CONDITION_MODEL.md`` ("Traffic and overtaking") asks for the wake to be
modelled as "relative longitudinal/lateral position, yaw and speed-dependent
drag/downforce modifiers **calibrated to declared assumptions**", and states the
limit that governs this whole module:

    Longitudinal gap alone can estimate a tow but cannot establish side-by-side
    space or contact probability.

So this module produces exactly two numbers -- a multiplier on ``CdA`` and a
multiplier on ``ClA`` -- from the *longitudinal* separation, and it says
truthfully whether the lateral offset behind those numbers was known. It makes
no side-by-side, overlap or contact claim; those live in
:mod:`afterlap_core.simulation.overtake`, which refuses them when the corridor
is unknown (decision D-10: a compiled driven-line package has
``lateral_geometry_surveyed is False`` and ``width_at`` returns ``nan``).

Functional form
---------------

One dimensionless *shielding* fraction drives both multipliers::

    decay(x)     = (exp(-x / L) - exp(-R / L)) / (1 - exp(-R / L))   for 0 <= x <= R
                 = 0                                                 for x > R
    falloff(y)   = exp(-(y / W) ** 2)          lateral offset known
                 = 1.0                         lateral offset unknown (in-line assumption)
    gate(v)      = min(1, v / V_ref)
    shielding    = decay(x) * falloff(y) * gate(v_leader)

    drag_multiplier      = 1 - D_max * shielding
    downforce_multiplier = 1 - F_max * shielding

where ``x`` is the nose-to-tail longitudinal separation, ``y`` the lateral
centre offset, ``v_leader`` the leader's ground speed, and ``L``, ``R``, ``W``,
``V_ref``, ``D_max``, ``F_max`` are the declared coefficients below.

``decay`` is a *range-truncated normalised exponential*: it is exactly 1.0 at
zero separation and exactly 0.0 at the declared range ``R``, so the effect
switches off continuously instead of stepping to zero at the range boundary,
and a car with nothing ahead of it inside ``R`` gets multipliers that are
exactly ``1.0`` and therefore a bit-identical trajectory.

What is *not* claimed
---------------------

* No coefficient here has been calibrated against a car, a wind tunnel or a
  telemetry residual. Every one is a :class:`~afterlap_core.config.Parameter`
  with ``synthetic_assumption`` provenance and a note saying what it means.
  Per the calibration hierarchy in ``RACE_CONDITION_MODEL.md``, traffic
  interaction is calibrated *after* free-air pace and braking; that step has
  not been done.
* Yaw is not an input. The spec lists it; resolving a yawed wake needs the
  lateral geometry this model may not assume, so it is left out rather than
  approximated.
* The multipliers do not depend on relative speed. ``relative_speed_mps`` is
  accepted and recorded because it is part of the interaction state a caller
  has, but no rate dependence is asserted without evidence for one.
* Nothing here is enabled by default. The engine applies a wake only when a
  run explicitly passes a :class:`WakeModel`, so every existing pinned number
  is reproduced bit for bit.
"""

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
"""No leader inside the declared range, or the leader is not ahead."""

LABEL_LATERAL_RESOLVED = "wake:lateral_resolved"
"""A corridor width was available, so a real lateral offset was supplied and the
lateral falloff applies. Whether that corridor was surveyed or merely declared is
the track source's provenance, recorded there and not restated here."""

LABEL_INLINE_ASSUMPTION = "wake:unknown_corridor_inline_assumption"
"""No corridor: the tow is estimated from longitudinal separation alone,
under the declared assumption that the follower is in line with the leader. No
side-by-side, overlap or contact claim follows from this."""

LABEL_DISABLED = "wake:disabled"
"""No wake model was installed on the run; the follower is in free air by construction."""


@dataclass(frozen=True, slots=True)
class WakeEffect:
    """What the wake model asserts about one follower at one instant.

    ``drag_multiplier`` and ``downforce_multiplier`` multiply the follower's
    ``CdA`` and ``ClA``. Both are exactly ``1.0`` when there is nothing ahead
    inside the declared range, which is what keeps a lone car's trajectory
    bit-identical to a run without the model.

    ``lateral_known`` is the honesty flag: ``False`` means the multipliers rest
    on the in-line assumption because the corridor is unsurveyed, and that *no*
    lateral conclusion -- side-by-side space, overlap, contact -- may be drawn
    from this record.
    """

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
        """Fraction of free-air ``CdA`` removed; 0.0 in free air."""
        return 1.0 - self.drag_multiplier

    @property
    def downforce_loss_fraction(self) -> float:
        return 1.0 - self.downforce_multiplier

    def describe(self) -> dict[str, Any]:
        """Per-car diagnostic record. Provenance, never an input to the dynamics."""
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
"""The neutral effect. Multipliers are exactly 1.0, so applying it is a no-op."""

DISABLED = WakeEffect(label=LABEL_DISABLED)
"""Returned when no wake model is installed, so a diagnostic says *why* it is 1.0."""


@dataclass(frozen=True, slots=True)
class WakeModel:
    """The declared-assumption wake, with every coefficient overridable.

    Frozen: a run cannot retune the aerodynamics halfway through. Construct a
    second model instead, which is then a different declared assumption and
    shows up as such in the run's diagnostics.
    """

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
        """Range-truncated normalised exponential; 1.0 at contact, 0.0 at the range."""
        if not math.isfinite(separation_m) or separation_m >= self.range_m:
            return 0.0
        x = max(0.0, separation_m)
        edge = math.exp(-self.range_m / self.decay_length_m)
        return (math.exp(-x / self.decay_length_m) - edge) / (1.0 - edge)

    def lateral_falloff(self, lateral_offset_m: float) -> float:
        """Gaussian falloff across the wake. Only ever called with a *known* offset."""
        ratio = lateral_offset_m / self.lateral_scale_m
        return math.exp(-(ratio * ratio))

    def speed_gate(self, leader_speed_mps: float) -> float:
        """Linear ramp to full strength at the speed reference."""
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
        """Multipliers for one follower.

        ``separation_m`` is the nose-to-tail longitudinal separation from the
        follower's nose to the leader's tail. ``None``, ``nan`` or a negative
        value means there is no car ahead to shelter behind, and the result is
        free air.

        ``lateral_offset_m`` is ``None`` when the corridor is unsurveyed. The
        tow is then still estimated -- longitudinal separation supports that --
        but under the explicit in-line assumption, and the returned effect says
        so through ``lateral_known=False`` and its label.
        """
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
        """Every coefficient with its declared provenance, for the run manifest."""
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
"""The declared default. It is **not** installed automatically: a run must pass it."""


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
