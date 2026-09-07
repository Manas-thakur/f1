"""WebSocket envelope and the discriminated union of stream payloads.

One envelope, one monotonic sequence per session. A client that sees a gap must
resynchronise from a snapshot rather than applying a delta to the wrong state.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .base import Contract, VersionedContract
from .enums import StreamEventType
from .estimate import StateEstimate
from .lifecycle import ExecutionEvent
from .planning import Recommendation
from .rules import RuleContext
from .session import SessionSnapshot
from .telemetry import ChannelQuality


class TelemetrySeries(Contract):
    """A downsampled numeric trace for display.

    ``sample_count`` is the original resolution; downsampling must preserve
    extrema and event crossings, and exact inspection uses the raw arrays held
    server-side.
    """

    channel: str = Field(min_length=1)
    car_id: str | None = None
    unit: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    x_coordinate: Literal["progress_m", "session_time_s"]
    x: tuple[float, ...] = ()
    y: tuple[float | None, ...] = ()
    y_low: tuple[float | None, ...] | None = None
    y_high: tuple[float | None, ...] | None = None
    quantile_definition: str | None = None
    sample_count: int = Field(default=0, ge=0)
    decimated: bool = False

    @model_validator(mode="after")
    def _aligned_arrays(self) -> TelemetrySeries:
        if len(self.x) != len(self.y):
            raise ValueError("series x and y lengths differ")
        for band in (self.y_low, self.y_high):
            if band is not None and len(band) != len(self.x):
                raise ValueError("series uncertainty band length differs from x")
        if (self.y_low is None) != (self.y_high is None):
            raise ValueError("an uncertainty band needs both bounds")
        if self.y_low is not None and self.quantile_definition is None:
            raise ValueError("a band must declare what its bounds mean")
        return self


class SnapshotPayload(Contract):
    event_type: Literal[StreamEventType.SNAPSHOT] = StreamEventType.SNAPSHOT
    snapshot: SessionSnapshot


class TelemetryViewPayload(Contract):
    event_type: Literal[StreamEventType.TELEMETRY_VIEW] = StreamEventType.TELEMETRY_VIEW
    series: tuple[TelemetrySeries, ...]
    coalesced_from_sequence: int | None = Field(
        default=None, ge=0, description="Set when several updates were merged; decisions are never merged."
    )
    coalesced_to_sequence: int | None = Field(default=None, ge=0)


class EstimateUpdatedPayload(Contract):
    event_type: Literal[StreamEventType.ESTIMATE_UPDATED] = StreamEventType.ESTIMATE_UPDATED
    estimate: StateEstimate


class RecommendationUpdatedPayload(Contract):
    event_type: Literal[StreamEventType.RECOMMENDATION_UPDATED] = StreamEventType.RECOMMENDATION_UPDATED
    recommendation: Recommendation


class ExecutionObservedPayload(Contract):
    event_type: Literal[StreamEventType.EXECUTION_OBSERVED] = StreamEventType.EXECUTION_OBSERVED
    execution: ExecutionEvent


class RuleContextChangedPayload(Contract):
    event_type: Literal[StreamEventType.RULE_CONTEXT_CHANGED] = StreamEventType.RULE_CONTEXT_CHANGED
    rule_context: RuleContext
    invalidated_recommendation_ids: tuple[str, ...] = ()


class QualityChangedPayload(Contract):
    event_type: Literal[StreamEventType.QUALITY_CHANGED] = StreamEventType.QUALITY_CHANGED
    channels: tuple[ChannelQuality, ...] = ()
    message: str | None = None


class ExperimentProgressPayload(Contract):
    event_type: Literal[StreamEventType.EXPERIMENT_PROGRESS] = StreamEventType.EXPERIMENT_PROGRESS
    experiment_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    progress: float = Field(ge=0.0, le=1.0)
    detail: str | None = None


class HeartbeatPayload(Contract):
    """Proves the connection exists. It says nothing about telemetry freshness."""

    event_type: Literal[StreamEventType.HEARTBEAT] = StreamEventType.HEARTBEAT
    server_uptime_s: float = Field(ge=0.0)


class ResyncRequiredPayload(Contract):
    event_type: Literal[StreamEventType.RESYNC_REQUIRED] = StreamEventType.RESYNC_REQUIRED
    reason: str = Field(min_length=1)
    earliest_available_sequence: int = Field(ge=0)


StreamPayload = Annotated[
    SnapshotPayload
    | TelemetryViewPayload
    | EstimateUpdatedPayload
    | RecommendationUpdatedPayload
    | ExecutionObservedPayload
    | RuleContextChangedPayload
    | QualityChangedPayload
    | ExperimentProgressPayload
    | HeartbeatPayload
    | ResyncRequiredPayload,
    Field(discriminator="event_type"),
]


class StreamEnvelope(VersionedContract):
    """The single wire envelope for every session stream message."""

    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event_type: StreamEventType
    session_time_s: float = Field(ge=0.0)
    payload: StreamPayload

    @model_validator(mode="after")
    def _envelope_matches_payload(self) -> StreamEnvelope:
        if self.payload.event_type is not self.event_type:
            raise ValueError(
                f"envelope event_type {self.event_type} disagrees with payload {self.payload.event_type}"
            )
        return self

    @property
    def is_lossless(self) -> bool:
        """Decision, quality and operator events may never be dropped or coalesced."""
        return self.event_type not in (
            StreamEventType.TELEMETRY_VIEW,
            StreamEventType.HEARTBEAT,
        )


StreamEnvelopeAdapter: TypeAdapter[StreamEnvelope] = TypeAdapter(StreamEnvelope)


__all__ = [
    "EstimateUpdatedPayload",
    "ExecutionObservedPayload",
    "ExperimentProgressPayload",
    "HeartbeatPayload",
    "QualityChangedPayload",
    "RecommendationUpdatedPayload",
    "ResyncRequiredPayload",
    "RuleContextChangedPayload",
    "SnapshotPayload",
    "StreamEnvelope",
    "StreamEnvelopeAdapter",
    "StreamPayload",
    "TelemetrySeries",
    "TelemetryViewPayload",
]
