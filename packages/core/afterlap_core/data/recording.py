"""Parquet recording, chunk manifests, acquisition provenance and redaction.

Layout under ``<root>/sessions/<session_id>/``::

    raw/car=<car>/family=<family>/chunk=<n>/part.parquet
    canonical/car=<car>/family=<family>/chunk=<n>/part.parquet
    manifest.json
    acquisition.json

Raw vendor packets and canonical normalised records are kept apart and each
chunk carries the mapping revision that produced it, so re-mapping later is a
new canonical chunk over the same immutable raw data.

Writes go to a task-owned staging file first; a chunk becomes visible only when
its descriptor is added to the manifest, and the manifest itself is replaced
atomically. A reader therefore never sees a partially written import.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import pyarrow as pa
import pyarrow.parquet as pq

from afterlap_contracts import (
    SCHEMA_VERSION,
    Provenance,
    Quality,
    RawSourcePacket,
    TelemetryChunkManifest,
    TelemetryEvent,
    channel as channel_spec,
)
from afterlap_core.paths import atomic_write_bytes, sha256_bytes

from .mapping import SECRET_NAME_PATTERN
from .pipeline import NormalisedRecord

REDACTED = "[redacted]"
RAW_FAMILY = "raw"
MANIFEST_NAME = "manifest.json"
ACQUISITION_NAME = "acquisition.json"

_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{6,}")
_COOKIE_LINE = re.compile(r"(?i)\b((?:set-)?cookie)\s*[:=]\s*[^\s;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential|signature)"
    r"\s*[=:]\s*[\"']?[^\s\"',;&]+"
)
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+")


def redact_text(text: str) -> str:
    """Remove credential-looking material from a free-text string.

    Applied to every string this module writes or logs. It is a safety net, not
    a licence to pass secrets around.
    """
    redacted = _URL.sub(lambda m: redact_url(m.group(0)), text)
    redacted = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", redacted)
    redacted = _COOKIE_LINE.sub(lambda m: f"{m.group(1)}: {REDACTED}", redacted)
    return _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", redacted)


def redact_url(url: str) -> str:
    """Strip userinfo and secret query parameters from a URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return REDACTED
    if not parts.scheme:
        return url
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{REDACTED}@{netloc.rsplit('@', 1)[1]}"
    query_pairs = [
        (key, REDACTED if SECRET_NAME_PATTERN.search(key) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    query = "&".join(f"{key}={value}" for key, value in query_pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively replace secret-looking values with ``[redacted]``."""
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if SECRET_NAME_PATTERN.search(str(key)):
            result[key] = REDACTED
        elif isinstance(value, Mapping):
            result[key] = redact_mapping(value)
        elif isinstance(value, list | tuple):
            result[key] = [
                redact_mapping(item)
                if isinstance(item, Mapping)
                else (redact_text(item) if isinstance(item, str) else item)
                for item in value
            ]
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    """Where a recorded session came from and under what terms."""

    source_id: str
    source_url: str
    license_note: str
    terms_review_status: str
    retrieved_at: str
    mapping_revision: str
    synthetic: bool
    note: str | None = None
    config: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": redact_url(self.source_url),
            "license_note": redact_text(self.license_note),
            "terms_review_status": self.terms_review_status,
            "retrieved_at": self.retrieved_at,
            "mapping_revision": self.mapping_revision,
            "synthetic": self.synthetic,
            "note": redact_text(self.note) if self.note else None,
            "config": redact_mapping(self.config),
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


CANONICAL_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string()),
        pa.field("event_id", pa.string()),
        pa.field("session_id", pa.string()),
        pa.field("car_id", pa.string()),
        pa.field("sequence", pa.int64()),
        pa.field("source_time_s", pa.float64()),
        pa.field("received_time_s", pa.float64()),
        pa.field("session_time_s", pa.float64()),
        pa.field("channel", pa.string()),
        pa.field("value", pa.float64()),
        pa.field("unit", pa.string()),
        pa.field("provenance", pa.string()),
        pa.field("quality", pa.string()),
        pa.field("source_id", pa.string()),
        pa.field("mapping_revision", pa.string()),
        pa.field("raw_packet_id", pa.string()),
        pa.field("vendor_field", pa.string()),
        pa.field("labels", pa.list_(pa.string())),
        pa.field("reason", pa.string()),
        pa.field("finalised_before_s", pa.float64()),
    ]
)

RAW_SCHEMA = pa.schema(
    [
        pa.field("packet_id", pa.string()),
        pa.field("source_id", pa.string()),
        pa.field("car_id", pa.string()),
        pa.field("received_time_s", pa.float64()),
        pa.field("session_time_s", pa.float64()),
        pa.field("mapping_revision", pa.string()),
        pa.field("fields_json", pa.string()),
    ]
)


@dataclass(frozen=True, slots=True)
class PendingChunk:
    """A staged chunk that is on disk but not yet visible to readers."""

    descriptor: TelemetryChunkManifest
    staging_path: Path
    final_path: Path
    kind: str


@dataclass(slots=True)
class _Bucket:
    car_id: str
    family: str
    chunk_index: int
    rows: list[dict[str, Any]] = field(default_factory=list)


class TelemetryRecorder:
    """Chunked Parquet recorder implementing the ``RecordSink`` protocol."""

    def __init__(
        self,
        root: Path | str,
        session_id: str,
        *,
        mapping_revision: str,
        chunk_duration_s: float = 10.0,
    ) -> None:
        if chunk_duration_s <= 0.0:
            raise ValueError("chunk duration must be positive")
        self.root = Path(root)
        self.session_id = session_id
        self.mapping_revision = mapping_revision
        self.chunk_duration_s = chunk_duration_s
        self.session_root = self.root / "sessions" / session_id
        self._canonical: dict[tuple[str, str, int], _Bucket] = {}
        self._raw: dict[tuple[str, str, int], _Bucket] = {}
        self._published: list[TelemetryChunkManifest] = []
        self._chunk_serial = 0

    def append_normalised(self, record: NormalisedRecord) -> None:
        event = record.event
        family = channel_spec(event.channel).family
        bucket = self._bucket(self._canonical, event.car_id, family, record.session_time_s)
        bucket.rows.append(
            {
                "schema_version": event.schema_version,
                "event_id": event.event_id,
                "session_id": event.session_id,
                "car_id": event.car_id,
                "sequence": int(event.sequence),
                "source_time_s": float(event.source_time_s),
                "received_time_s": float(event.received_time_s),
                "session_time_s": float(record.session_time_s),
                "channel": event.channel,
                "value": event.value,
                "unit": event.unit,
                "provenance": event.provenance.value,
                "quality": event.quality.value,
                "source_id": record.source_id,
                "mapping_revision": record.mapping_revision,
                "raw_packet_id": record.raw_packet_id,
                "vendor_field": record.vendor_field,
                "labels": list(record.labels),
                "reason": record.reason,
                "finalised_before_s": record.finalised_before_s,
            }
        )

    def append_raw(self, packet: RawSourcePacket, *, car_id: str, session_time_s: float) -> None:
        bucket = self._bucket(self._raw, car_id, RAW_FAMILY, session_time_s)
        bucket.rows.append(
            {
                "packet_id": packet.packet_id,
                "source_id": packet.source_id,
                "car_id": car_id,
                "received_time_s": float(packet.received_time_s),
                "session_time_s": float(session_time_s),
                "mapping_revision": packet.mapping_revision or self.mapping_revision,
                "fields_json": json.dumps(dict(packet.fields), sort_keys=True, default=str),
            }
        )

    def _bucket(
        self,
        store: dict[tuple[str, str, int], _Bucket],
        car_id: str,
        family: str,
        session_time_s: float,
    ) -> _Bucket:
        index = int(max(0.0, session_time_s) // self.chunk_duration_s)
        key = (car_id, family, index)
        if key not in store:
            store[key] = _Bucket(car_id=car_id, family=family, chunk_index=index)
        return store[key]

    def stage(self) -> tuple[PendingChunk, ...]:
        """Write buffered rows to staging files. Nothing becomes visible yet."""
        pending: list[PendingChunk] = []
        pending.extend(self._stage_store(self._canonical, "canonical", CANONICAL_SCHEMA))
        pending.extend(self._stage_store(self._raw, RAW_FAMILY, RAW_SCHEMA))
        self._canonical.clear()
        self._raw.clear()
        return tuple(pending)

    def _stage_store(
        self,
        store: dict[tuple[str, str, int], _Bucket],
        kind: str,
        schema: pa.Schema,
    ) -> list[PendingChunk]:
        pending: list[PendingChunk] = []
        for key in sorted(store):
            bucket = store[key]
            if not bucket.rows:
                continue
            table = pa.Table.from_pylist(bucket.rows, schema=schema)
            sink = pa.BufferOutputStream()
            pq.write_table(table, sink, compression="snappy")
            payload = sink.getvalue().to_pybytes()
            digest = sha256_bytes(payload)
            relative = (
                Path(kind)
                / f"car={bucket.car_id}"
                / f"family={bucket.family}"
                / f"chunk={bucket.chunk_index:06d}"
                / "part.parquet"
            )
            final_path = self.session_root / relative
            self._chunk_serial += 1
            staging_path = final_path.parent / f".part-{self._chunk_serial:06d}.staging.parquet"
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.write_bytes(payload)
            times = [float(row["session_time_s"]) for row in bucket.rows]
            descriptor = TelemetryChunkManifest(
                chunk_hash=digest,
                session_id=self.session_id,
                car_id=bucket.car_id,
                channel_family=bucket.family,
                start_session_time_s=max(0.0, min(times)),
                end_session_time_s=max(0.0, *times),
                row_count=len(bucket.rows),
                path=relative.as_posix(),
                mapping_revision=self.mapping_revision,
            )
            pending.append(
                PendingChunk(
                    descriptor=descriptor,
                    staging_path=staging_path,
                    final_path=final_path,
                    kind=kind,
                )
            )
        return pending

    def publish(self, pending: Sequence[PendingChunk]) -> tuple[TelemetryChunkManifest, ...]:
        """Move staged chunks into place and republish the manifest atomically."""
        if not pending:
            return ()
        for chunk in pending:
            chunk.final_path.parent.mkdir(parents=True, exist_ok=True)
            chunk.staging_path.replace(chunk.final_path)
        self._published.extend(chunk.descriptor for chunk in pending)
        self._write_manifest()
        return tuple(chunk.descriptor for chunk in pending)

    def discard(self, pending: Sequence[PendingChunk]) -> None:
        """Abandon staged chunks; the manifest is untouched so readers never saw them."""
        for chunk in pending:
            chunk.staging_path.unlink(missing_ok=True)

    def flush(self) -> tuple[TelemetryChunkManifest, ...]:
        return self.publish(self.stage())

    def _write_manifest(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "mapping_revision": self.mapping_revision,
            "chunk_duration_s": self.chunk_duration_s,
            "chunks": [chunk.model_dump(mode="json") for chunk in self._published],
        }
        atomic_write_bytes(
            self.session_root / MANIFEST_NAME,
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        )

    def write_acquisition_manifest(self, records: Iterable[AcquisitionRecord]) -> Path:
        """Record source URL, license and terms-review status, with redaction."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "written_at": utc_now_iso(),
            "sources": [record.to_json() for record in records],
        }
        target = self.session_root / ACQUISITION_NAME
        atomic_write_bytes(target, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
        return target

    @property
    def published_chunks(self) -> tuple[TelemetryChunkManifest, ...]:
        return tuple(self._published)


class ChunkReader:
    """Reads only what the manifest publishes."""

    def __init__(self, root: Path | str, session_id: str) -> None:
        self.root = Path(root)
        self.session_id = session_id
        self.session_root = self.root / "sessions" / session_id

    def manifest(self) -> tuple[TelemetryChunkManifest, ...]:
        path = self.session_root / MANIFEST_NAME
        if not path.exists():
            return ()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return tuple(TelemetryChunkManifest.model_validate(entry) for entry in payload.get("chunks", ()))

    def acquisition(self) -> dict[str, Any]:
        path = self.session_root / ACQUISITION_NAME
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def verify(self) -> tuple[str, ...]:
        """Re-hash every published chunk; returns a tuple of failure messages."""
        failures: list[str] = []
        for chunk in self.manifest():
            path = self.session_root / chunk.path
            if not path.exists():
                failures.append(f"{chunk.path}: published chunk is missing from disk")
                continue
            actual = sha256_bytes(path.read_bytes())
            if actual != chunk.chunk_hash:
                failures.append(f"{chunk.path}: hash {actual} does not match manifest {chunk.chunk_hash}")
        return tuple(failures)

    def _rows(self, kind: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for chunk in self.manifest():
            if not chunk.path.startswith(f"{kind}/"):
                continue
            path = self.session_root / chunk.path
            if not path.exists():
                raise FileNotFoundError(f"manifest lists {chunk.path} but it is not on disk")
            rows.extend(pq.read_table(path).to_pylist())
        return rows

    def read_canonical_rows(self) -> list[dict[str, Any]]:
        return self._rows("canonical")

    def read_raw_rows(self) -> list[dict[str, Any]]:
        return self._rows(RAW_FAMILY)

    def read_normalised(self) -> tuple[NormalisedRecord, ...]:
        """Rebuild normalised records, ordered by session time then sequence."""
        records = [_record_from_row(row) for row in self.read_canonical_rows()]
        records.sort(key=lambda item: (item.session_time_s, item.event.sequence))
        return tuple(records)

    def read_raw_packets(self) -> tuple[RawSourcePacket, ...]:
        packets = []
        for row in self.read_raw_rows():
            packets.append(
                RawSourcePacket(
                    packet_id=row["packet_id"],
                    source_id=row["source_id"],
                    received_time_s=row["received_time_s"],
                    fields=json.loads(row["fields_json"]),
                    mapping_revision=row["mapping_revision"],
                )
            )
        return tuple(packets)


def _record_from_row(row: Mapping[str, Any]) -> NormalisedRecord:
    event = TelemetryEvent(
        schema_version=row["schema_version"],
        event_id=row["event_id"],
        session_id=row["session_id"],
        car_id=row["car_id"],
        sequence=int(row["sequence"]),
        source_time_s=float(row["source_time_s"]),
        received_time_s=float(row["received_time_s"]),
        channel=row["channel"],
        value=row["value"],
        unit=row["unit"],
        provenance=Provenance(row["provenance"]),
        quality=Quality(row["quality"]),
    )
    return NormalisedRecord(
        event=event,
        session_time_s=float(row["session_time_s"]),
        source_id=row["source_id"],
        mapping_revision=row["mapping_revision"],
        raw_packet_id=row["raw_packet_id"],
        vendor_field=row["vendor_field"],
        labels=tuple(row["labels"] or ()),
        reason=row["reason"],
        finalised_before_s=row["finalised_before_s"],
    )


__all__ = [
    "ACQUISITION_NAME",
    "CANONICAL_SCHEMA",
    "MANIFEST_NAME",
    "RAW_FAMILY",
    "RAW_SCHEMA",
    "REDACTED",
    "AcquisitionRecord",
    "ChunkReader",
    "PendingChunk",
    "TelemetryRecorder",
    "redact_mapping",
    "redact_text",
    "redact_url",
    "utc_now_iso",
]
