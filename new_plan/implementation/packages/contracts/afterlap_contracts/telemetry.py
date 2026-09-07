"""Source capability declaration, telemetry wire events and quality events.

``TelemetryEvent`` is normatively seeded by
``01_contracts/schemas/telemetry-event.schema.json``; the generated schema is
checked against that file by the contract test suite.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import CapabilityState, Provenance, Quality, SessionMode


class SourceCapability(Contract):
    """What a telemetry source can actually supply.

    ``supported_channels`` is what the adapter can map; ``measured_channels`` is
    the subset backed by real measurement rather than configuration or model
    output. Declaring a channel supported does not make it measured.
    """

    source_id: str = Field(min_length=1)
    mode: SessionMode
    supported_channels: tuple[str, ...] = Field(default=())
    measured_channels: tuple[str, ...] = Field(default=())
    update_rates_hz: dict[str, float] = Field(default_factory=dict)
    clock_error_s: float = Field(ge=0.0, description="Bound on source-to-session clock error.")
    limitations: tuple[str, ...] = Field(
        default=(),
        description="Plain-language limits, e.g. 'no battery-energy channel', 'lateral position unreliable'.",
    )
    license_note: str | None = None

    @model_validator(mode="after")
    def _measured_is_a_subset(self) -> SourceCapability:
        unsupported = set(self.measured_channels) - set(self.supported_channels)
        if unsupported:
            raise ValueError(f"measured channels not in supported set: {sorted(unsupported)}")
        unknown_rates = set(self.update_rates_hz) - set(self.supported_channels)
        if unknown_rates:
            raise ValueError(f"update rates declared for unsupported channels: {sorted(unknown_rates)}")
        for channel, rate in self.update_rates_hz.items():
            if rate <= 0.0:
                raise ValueError(f"update rate for {channel} must be positive")
        return self

    def provides(self, channel: str) -> bool:
        return channel in self.supported_channels

    def measures(self, channel: str) -> bool:
        return channel in self.measured_channels


class TelemetryEvent(VersionedContract):
    """One canonical channel sample after normalisation.

    Field order and constraints mirror the normative JSON schema. ``value`` may
    be ``None`` for an explicitly missing sample; ``quality`` must then say so.
    """

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    car_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    source_time_s: float = Field(ge=0.0)
    received_time_s: float = Field(ge=0.0)
    channel: str = Field(min_length=1)
    value: float | None
    unit: str
    provenance: Provenance
    quality: Quality

    @model_validator(mode="after")
    def _null_value_is_explained(self) -> TelemetryEvent:
        if self.value is None and self.quality in (Quality.VALID, Quality.DEGRADED, Quality.STALE):
            raise ValueError("a null telemetry value requires quality=missing or invalid")
        return self


class RawSourcePacket(Contract):
    """An unmapped vendor packet retained for archival and later re-mapping.

    Unmapped fields are preserved rather than guessed at import time.
    """

    packet_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    received_time_s: float = Field(ge=0.0)
    fields: dict[str, float | int | str | bool | None]
    mapping_revision: str | None = None


class ChannelQuality(Contract):
    """Per-channel freshness assessment, derived from observations only.

    Freshness is never inferred from a WebSocket heartbeat.
    """

    channel: str = Field(min_length=1)
    car_id: str | None = None
    quality: Quality
    last_source_time_s: float | None = None
    age_s: float | None = Field(default=None, ge=0.0)
    expected_period_s: float | None = Field(default=None, gt=0.0)
    reason: str | None = None


class QualityEvent(VersionedContract):
    """A change in source or capability health, published losslessly to clients."""

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    session_time_s: float = Field(ge=0.0)
    channels: tuple[ChannelQuality, ...] = ()
    capability_states: dict[str, CapabilityState] = Field(default_factory=dict)
    message: str | None = None


class TelemetryChunkManifest(Contract):
    """Immutable descriptor of a completed Parquet chunk.

    Readers consume only chunks that appear here, which is what makes the
    staging-then-manifest write atomic from a reader's point of view.
    """

    chunk_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    car_id: str | None = None
    channel_family: str = Field(min_length=1)
    start_session_time_s: float = Field(ge=0.0)
    end_session_time_s: float = Field(ge=0.0)
    row_count: int = Field(ge=0)
    path: str = Field(min_length=1)
    mapping_revision: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_window(self) -> TelemetryChunkManifest:
        if self.end_session_time_s < self.start_session_time_s:
            raise ValueError("chunk end precedes its start")
        return self


__all__ = [
    "ChannelQuality",
    "QualityEvent",
    "RawSourcePacket",
    "SourceCapability",
    "TelemetryChunkManifest",
    "TelemetryEvent",
]
