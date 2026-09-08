"""Channel freshness and integration-gap assessment.

Freshness is a function of the age of the last *observation* on that channel,
the cadence the source itself declared, the channel's registered bounds and the
clock mapping uncertainty. It is deliberately **not** a function of transport
liveness: a WebSocket heartbeat proves a socket is open and nothing else, so
``QualityTracker.heartbeat`` records the heartbeat for connection diagnostics
and is never read by :meth:`QualityTracker.assess`.

A channel that feeds an energy integral (electrical power) also reports how much
integration time was unobserved. Estimation widens its uncertainty by that
amount rather than pretending the gap integrated to zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from afterlap_contracts import (
    ChannelQuality,
    Quality,
    SourceCapability,
    channel as channel_spec,
    is_registered,
)
from afterlap_core.timebase import classify_freshness

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

INTEGRATING_CHANNELS: frozenset[str] = frozenset({"electrical_power_w", "deploy_power_w", "harvest_power_w"})


@dataclass(frozen=True, slots=True)
class ChannelExpectation:
    """What the source promised for one channel on one car."""

    channel: str
    expected_rate_hz: float
    car_id: str | None = None
    measured: bool = True
    note: str | None = None

    def __post_init__(self) -> None:
        if self.expected_rate_hz <= 0.0:
            raise ValueError(f"expected rate for {self.channel} must be positive")
        if not is_registered(self.channel):
            raise ValueError(f"unregistered channel {self.channel!r}")

    @property
    def expected_period_s(self) -> float:
        return 1.0 / self.expected_rate_hz

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.channel, self.car_id)


@dataclass(frozen=True, slots=True)
class IntegrationGapRecord:
    """An unobserved interval on a channel that feeds an energy integral.

    ``integration_gap_s`` is the quantity downstream estimation uses to widen
    uncertainty; it is never silently treated as zero power.
    """

    channel: str
    car_id: str | None
    integration_gap_s: float
    gap_start_s: float
    gap_end_s: float
    cumulative_gap_s: float
    expected_period_s: float
    reason: str


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    """Result of one assessment pass."""

    at_s: float
    channels: tuple[ChannelQuality, ...]
    integration_gaps: tuple[IntegrationGapRecord, ...] = ()
    heartbeat_age_s: float | None = None
    heartbeat_note: str = "Transport liveness only. Heartbeats never contribute to channel freshness."

    def by_channel(self, channel: str, car_id: str | None = None) -> ChannelQuality | None:
        for entry in self.channels:
            if entry.channel == channel and entry.car_id == car_id:
                return entry
        return None

    def integration_gap_for(self, channel: str, car_id: str | None = None) -> float:
        total = 0.0
        for gap in self.integration_gaps:
            if gap.channel == channel and gap.car_id == car_id:
                total = max(total, gap.cumulative_gap_s)
        return total

    def worst(self) -> Quality:
        order = [Quality.VALID, Quality.DEGRADED, Quality.STALE, Quality.INVALID, Quality.MISSING]
        worst = Quality.VALID
        for entry in self.channels:
            if order.index(entry.quality) > order.index(worst):
                worst = entry.quality
        return worst


@dataclass(slots=True)
class _ChannelState:
    last_source_time_s: float | None = None
    last_session_time_s: float | None = None
    last_value: float | None = None
    last_quality: Quality | None = None
    last_reason: str | None = None
    observation_count: int = 0
    cumulative_gap_s: float = 0.0
    gaps: list[IntegrationGapRecord] = field(default_factory=list)


class QualityTracker:
    """Per-channel observation bookkeeping and freshness classification."""

    def __init__(
        self,
        expectations: Iterable[ChannelExpectation],
        *,
        clock_uncertainty_s: float = 0.0,
        integration_gap_periods: float = 2.0,
        stale_periods: float = 4.0,
        degraded_periods: float = 2.0,
        missing_periods: float = 20.0,
    ) -> None:
        if clock_uncertainty_s < 0.0:
            raise ValueError("clock uncertainty cannot be negative")
        self._expectations: dict[tuple[str, str | None], ChannelExpectation] = {}
        for expectation in expectations:
            self._expectations[expectation.key] = expectation
        self._states: dict[tuple[str, str | None], _ChannelState] = {
            key: _ChannelState() for key in self._expectations
        }
        self.clock_uncertainty_s = clock_uncertainty_s
        self.integration_gap_periods = integration_gap_periods
        self._thresholds = {
            "stale_periods": stale_periods,
            "degraded_periods": degraded_periods,
            "missing_periods": missing_periods,
        }
        self._last_heartbeat_s: float | None = None
        self._heartbeat_count = 0

    @property
    def expectations(self) -> Mapping[tuple[str, str | None], ChannelExpectation]:
        return dict(self._expectations)

    def expectation_for(self, channel: str, car_id: str | None = None) -> ChannelExpectation | None:
        return self._expectations.get((channel, car_id)) or self._expectations.get((channel, None))

    def observe(
        self,
        channel: str,
        *,
        session_time_s: float,
        source_time_s: float | None = None,
        car_id: str | None = None,
        value: float | None = None,
        quality: Quality | None = None,
        reason: str | None = None,
    ) -> IntegrationGapRecord | None:
        """Record one observation; returns an integration gap if this sample closed one."""
        key = self._resolve_key(channel, car_id)
        state = self._states.setdefault(key, _ChannelState())
        expectation = self.expectation_for(channel, key[1])

        gap_record: IntegrationGapRecord | None = None
        previous = state.last_session_time_s
        if (
            previous is not None
            and expectation is not None
            and channel in INTEGRATING_CHANNELS
            and session_time_s > previous
        ):
            threshold = self.integration_gap_periods * expectation.expected_period_s
            elapsed = session_time_s - previous
            if elapsed > threshold:
                unobserved = elapsed - expectation.expected_period_s
                state.cumulative_gap_s += unobserved
                gap_record = IntegrationGapRecord(
                    channel=channel,
                    car_id=key[1],
                    integration_gap_s=unobserved,
                    gap_start_s=previous,
                    gap_end_s=session_time_s,
                    cumulative_gap_s=state.cumulative_gap_s,
                    expected_period_s=expectation.expected_period_s,
                    reason=(
                        f"{unobserved:.3f} s of {channel} integration is unobserved; "
                        "widen energy uncertainty by this interval"
                    ),
                )
                state.gaps.append(gap_record)

        state.observation_count += 1
        if previous is not None and session_time_s < previous:
            return gap_record
        state.last_session_time_s = session_time_s
        state.last_source_time_s = source_time_s if source_time_s is not None else session_time_s
        state.last_value = value
        state.last_quality = quality
        state.last_reason = reason
        return gap_record

    def heartbeat(self, at_s: float) -> None:
        """Record transport liveness.

        This exists so a connection fault is visible. It intentionally has no
        effect on :meth:`assess`; see the module docstring.
        """
        self._last_heartbeat_s = at_s
        self._heartbeat_count += 1

    @property
    def heartbeat_count(self) -> int:
        return self._heartbeat_count

    def assess(self, now_s: float) -> QualityAssessment:
        entries: list[ChannelQuality] = []
        gaps: list[IntegrationGapRecord] = []
        all_keys = set(self._expectations) | set(self._states)
        specialised = {channel for channel, car in all_keys if car is not None}
        keys = sorted(
            (key for key in all_keys if not (key[1] is None and key[0] in specialised)),
            key=lambda item: (item[0], item[1] or ""),
        )
        for key in keys:
            channel, car_id = key
            expectation = self.expectation_for(channel, car_id)
            state = self._states.get(key, _ChannelState())
            period = expectation.expected_period_s if expectation else None
            entries.append(self._classify(channel, car_id, state, period, now_s, expectation))
            gaps.extend(state.gaps)
        heartbeat_age = None if self._last_heartbeat_s is None else max(0.0, now_s - self._last_heartbeat_s)
        return QualityAssessment(
            at_s=now_s,
            channels=tuple(entries),
            integration_gaps=tuple(gaps),
            heartbeat_age_s=heartbeat_age,
        )

    def _classify(
        self,
        channel: str,
        car_id: str | None,
        state: _ChannelState,
        period: float | None,
        now_s: float,
        expectation: ChannelExpectation | None,
    ) -> ChannelQuality:
        if state.observation_count == 0 or state.last_session_time_s is None:
            missing_reason = "no observation received on this channel"
            if expectation is not None and not expectation.measured:
                missing_reason = "channel is declared supported but not measured by this source"
            return ChannelQuality(
                channel=channel,
                car_id=car_id,
                quality=Quality.MISSING,
                last_source_time_s=None,
                age_s=None,
                expected_period_s=period,
                reason=missing_reason,
            )

        raw_age = now_s - state.last_session_time_s
        if raw_age < 0.0:
            return ChannelQuality(
                channel=channel,
                car_id=car_id,
                quality=Quality.INVALID,
                last_source_time_s=state.last_source_time_s,
                age_s=None,
                expected_period_s=period,
                reason=f"last observation is {abs(raw_age):.3f} s in the future of the session clock",
            )

        if state.last_quality in (Quality.MISSING, Quality.INVALID):
            return ChannelQuality(
                channel=channel,
                car_id=car_id,
                quality=state.last_quality,
                last_source_time_s=state.last_source_time_s,
                age_s=raw_age,
                expected_period_s=period,
                reason=state.last_reason or "last sample was rejected by ingestion",
            )

        bounds_reason = self._bounds_reason(channel, state.last_value)
        if bounds_reason is not None:
            return ChannelQuality(
                channel=channel,
                car_id=car_id,
                quality=Quality.INVALID,
                last_source_time_s=state.last_source_time_s,
                age_s=raw_age,
                expected_period_s=period,
                reason=bounds_reason,
            )

        effective_age = raw_age + self.clock_uncertainty_s
        quality = classify_freshness(effective_age, period, **self._thresholds)
        reason: str | None = None
        if quality is not Quality.VALID:
            if period is None:
                reason = "source declared no cadence for this channel"
            else:
                reason = (
                    f"last observation is {raw_age:.3f} s old "
                    f"({effective_age / period:.1f} expected periods including "
                    f"{self.clock_uncertainty_s:.3f} s clock uncertainty)"
                )
        if state.cumulative_gap_s > 0.0:
            gap_note = f"integration_gap_s={state.cumulative_gap_s:.3f}"
            reason = f"{reason}; {gap_note}" if reason else gap_note
            if quality is Quality.VALID:
                quality = Quality.DEGRADED
        return ChannelQuality(
            channel=channel,
            car_id=car_id,
            quality=quality,
            last_source_time_s=state.last_source_time_s,
            age_s=raw_age,
            expected_period_s=period,
            reason=reason,
        )

    @staticmethod
    def _bounds_reason(channel: str, value: float | None) -> str | None:
        if value is None or not is_registered(channel):
            return None
        spec = channel_spec(channel)
        if spec.lower_bound is not None and value < spec.lower_bound:
            return f"value {value} is below the registered bound {spec.lower_bound} {spec.unit}"
        if spec.upper_bound is not None and value > spec.upper_bound:
            return f"value {value} is above the registered bound {spec.upper_bound} {spec.unit}"
        return None

    def _resolve_key(self, channel: str, car_id: str | None) -> tuple[str, str | None]:
        """Observations are always keyed by the car that produced them.

        A ``(channel, None)`` expectation is a per-source template that applies
        to every car; it does not merge the cars into one state.
        """
        return (channel, car_id)


def expectations_from_capability(
    capability: SourceCapability, car_id: str | None = None
) -> tuple[ChannelExpectation, ...]:
    """Build expectations straight from a source's own declared cadence.

    A 3.7 Hz public feed is therefore judged against 3.7 Hz, never against a
    20 Hz simulator's expectations.
    """
    result: list[ChannelExpectation] = []
    for channel in capability.supported_channels:
        rate = capability.update_rates_hz.get(channel)
        if rate is None:
            continue
        result.append(
            ChannelExpectation(
                channel=channel,
                expected_rate_hz=rate,
                car_id=car_id,
                measured=channel in capability.measured_channels,
            )
        )
    return tuple(result)


__all__ = [
    "INTEGRATING_CHANNELS",
    "ChannelExpectation",
    "IntegrationGapRecord",
    "QualityAssessment",
    "QualityTracker",
    "expectations_from_capability",
]
