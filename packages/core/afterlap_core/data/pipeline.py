"""The ingestion pipeline, as separable stages.

    parse -> structural validation -> source timestamp conversion -> SI
    conversion -> deduplication -> bounded reorder -> assign session sequence ->
    quality classification -> append raw/normalised -> publish

Each stage is a function or small class that can be tested on its own; the
:class:`IngestionPipeline` is only the wiring. The properties that matter:

* the reorder window is configured per source, closes on a clock rather than on
  the arrival of a missing packet, and reports the latency it induced;
* deduplication keys on ``(source_id, epoch, source_sequence)`` and additionally
  refuses any post-restart packet whose source time was already accepted, so a
  restarted adapter cannot replay old packets as new ones;
* session sequence numbers are monotonic per session and never reused, even
  when several sources interleave;
* a record that arrives after a decision cutoff is archived with an
  ``out_of_order`` label and excluded from the finalised decision state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from afterlap_contracts import (
    SCHEMA_VERSION,
    ChannelQuality,
    Provenance,
    Quality,
    RawSourcePacket,
    SourceCapability,
    TelemetryEvent,
    channel as channel_spec,
)

from .mapping import MappingError, MappingTable
from .quality import (
    ChannelExpectation,
    IntegrationGapRecord,
    QualityAssessment,
    QualityTracker,
    expectations_from_capability,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from afterlap_core.timebase import ClockMapping

    from .adapters import ObservationRecord


LABEL_OUT_OF_ORDER = "out_of_order"
LABEL_EXCLUDED_FROM_FINALISED = "excluded_from_finalised_state"
LABEL_LATE_AFTER_WINDOW = "late_after_reorder_window"
LABEL_BACKWARDS_CLOCK = "backwards_source_clock"
LABEL_OUT_OF_BOUNDS = "out_of_registered_bounds"
LABEL_MISSING_VALUE = "missing_value"
LABEL_UNMAPPED_FIELD = "unmapped_vendor_field"
LABEL_FORBIDDEN_FIELD = "forbidden_vendor_field"


class RejectionReason(StrEnum):
    """Why a whole record never became normalised events."""

    DUPLICATE = "duplicate"
    RESTART_REPLAY = "restart_replay"
    STRUCTURAL = "structural"


@dataclass(frozen=True, slots=True)
class StructuralIssue:
    field_name: str
    detail: str


@dataclass(frozen=True, slots=True)
class MappedField:
    """One vendor field after SI conversion, before ordering or sequencing."""

    vendor_field: str
    channel: str
    unit: str
    value: float | None
    raw_value: Any
    labels: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    """Result of parse + structural validation for one observation record."""

    record: ObservationRecord
    raw_packet: RawSourcePacket
    unmapped_fields: tuple[str, ...]
    forbidden_fields: tuple[str, ...]
    issues: tuple[StructuralIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def parse_record(record: ObservationRecord, mapping: MappingTable, *, received_time_s: float) -> ParsedRecord:
    """Stage 1: split vendor fields into mapped, unmapped and forbidden.

    The full vendor payload -- mapped or not -- is preserved in the raw packet.
    Nothing is dropped and nothing is guessed.
    """
    unmapped: list[str] = []
    forbidden: list[str] = []
    for name in record.field_names():
        if mapping.is_forbidden(name):
            forbidden.append(name)
        elif not mapping.is_mapped(name):
            unmapped.append(name)
    raw_packet = RawSourcePacket(
        packet_id=raw_packet_id(record),
        source_id=record.source_id,
        received_time_s=max(0.0, received_time_s),
        fields={k: _as_raw(v) for k, v in record.fields.items()},
        mapping_revision=mapping.mapping_revision,
    )
    return ParsedRecord(
        record=record,
        raw_packet=raw_packet,
        unmapped_fields=tuple(sorted(unmapped)),
        forbidden_fields=tuple(sorted(forbidden)),
        issues=validate_structure(record),
    )


def raw_packet_id(record: ObservationRecord) -> str:
    return f"{record.source_id}:{record.car_id}:{record.source_sequence}"


def _as_raw(value: Any) -> float | int | str | bool | None:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    return str(value)


def validate_structure(record: ObservationRecord) -> tuple[StructuralIssue, ...]:
    """Stage 2: everything checkable without units or clocks."""
    issues: list[StructuralIssue] = []
    if not record.source_id:
        issues.append(StructuralIssue("source_id", "empty source id"))
    if not record.car_id:
        issues.append(StructuralIssue("car_id", "empty car id"))
    if not isinstance(record.source_sequence, int) or isinstance(record.source_sequence, bool):
        issues.append(StructuralIssue("source_sequence", "sequence is not an integer"))
    elif record.source_sequence < 0:
        issues.append(StructuralIssue("source_sequence", "sequence is negative"))
    if not isinstance(record.source_time_s, int | float) or isinstance(record.source_time_s, bool):
        issues.append(StructuralIssue("source_time_s", "source time is not numeric"))
    elif not math.isfinite(record.source_time_s):
        issues.append(StructuralIssue("source_time_s", "source time is not finite"))
    if not record.fields:
        issues.append(StructuralIssue("fields", "packet carries no fields"))
    return tuple(issues)


@dataclass(frozen=True, slots=True)
class TimeConversion:
    session_time_s: float
    backwards: bool
    previous_source_time_s: float | None
    uncertainty_s: float

    @property
    def label(self) -> str | None:
        return LABEL_BACKWARDS_CLOCK if self.backwards else None


class SourceClockConverter:
    """Stage 3: map source time to session time and detect a backwards clock.

    A source clock that steps backwards is labelled and surfaced. It is never
    silently accepted, and it never rewrites the session clock.
    """

    def __init__(self, mapping: ClockMapping, *, tolerance_s: float = 0.0) -> None:
        self._mapping = mapping
        self._tolerance_s = tolerance_s
        self._last_source_time_s: dict[str, float] = {}
        self.backwards_count = 0

    @property
    def mapping(self) -> ClockMapping:
        return self._mapping

    def convert(self, record: ObservationRecord) -> TimeConversion:
        key = record.car_id
        previous = self._last_source_time_s.get(key)
        backwards = previous is not None and record.source_time_s < previous - self._tolerance_s
        if backwards:
            self.backwards_count += 1
        else:
            self._last_source_time_s[key] = record.source_time_s
        session_time_s = max(0.0, self._mapping.to_session_time(record.source_time_s))
        return TimeConversion(
            session_time_s=session_time_s,
            backwards=backwards,
            previous_source_time_s=previous,
            uncertainty_s=self._mapping.uncertainty_s,
        )


def convert_to_si(parsed: ParsedRecord, mapping: MappingTable) -> tuple[MappedField, ...]:
    """Stage 4: vendor units to registry SI units, with bounds checking.

    A value outside the channel's registered bounds becomes ``INVALID`` with a
    reason; a sentinel or absent value becomes ``None`` with ``MISSING``. Neither
    is ever replaced by zero.
    """
    fields: list[MappedField] = []
    for name in sorted(parsed.record.field_names()):
        entry = mapping.get(name) if not mapping.is_forbidden(name) else None
        if entry is None:
            continue
        try:
            si_value = entry.to_si(parsed.record.fields[name])
        except MappingError as exc:
            fields.append(
                MappedField(
                    vendor_field=name,
                    channel=entry.channel,
                    unit=entry.si_unit,
                    value=None,
                    raw_value=parsed.record.fields[name],
                    labels=(LABEL_MISSING_VALUE,),
                    reason=str(exc),
                )
            )
            continue
        if si_value is None:
            fields.append(
                MappedField(
                    vendor_field=name,
                    channel=entry.channel,
                    unit=entry.si_unit,
                    value=None,
                    raw_value=parsed.record.fields[name],
                    labels=(LABEL_MISSING_VALUE,),
                    reason=f"{name!r} carried a declared missing value; the channel is not zero",
                )
            )
            continue
        spec = channel_spec(entry.channel)
        labels: tuple[str, ...] = ()
        reason: str | None = None
        if spec.lower_bound is not None and si_value < spec.lower_bound:
            labels, reason = (
                (LABEL_OUT_OF_BOUNDS,),
                f"{si_value} {spec.unit} is below the registered bound {spec.lower_bound}",
            )
        elif spec.upper_bound is not None and si_value > spec.upper_bound:
            labels, reason = (
                (LABEL_OUT_OF_BOUNDS,),
                f"{si_value} {spec.unit} is above the registered bound {spec.upper_bound}",
            )
        fields.append(
            MappedField(
                vendor_field=name,
                channel=entry.channel,
                unit=spec.unit,
                value=si_value,
                raw_value=parsed.record.fields[name],
                labels=labels,
                reason=reason,
            )
        )
    return tuple(fields)


@dataclass(frozen=True, slots=True)
class DedupDecision:
    accepted: bool
    reason: RejectionReason | None
    epoch: int
    detail: str | None = None


class DeduplicationIndex:
    """Stage 5: exactly-once admission across restarts.

    Two rules:

    1. an exact ``(source_id, epoch, source_sequence)`` that was already
       admitted is a duplicate. A source that restarts *without* announcing it
       replays its old sequence numbers into the same epoch and is caught here.
    2. an explicit restart marker advances the epoch, which would otherwise make
       every replayed sequence number look brand new. So a restart also arms a
       replay guard at the highest source time already admitted: until the
       source produces something genuinely newer than that, its packets are
       refused as replays.

    Out-of-order delivery inside a reorder window is *not* a dedup concern: a
    sequence lower than the highest admitted is still new data if it was never
    admitted before. Ordering is the reorder buffer's job.
    """

    def __init__(self, *, time_tolerance_s: float = 1e-9) -> None:
        self._epoch: dict[str, int] = {}
        self._seen: set[tuple[str, int, int]] = set()
        self._max_source_time_s: dict[str, float] = {}
        self._replay_guard_s: dict[str, float] = {}
        self._tolerance = time_tolerance_s
        self.duplicate_count = 0
        self.replay_count = 0

    def epoch_of(self, source_id: str) -> int:
        return self._epoch.get(source_id, 0)

    def replay_guard_of(self, source_id: str) -> float | None:
        return self._replay_guard_s.get(source_id)

    def admit(self, record: ObservationRecord) -> DedupDecision:
        source = record.source_id
        epoch = self._epoch.get(source, 0)

        if record.restart_marker:
            epoch += 1
            self._epoch[source] = epoch
            covered = self._max_source_time_s.get(source)
            if covered is not None:
                self._replay_guard_s[source] = covered

        guard = self._replay_guard_s.get(source)
        if guard is not None:
            if record.source_time_s <= guard + self._tolerance:
                self.replay_count += 1
                return DedupDecision(
                    accepted=False,
                    reason=RejectionReason.RESTART_REPLAY,
                    epoch=epoch,
                    detail=(
                        f"packet at source time {record.source_time_s} replays data already "
                        f"admitted up to {guard} before the restart"
                    ),
                )
            del self._replay_guard_s[source]

        key = (source, epoch, record.source_sequence)
        if key in self._seen:
            self.duplicate_count += 1
            return DedupDecision(
                accepted=False,
                reason=RejectionReason.DUPLICATE,
                epoch=epoch,
                detail=f"sequence {record.source_sequence} already admitted in epoch {epoch}",
            )

        self._seen.add(key)
        previous_time = self._max_source_time_s.get(source)
        if previous_time is None or record.source_time_s > previous_time:
            self._max_source_time_s[source] = record.source_time_s
        return DedupDecision(accepted=True, reason=None, epoch=epoch)


@dataclass(frozen=True, slots=True)
class BufferedRecord:
    parsed: ParsedRecord
    fields: tuple[MappedField, ...]
    session_time_s: float
    conversion: TimeConversion
    epoch: int
    arrival_s: float


@dataclass(frozen=True, slots=True)
class ReorderStats:
    """Measured cost of the reorder window."""

    window_s: float
    released: int
    late_after_close: int
    max_induced_latency_s: float
    mean_induced_latency_s: float
    max_reordering_depth: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "window_s": self.window_s,
            "released": self.released,
            "late_after_close": self.late_after_close,
            "max_induced_latency_s": self.max_induced_latency_s,
            "mean_induced_latency_s": self.mean_induced_latency_s,
            "max_reordering_depth": self.max_reordering_depth,
        }


class ReorderBuffer:
    """Stage 6: bounded out-of-order buffering with a hard deadline.

    Two release criteria, both bounded:

    * **session-time watermark** -- a record is released once the newest session
      time seen is at least ``window_s`` beyond it. This is what actually
      reorders a delayed burst.
    * **arrival deadline** -- a record is released once ``window_s`` of
      ingestion time has passed since it arrived, even if nothing newer ever
      shows up. This is why the buffer never blocks indefinitely on a missing
      packet: the window closes on the clock, not on an arrival.

    A record whose session time is already behind the last released one has
    missed its window entirely. It is returned immediately so it can still be
    archived with an ``out_of_order`` label, never silently dropped.
    """

    def __init__(self, window_s: float) -> None:
        if window_s < 0.0:
            raise ValueError("reorder window cannot be negative")
        self.window_s = window_s
        self._pending: list[BufferedRecord] = []
        self._released = 0
        self._late = 0
        self._latency_sum = 0.0
        self._max_latency = 0.0
        self._max_depth = 0
        self._last_released_time_s: float | None = None
        self._max_session_time_s: float | None = None

    def push(self, item: BufferedRecord) -> tuple[bool, BufferedRecord | None]:
        """Add a record. Returns ``(buffered, immediate_late_release)``."""
        if self._last_released_time_s is not None and item.session_time_s < self._last_released_time_s:
            self._late += 1
            return False, item
        self._pending.append(item)
        self._pending.sort(key=lambda entry: (entry.session_time_s, entry.parsed.raw_packet.packet_id))
        self._max_depth = max(self._max_depth, len(self._pending))
        if self._max_session_time_s is None or item.session_time_s > self._max_session_time_s:
            self._max_session_time_s = item.session_time_s
        return True, None

    def release(self, now_s: float) -> tuple[BufferedRecord, ...]:
        """Release everything whose window has closed at ingestion time ``now_s``."""
        if not self._pending:
            return ()
        cut: float | None = None
        if self._max_session_time_s is not None:
            cut = self._max_session_time_s - self.window_s

        deadline = now_s - self.window_s
        timed_out = [entry.session_time_s for entry in self._pending if entry.arrival_s <= deadline]
        if timed_out:
            cut = max(timed_out) if cut is None else max(cut, *timed_out)

        if cut is None:
            return ()
        due = [entry for entry in self._pending if entry.session_time_s <= cut]
        if not due:
            return ()
        self._pending = [entry for entry in self._pending if entry.session_time_s > cut]
        return self._emit(due, now_s)

    def drain(self, now_s: float) -> tuple[BufferedRecord, ...]:
        """Close every open window immediately (end of stream / session stop)."""
        ready, self._pending = self._pending, []
        return self._emit(ready, now_s) if ready else ()

    def _emit(self, ready: list[BufferedRecord], now_s: float) -> tuple[BufferedRecord, ...]:
        ready.sort(key=lambda entry: (entry.session_time_s, entry.parsed.raw_packet.packet_id))
        for entry in ready:
            latency = max(0.0, now_s - entry.arrival_s)
            self._latency_sum += latency
            self._max_latency = max(self._max_latency, latency)
            self._released += 1
            if self._last_released_time_s is None or entry.session_time_s > self._last_released_time_s:
                self._last_released_time_s = entry.session_time_s
        return tuple(ready)

    @property
    def pending(self) -> int:
        return len(self._pending)

    @property
    def latest_pending_arrival_s(self) -> float:
        return max((entry.arrival_s for entry in self._pending), default=0.0)

    def stats(self) -> ReorderStats:
        mean = self._latency_sum / self._released if self._released else 0.0
        return ReorderStats(
            window_s=self.window_s,
            released=self._released,
            late_after_close=self._late,
            max_induced_latency_s=self._max_latency,
            mean_induced_latency_s=mean,
            max_reordering_depth=self._max_depth,
        )


class SequenceAllocator:
    """Stage 7: strictly monotonic session sequence numbers, never reused."""

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ValueError("sequence numbers start at zero")
        self._next = start
        self._issued: int = 0

    def allocate(self) -> int:
        value = self._next
        self._next += 1
        self._issued += 1
        return value

    @property
    def next_sequence(self) -> int:
        return self._next

    @property
    def issued(self) -> int:
        return self._issued


@dataclass(frozen=True, slots=True)
class NormalisedRecord:
    """One canonical event plus the provenance ingestion added to it."""

    event: TelemetryEvent
    session_time_s: float
    source_id: str
    mapping_revision: str
    raw_packet_id: str
    vendor_field: str
    labels: tuple[str, ...] = ()
    reason: str | None = None
    finalised_before_s: float | None = None

    @property
    def usable_for_decisions(self) -> bool:
        """False once the record is excluded from an already-finalised state."""
        return LABEL_EXCLUDED_FROM_FINALISED not in self.labels

    @property
    def out_of_order(self) -> bool:
        return LABEL_OUT_OF_ORDER in self.labels

    def with_labels(self, *labels: str, reason: str | None = None) -> NormalisedRecord:
        merged = tuple(dict.fromkeys((*self.labels, *labels)))
        return NormalisedRecord(
            event=self.event,
            session_time_s=self.session_time_s,
            source_id=self.source_id,
            mapping_revision=self.mapping_revision,
            raw_packet_id=self.raw_packet_id,
            vendor_field=self.vendor_field,
            labels=merged,
            reason=reason or self.reason,
            finalised_before_s=self.finalised_before_s,
        )


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    record: ObservationRecord
    reason: RejectionReason
    detail: str
    raw_packet: RawSourcePacket | None = None


class RecordSink(Protocol):
    """Stage 9: where raw and normalised records are appended."""

    def append_raw(self, packet: RawSourcePacket, *, car_id: str, session_time_s: float) -> None: ...

    def append_normalised(self, record: NormalisedRecord) -> None: ...


@dataclass(slots=True)
class MemorySink:
    """In-memory sink; also the reference implementation of :class:`RecordSink`."""

    raw: list[tuple[RawSourcePacket, str, float]] = field(default_factory=list)
    normalised: list[NormalisedRecord] = field(default_factory=list)

    def append_raw(self, packet: RawSourcePacket, *, car_id: str, session_time_s: float) -> None:
        self.raw.append((packet, car_id, session_time_s))

    def append_normalised(self, record: NormalisedRecord) -> None:
        self.normalised.append(record)


@dataclass(frozen=True, slots=True)
class PipelineOutput:
    """What one ``ingest``/``flush`` call published."""

    normalised: tuple[NormalisedRecord, ...] = ()
    raw: tuple[RawSourcePacket, ...] = ()
    rejected: tuple[RejectedRecord, ...] = ()
    channel_quality: tuple[ChannelQuality, ...] = ()
    integration_gaps: tuple[IntegrationGapRecord, ...] = ()

    def decision_visible(self) -> tuple[NormalisedRecord, ...]:
        return tuple(entry for entry in self.normalised if entry.usable_for_decisions)

    def __add__(self, other: PipelineOutput) -> PipelineOutput:
        return PipelineOutput(
            normalised=self.normalised + other.normalised,
            raw=self.raw + other.raw,
            rejected=self.rejected + other.rejected,
            channel_quality=self.channel_quality + other.channel_quality,
            integration_gaps=self.integration_gaps + other.integration_gaps,
        )


@dataclass(frozen=True, slots=True)
class SourcePipelineConfig:
    """Per-source ingestion configuration.

    ``reorder_window_s`` is per source on purpose: a 3.7 Hz archive needs a very
    different window from a 20 Hz simulator, and the induced latency of each is
    reported separately.
    """

    session_id: str
    source_id: str
    mapping: MappingTable
    capability: SourceCapability
    provenance: Provenance
    clock: ClockMapping
    reorder_window_s: float = 0.2
    expectations: tuple[ChannelExpectation, ...] = ()

    def __post_init__(self) -> None:
        if self.mapping.source_id != self.source_id:
            raise ValueError("mapping table belongs to a different source")
        if self.capability.source_id != self.source_id:
            raise ValueError("capability belongs to a different source")
        if self.reorder_window_s < 0.0:
            raise ValueError("reorder window cannot be negative")


@dataclass(frozen=True, slots=True)
class PipelineStats:
    source_id: str
    records_in: int
    records_admitted: int
    events_published: int
    duplicates: int
    replays: int
    backwards_clock: int
    out_of_order: int
    excluded_from_finalised: int
    reorder: ReorderStats

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "records_in": self.records_in,
            "records_admitted": self.records_admitted,
            "events_published": self.events_published,
            "duplicates": self.duplicates,
            "replays": self.replays,
            "backwards_clock": self.backwards_clock,
            "out_of_order": self.out_of_order,
            "excluded_from_finalised": self.excluded_from_finalised,
            "reorder": self.reorder.as_dict(),
        }


class IngestionPipeline:
    """One source's worth of the pipeline, wired together."""

    def __init__(
        self,
        config: SourcePipelineConfig,
        *,
        sequences: SequenceAllocator | None = None,
        sink: RecordSink | None = None,
        tracker: QualityTracker | None = None,
    ) -> None:
        self.config = config
        self._sequences = sequences or SequenceAllocator()
        self._sink = sink
        expectations = config.expectations or expectations_from_capability(config.capability)
        self._tracker = tracker or QualityTracker(
            expectations, clock_uncertainty_s=config.clock.uncertainty_s
        )
        self._clock = SourceClockConverter(config.clock)
        self._dedup = DeduplicationIndex()
        self._buffer = ReorderBuffer(config.reorder_window_s)
        self._finalised_before_s: float | None = None
        self._records_in = 0
        self._records_admitted = 0
        self._events_published = 0
        self._out_of_order = 0
        self._excluded = 0
        self._horizon_s = 0.0

    @property
    def tracker(self) -> QualityTracker:
        return self._tracker

    @property
    def sequences(self) -> SequenceAllocator:
        return self._sequences

    @property
    def finalised_before_s(self) -> float | None:
        return self._finalised_before_s

    def finalise(self, cutoff_s: float) -> None:
        """Publish a decision cutoff.

        Everything at or before ``cutoff_s`` that arrives from now on is
        archived but excluded from the state that decision observed.
        """
        if self._finalised_before_s is not None and cutoff_s < self._finalised_before_s:
            raise ValueError("a decision cutoff never moves backwards")
        self._finalised_before_s = cutoff_s

    def heartbeat(self, at_s: float) -> None:
        """Transport liveness only; see :mod:`afterlap_core.data.quality`."""
        self._tracker.heartbeat(at_s)

    def ingest(self, record: ObservationRecord, *, now_s: float | None = None) -> PipelineOutput:
        """Run one record through stages 1-6 and release whatever is ready."""
        self._records_in += 1
        arrival = self._arrival_time(record, now_s)

        parsed = parse_record(record, self.config.mapping, received_time_s=arrival)
        if not parsed.ok:
            return PipelineOutput(
                rejected=(
                    RejectedRecord(
                        record=record,
                        reason=RejectionReason.STRUCTURAL,
                        detail="; ".join(f"{i.field_name}: {i.detail}" for i in parsed.issues),
                        raw_packet=parsed.raw_packet,
                    ),
                ),
                raw=(parsed.raw_packet,),
            )

        decision = self._dedup.admit(record)
        if not decision.accepted:
            reason = decision.reason or RejectionReason.DUPLICATE
            return PipelineOutput(
                rejected=(
                    RejectedRecord(
                        record=record,
                        reason=reason,
                        detail=decision.detail or reason.value,
                        raw_packet=parsed.raw_packet,
                    ),
                ),
                raw=(parsed.raw_packet,),
            )
        self._records_admitted += 1

        conversion = self._clock.convert(record)
        fields = convert_to_si(parsed, self.config.mapping)
        buffered = BufferedRecord(
            parsed=parsed,
            fields=fields,
            session_time_s=conversion.session_time_s,
            conversion=conversion,
            epoch=decision.epoch,
            arrival_s=arrival,
        )
        accepted, late = self._buffer.push(buffered)
        output = PipelineOutput()
        if not accepted and late is not None:
            output = output + self._publish((late,), late_release=True)
        released = self._buffer.release(arrival)
        if released:
            output = output + self._publish(released, late_release=False)
        return output

    def flush(self, now_s: float) -> PipelineOutput:
        """Close every window whose deadline has passed at ``now_s``."""
        released = self._buffer.release(now_s)
        return self._publish(released, late_release=False) if released else PipelineOutput()

    def close(self, now_s: float | None = None) -> PipelineOutput:
        """End of stream: drain the buffer rather than waiting for absent packets."""
        at = now_s if now_s is not None else self._buffer_horizon()
        released = self._buffer.drain(at)
        return self._publish(released, late_release=False) if released else PipelineOutput()

    def ingest_all(
        self, records: Iterable[ObservationRecord], *, now_s: float | None = None
    ) -> PipelineOutput:
        output = PipelineOutput()
        for record in records:
            output = output + self.ingest(record, now_s=now_s)
        return output + self.close()

    def _buffer_horizon(self) -> float:
        return self._buffer.latest_pending_arrival_s + self._buffer.window_s

    def _arrival_time(self, record: ObservationRecord, now_s: float | None) -> float:
        if now_s is not None:
            return now_s
        if record.received_time_s is not None:
            return record.received_time_s
        return max(0.0, self.config.clock.to_session_time(record.source_time_s))

    def _publish(self, entries: Sequence[BufferedRecord], *, late_release: bool) -> PipelineOutput:
        normalised: list[NormalisedRecord] = []
        raw: list[RawSourcePacket] = []
        gaps: list[IntegrationGapRecord] = []
        for entry in entries:
            raw.append(entry.parsed.raw_packet)
            if self._sink is not None:
                self._sink.append_raw(
                    entry.parsed.raw_packet,
                    car_id=entry.parsed.record.car_id,
                    session_time_s=entry.session_time_s,
                )
            base_labels: list[str] = []
            base_reason: str | None = None
            if late_release:
                base_labels.append(LABEL_OUT_OF_ORDER)
                base_labels.append(LABEL_LATE_AFTER_WINDOW)
                base_reason = (
                    f"arrived after the {self._buffer.window_s:.3f} s reorder window for "
                    f"session time {entry.session_time_s:.3f} closed"
                )
                self._out_of_order += 1
            if entry.conversion.backwards:
                base_labels.append(LABEL_BACKWARDS_CLOCK)
                previous = entry.conversion.previous_source_time_s
                base_reason = (
                    f"source clock stepped backwards from {previous} to {entry.parsed.record.source_time_s}"
                )
            if entry.parsed.unmapped_fields:
                base_labels.append(LABEL_UNMAPPED_FIELD)
            if entry.parsed.forbidden_fields:
                base_labels.append(LABEL_FORBIDDEN_FIELD)

            for mapped in entry.fields:
                record = self._normalise(entry, mapped, base_labels, base_reason)
                normalised.append(record)
                gap = self._tracker.observe(
                    mapped.channel,
                    session_time_s=entry.session_time_s,
                    source_time_s=entry.parsed.record.source_time_s,
                    car_id=entry.parsed.record.car_id,
                    value=record.event.value,
                    quality=record.event.quality,
                    reason=record.reason,
                )
                if gap is not None:
                    gaps.append(gap)
                if self._sink is not None:
                    self._sink.append_normalised(record)
        self._events_published += len(normalised)
        if entries:
            self._horizon_s = max(self._horizon_s, *(entry.session_time_s for entry in entries))
        quality = self._tracker.assess(self._horizon_s).channels if entries else ()
        return PipelineOutput(
            normalised=tuple(normalised),
            raw=tuple(raw),
            channel_quality=quality,
            integration_gaps=tuple(gaps),
        )

    def _normalise(
        self,
        entry: BufferedRecord,
        mapped: MappedField,
        base_labels: Sequence[str],
        base_reason: str | None,
    ) -> NormalisedRecord:
        labels = list(dict.fromkeys((*base_labels, *mapped.labels)))
        reason = mapped.reason or base_reason

        quality = Quality.VALID
        value = mapped.value
        if entry.conversion.backwards:
            quality = Quality.INVALID
        if LABEL_OUT_OF_BOUNDS in mapped.labels:
            quality = Quality.INVALID
        if value is None:
            quality = Quality.MISSING
            if not reason:
                reason = f"{mapped.vendor_field!r} produced no value; the channel is missing, not zero"

        cutoff = self._finalised_before_s
        if cutoff is not None and entry.session_time_s <= cutoff:
            labels.append(LABEL_OUT_OF_ORDER)
            labels.append(LABEL_EXCLUDED_FROM_FINALISED)
            self._excluded += 1
            reason = (
                f"{reason}; " if reason else ""
            ) + f"arrived after the decision cutoff at session time {cutoff:.3f} s"

        sequence = self._sequences.allocate()
        event = TelemetryEvent(
            schema_version=SCHEMA_VERSION,
            event_id=f"{entry.parsed.raw_packet.packet_id}:{mapped.vendor_field}:e{entry.epoch}",
            session_id=self.config.session_id,
            car_id=entry.parsed.record.car_id,
            sequence=sequence,
            source_time_s=max(0.0, entry.parsed.record.source_time_s),
            received_time_s=max(0.0, entry.arrival_s),
            channel=mapped.channel,
            value=value,
            unit=mapped.unit,
            provenance=self.config.provenance,
            quality=quality,
        )
        return NormalisedRecord(
            event=event,
            session_time_s=entry.session_time_s,
            source_id=self.config.source_id,
            mapping_revision=self.config.mapping.mapping_revision,
            raw_packet_id=entry.parsed.raw_packet.packet_id,
            vendor_field=mapped.vendor_field,
            labels=tuple(dict.fromkeys(labels)),
            reason=reason,
            finalised_before_s=cutoff,
        )

    def stats(self) -> PipelineStats:
        return PipelineStats(
            source_id=self.config.source_id,
            records_in=self._records_in,
            records_admitted=self._records_admitted,
            events_published=self._events_published,
            duplicates=self._dedup.duplicate_count,
            replays=self._dedup.replay_count,
            backwards_clock=self._clock.backwards_count,
            out_of_order=self._out_of_order,
            excluded_from_finalised=self._excluded,
            reorder=self._buffer.stats(),
        )

    def assess_quality(self, now_s: float) -> QualityAssessment:
        return self._tracker.assess(now_s)


