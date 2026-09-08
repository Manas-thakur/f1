"""Controller-visible belief state.

``StateEstimate`` is the *only* input path from the world to the controller and
to operational UIs. It never contains simulator truth: see ``WorldState``, which
lives in the simulation package and has no wire schema.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import EligibilityState, FlagState, Provenance, Quality, RivalIntention
from .quantities import IntervalValue, ScalarValue
from .telemetry import ChannelQuality


class OwnCarEstimate(Contract):
    """Fused belief about the car being advised.

    Energy is nullable: a public-only source cannot observe battery state, and
    a missing value must gate precise energy advice rather than be invented.
    """

    car_id: str = Field(min_length=1)
    progress_m: ScalarValue
    lap_distance_m: ScalarValue
    completed_laps: int = Field(ge=0)
    speed_mps: ScalarValue
    acceleration_mps2: ScalarValue
    battery_energy_j: ScalarValue
    battery_energy_interval: IntervalValue | None = Field(
        default=None,
        description="Set when only partial energy information exists; not collapsed to a point value.",
    )
    battery_temperature_k: ScalarValue
    electrical_power_w: ScalarValue = Field(
        description="Signed DC-bus power. Positive deploys to the wheels; negative harvests."
    )
    recharge_spent_this_lap_j: ScalarValue
    tyre_pace_residual_s_per_lap: ScalarValue | None = None
    active_profile_id: str | None = None

    @model_validator(mode="after")
    def _energy_uncertainty_is_explicit(self) -> OwnCarEstimate:
        if (
            self.battery_energy_j.value is None
            and self.battery_energy_interval is None
            and self.battery_energy_j.quality is Quality.VALID
        ):
            raise ValueError("unknown energy must be quality missing/invalid")
        return self

    @property
    def has_energy_capability(self) -> bool:
        """True when precise energy advice is supportable for this car."""
        return self.battery_energy_j.value is not None and self.battery_energy_j.quality in (
            Quality.VALID,
            Quality.DEGRADED,
        )


class IntentionWeights(Contract):
    """Normalised posterior over reactive rival intentions."""

    conserve: float = Field(ge=0.0, le=1.0)
    normal: float = Field(ge=0.0, le=1.0)
    attack: float = Field(ge=0.0, le=1.0)
    defend: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _sums_to_one(self) -> IntentionWeights:
        total = self.conserve + self.normal + self.attack + self.defend
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"intention weights must sum to 1.0, got {total!r}")
        return self

    def as_mapping(self) -> dict[RivalIntention, float]:
        return {
            RivalIntention.CONSERVE: self.conserve,
            RivalIntention.NORMAL: self.normal,
            RivalIntention.ATTACK: self.attack,
            RivalIntention.DEFEND: self.defend,
        }


class RivalBelief(Contract):
    """Belief about one rival, built only from permitted observations.

    Rival energy is never ``measured``: without an authorised feed it is an
    estimate with a wide interval, and it may be entirely unknown.
    """

    car_id: str = Field(min_length=1)
    slot: str = Field(min_length=1, description="Stable identity slot, e.g. 'ahead_1' or 'behind_1'.")
    is_ahead: bool
    gap_s: ScalarValue = Field(description="Signed time gap at common progress; positive is ahead.")
    gap_m: ScalarValue
    relative_speed_mps: ScalarValue
    energy_interval_j: IntervalValue | None = None
    energy_mean_j: ScalarValue | None = None
    pace_bias_s_per_lap: ScalarValue | None = None
    intentions: IntentionWeights
    observation_age_s: float | None = Field(default=None, ge=0.0)
    lateral_geometry_known: bool = Field(
        default=False,
        description="False when the source cannot resolve lateral placement; blocks contact-risk claims.",
    )

    @model_validator(mode="after")
    def _rival_energy_is_never_measured(self) -> RivalBelief:
        for field in (self.energy_mean_j,):
            if field is not None and field.provenance is Provenance.MEASURED:
                raise ValueError(
                    "rival battery energy cannot be labelled measured without an authorised feed"
                )
        if self.energy_interval_j is not None and self.energy_interval_j.provenance is Provenance.MEASURED:
            raise ValueError("rival energy interval cannot be labelled measured")
        return self


class RaceContext(Contract):
    """Race-level facts that condition planning."""

    lap: int = Field(ge=0)
    total_laps: int | None = Field(default=None, ge=1)
    remaining_distance_m: ScalarValue
    track_length_m: float = Field(gt=0.0)
    flag_state: FlagState = FlagState.UNKNOWN
    flag_known: bool = True
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    eligibility_observed_at_s: float | None = None
    position: int | None = Field(default=None, ge=1)


class EstimateQuality(Contract):
    """Aggregate health of the estimate and its inputs."""

    overall: Quality
    channels: tuple[ChannelQuality, ...] = ()
    clock_uncertainty_s: float = Field(ge=0.0)
    own_energy_capability: bool = True
    residual_alarm: bool = False
    notes: tuple[str, ...] = ()


class StateEstimate(VersionedContract):
    """Timestamped controller belief.

    ``cutoff_s`` is the decision cutoff: no observation later than this
    contributed. ``contributing_event_ids`` makes that auditable.
    """

    session_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    cutoff_s: float = Field(ge=0.0)
    created_at_s: float = Field(ge=0.0)
    own_car: OwnCarEstimate
    rival_beliefs: tuple[RivalBelief, ...] = ()
    race_context: RaceContext
    quality: EstimateQuality
    contributing_event_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _created_after_cutoff(self) -> StateEstimate:
        if self.created_at_s < self.cutoff_s:
            raise ValueError("estimate cannot be created before its own observation cutoff")
        slots = [rival.slot for rival in self.rival_beliefs]
        if len(set(slots)) != len(slots):
            raise ValueError(f"duplicate rival identity slots: {slots}")
        return self

    def rival_in_slot(self, slot: str) -> RivalBelief | None:
        for rival in self.rival_beliefs:
            if rival.slot == slot:
                return rival
        return None

    @property
    def nearest_ahead(self) -> RivalBelief | None:
        ahead = [r for r in self.rival_beliefs if r.is_ahead and r.gap_s.value is not None]
        return min(ahead, key=lambda r: abs(r.gap_s.value or 0.0), default=None)

    @property
    def nearest_behind(self) -> RivalBelief | None:
        behind = [r for r in self.rival_beliefs if not r.is_ahead and r.gap_s.value is not None]
        return min(behind, key=lambda r: abs(r.gap_s.value or 0.0), default=None)


__all__ = [
    "EstimateQuality",
    "IntentionWeights",
    "OwnCarEstimate",
    "RaceContext",
    "RivalBelief",
    "StateEstimate",
]
