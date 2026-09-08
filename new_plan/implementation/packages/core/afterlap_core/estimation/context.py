"""Shared inputs and per-family bookkeeping for the estimator.

An :class:`Observation` is one canonical telemetry sample already placed on the
session clock. :class:`EstimationContext` carries everything the estimator is
allowed to know that is *not* an observation: the decision cutoff, the clock
mapping and its uncertainty, the source's declared capability, the freshness and
integration-gap findings from :mod:`afterlap_core.data.quality`, and race-level
facts owned by other modules.

Nothing here reaches into simulator state. The context is assembled from source
capability declarations and from observations, which is what makes the
truth-mutation test in ``tests/estimation/test_rivals.py`` meaningful.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from afterlap_contracts import (
    ChannelQuality,
    EligibilityState,
    FlagState,
    Provenance,
    Quality,
    SourceCapability,
    TelemetryEvent,
)
from afterlap_core.timebase import ClockMapping

#: Channels the own-car filter knows how to fuse.
OWN_CAR_CHANNELS: frozenset[str] = frozenset(
    {
        "progress_m",
        "lap_distance_m",
        "speed_mps",
        "acceleration_mps2",
        "battery_energy_j",
        "electrical_power_w",
        "battery_temperature_k",
        "recharge_ledger_j",
    }
)

#: Channels the rival filter consumes.
RIVAL_CHANNELS: frozenset[str] = frozenset(
    {"progress_m", "speed_mps", "lap_distance_m", "gap_ahead_s", "gap_behind_s"}
)

#: Quality values whose sample may be fused. Anything else is recorded, not used.
USABLE_QUALITIES: frozenset[Quality] = frozenset({Quality.VALID, Quality.DEGRADED, Quality.STALE})


@dataclass(frozen=True, slots=True)
class Observation:
    """One telemetry sample expressed on the canonical session clock."""

    event_id: str
    car_id: str
    channel: str
    value: float | None
    unit: str
    session_time_s: float
    source_time_s: float
    provenance: Provenance
    quality: Quality
    source_id: str | None = None

    @property
    def usable(self) -> bool:
        return self.value is not None and self.quality in USABLE_QUALITIES


@dataclass(frozen=True, slots=True)
class RejectedObservation:
    """An observation the estimator refused, with the reason it refused it."""

    event_id: str
    channel: str
    session_time_s: float
    reason: str


@dataclass(frozen=True, slots=True)
class EstimationContext:
    """Everything the estimator may condition on besides the observations."""

    session_id: str
    car_id: str
    cutoff_s: float
    track_length_m: float
    created_at_s: float | None = None
    clock: ClockMapping | None = None
    clock_uncertainty_s: float = 0.0
    lap: int = 0
    total_laps: int | None = None
    position: int | None = None
    flag_state: FlagState = FlagState.UNKNOWN
    flag_known: bool = False
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    eligibility_observed_at_s: float | None = None
    rival_car_ids: tuple[str, ...] = ()
    capability: SourceCapability | None = None
    channel_quality: tuple[ChannelQuality, ...] = ()
    integration_gap_s: Mapping[str, float] = field(default_factory=dict)
    expected_periods_s: Mapping[str, float] = field(default_factory=dict)
    lateral_geometry_known: bool = False
    observation_dropout_s: float = 0.0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.track_length_m <= 0.0:
            raise ValueError("track length must be positive")
        if self.cutoff_s < 0.0:
            raise ValueError("the decision cutoff cannot be negative")
        if self.clock_uncertainty_s < 0.0:
            raise ValueError("clock uncertainty cannot be negative")
        if self.created_at_s is not None and self.created_at_s < self.cutoff_s:
            raise ValueError("an estimate cannot be created before its own observation cutoff")

    @property
    def publish_time_s(self) -> float:
        return self.cutoff_s if self.created_at_s is None else self.created_at_s

    @property
    def effective_clock_uncertainty_s(self) -> float:
        """The larger of the explicit uncertainty and the source's declared clock error."""
        declared = self.capability.clock_error_s if self.capability is not None else 0.0
        mapped = self.clock.uncertainty_s if self.clock is not None else 0.0
        return max(self.clock_uncertainty_s, declared, mapped)

    def channel_is_measured(self, channel: str) -> bool:
        """True only when the source itself declares the channel measured.

        A source that merely *supports* a channel is not treated as measuring it;
        that distinction is what gates energy capability.
        """
        if self.capability is None:
            return True
        return self.capability.measures(channel)

    def channel_is_supported(self, channel: str) -> bool:
        if self.capability is None:
            return True
        return self.capability.provides(channel)

    def gap_for(self, channel: str) -> float:
        return float(self.integration_gap_s.get(channel, 0.0))

    def expected_period_for(self, channel: str) -> float | None:
        period = self.expected_periods_s.get(channel)
        if period is not None:
            return float(period)
        if self.capability is not None:
            rate = self.capability.update_rates_hz.get(channel)
            if rate:
                return 1.0 / float(rate)
        return None

    def to_session_time(self, source_time_s: float) -> float:
        return self.clock.to_session_time(source_time_s) if self.clock is not None else source_time_s