class IngestionRouter:
    """Several sources sharing one session sequence space.

    The shared :class:`SequenceAllocator` is what makes sequence numbers
    monotonic and unique across arbitrary interleaving of sources.
    """

    def __init__(self, configs: Iterable[SourcePipelineConfig], *, sink: RecordSink | None = None) -> None:
        self.sequences = SequenceAllocator()
        self._pipelines: dict[str, IngestionPipeline] = {}
        for config in configs:
            if config.source_id in self._pipelines:
                raise ValueError(f"duplicate source pipeline for {config.source_id!r}")
            self._pipelines[config.source_id] = IngestionPipeline(config, sequences=self.sequences, sink=sink)

    def __getitem__(self, source_id: str) -> IngestionPipeline:
        return self._pipelines[source_id]

    @property
    def pipelines(self) -> Mapping[str, IngestionPipeline]:
        return dict(self._pipelines)

    def ingest(self, record: ObservationRecord, *, now_s: float | None = None) -> PipelineOutput:
        try:
            pipeline = self._pipelines[record.source_id]
        except KeyError as exc:
            raise KeyError(f"no pipeline configured for source {record.source_id!r}") from exc
        return pipeline.ingest(record, now_s=now_s)

    def finalise(self, cutoff_s: float) -> None:
        for pipeline in self._pipelines.values():
            pipeline.finalise(cutoff_s)

    def flush(self, now_s: float) -> PipelineOutput:
        output = PipelineOutput()
        for pipeline in self._pipelines.values():
            output = output + pipeline.flush(now_s)
        return output

    def close(self, now_s: float | None = None) -> PipelineOutput:
        output = PipelineOutput()
        for pipeline in self._pipelines.values():
            output = output + pipeline.close(now_s)
        return output

    def stats(self) -> tuple[PipelineStats, ...]:
        return tuple(pipeline.stats() for pipeline in self._pipelines.values())


def sort_normalised(records: Iterable[NormalisedRecord]) -> tuple[NormalisedRecord, ...]:
    """Canonical ordering for comparison: session time, then session sequence."""
    return tuple(sorted(records, key=lambda item: (item.session_time_s, item.event.sequence)))


def iter_decision_visible(records: Iterable[NormalisedRecord]) -> Iterator[NormalisedRecord]:
    for record in records:
        if record.usable_for_decisions:
            yield record


__all__ = [
    "LABEL_BACKWARDS_CLOCK",
    "LABEL_EXCLUDED_FROM_FINALISED",
    "LABEL_FORBIDDEN_FIELD",
    "LABEL_LATE_AFTER_WINDOW",
    "LABEL_MISSING_VALUE",
    "LABEL_OUT_OF_BOUNDS",
    "LABEL_OUT_OF_ORDER",
    "LABEL_UNMAPPED_FIELD",
    "BufferedRecord",
    "DedupDecision",
    "DeduplicationIndex",
    "IngestionPipeline",
    "IngestionRouter",
    "MappedField",
    "MemorySink",
    "NormalisedRecord",
    "ParsedRecord",
    "PipelineOutput",
    "PipelineStats",
    "RecordSink",
    "RejectedRecord",
    "RejectionReason",
    "ReorderBuffer",
    "ReorderStats",
    "SequenceAllocator",
    "SourceClockConverter",
    "SourcePipelineConfig",
    "StructuralIssue",
    "TimeConversion",
    "convert_to_si",
    "iter_decision_visible",
    "parse_record",
    "raw_packet_id",
    "sort_normalised",
    "validate_structure",
]