@dataclass(frozen=True, slots=True)
class FamilyDiagnostic:
    """Provenance, age, residual and uncertainty for one estimated family.

    Recorded for every family the estimator publishes, so a consumer can see how
    an individual number was supported rather than trusting the estimate as a
    block.
    """

    family: str
    provenance: Provenance
    quality: Quality
    observed_at_s: float | None = None
    observation_age_s: float | None = None
    residual: float | None = None
    residual_normalised: float | None = None
    innovation_variance: float | None = None
    standard_deviation: float | None = None
    source_id: str | None = None
    update_count: int = 0
    note: str | None = None


def observations_from_events(
    events: Iterable[TelemetryEvent],
    context: EstimationContext,
    *,
    source_id: str | None = None,
) -> tuple[tuple[Observation, ...], tuple[RejectedObservation, ...]]:
    """Place events on the session clock and drop everything after the cutoff.

    The cutoff filter is a hard causality rule, not a tuning choice: an event
    whose session time exceeds ``context.cutoff_s`` is returned in the rejected
    tuple and is never seen by any filter, any quality tracker or any identifier
    list. That is what makes an estimate reproducible from its own cutoff.
    """
    accepted: list[Observation] = []
    rejected: list[RejectedObservation] = []
    for event in events:
        session_time_s = context.to_session_time(event.source_time_s)
        if session_time_s > context.cutoff_s:
            rejected.append(
                RejectedObservation(
                    event_id=event.event_id,
                    channel=event.channel,
                    session_time_s=session_time_s,
                    reason=(
                        f"observation at {session_time_s:.6f} s is later than the decision cutoff "
                        f"{context.cutoff_s:.6f} s"
                    ),
                )
            )
            continue
        accepted.append(
            Observation(
                event_id=event.event_id,
                car_id=event.car_id,
                channel=event.channel,
                value=event.value,
                unit=event.unit,
                session_time_s=session_time_s,
                source_time_s=event.source_time_s,
                provenance=event.provenance,
                quality=event.quality,
                source_id=source_id,
            )
        )
    accepted.sort(key=lambda obs: (obs.session_time_s, obs.channel, obs.event_id))
    return tuple(accepted), tuple(rejected)


def group_by_car(observations: Sequence[Observation]) -> dict[str, tuple[Observation, ...]]:
    grouped: dict[str, list[Observation]] = {}
    for observation in observations:
        grouped.setdefault(observation.car_id, []).append(observation)
    return {car_id: tuple(items) for car_id, items in grouped.items()}


__all__ = [
    "OWN_CAR_CHANNELS",
    "RIVAL_CHANNELS",
    "USABLE_QUALITIES",
    "EstimationContext",
    "FamilyDiagnostic",
    "Observation",
    "RejectedObservation",
    "group_by_car",
    "observations_from_events",
]
