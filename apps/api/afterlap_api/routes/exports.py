"""Local export of a complete session record.

``backend/PERSISTENCE_AND_WORKERS.md``: an export contains the session
manifest, scenario definition, decision/command/execution logs, selected
trajectory chunk references, rule/model/objective hashes, software versions,
provenance and the evaluation report. Units are labelled. Private source
credentials and operator secrets are redacted. The demo export is synthetic and
says so.

Two things are enforced rather than documented:

* **every written path is validated against the configured storage root** with
  ``Paths.resolve_within``, so a traversal in a request or a manifest cannot
  escape the export area;
* **credentials are redacted** by ``afterlap_core.data.redact_mapping`` before
  anything is written, and the resulting file is scanned for the redaction to
  have taken effect. Truth endpoints are authorised separately and no simulator
  truth appears in an export.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import sys
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import (
    CONTRACT_REVISION,
    SCHEMA_VERSION,
    ErrorCode,
    JobStatus,
    SessionManifest,
)
from afterlap_contracts.requests import CreateExportRequest, ExportJobResponse
from afterlap_core.data import redact_mapping
from afterlap_core.paths import Paths, atomic_write_bytes, atomic_write_text, sha256_json

from ..db import LifecycleError
from ..db.models import (
    Decision,
    ExecutionEventRow,
    ExportJob,
    LifecycleEvent,
    Manifest,
    OperatorCommand,
    OutcomeRecordRow,
    Session,
    SessionEvent,
    TelemetryChunk,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..deps import CommandDbSession, DbSession, IdempotencyKey, OperatorId

router = APIRouter()

SYNTHETIC_EXPORT_NOTICE = (
    "SYNTHETIC EXPORT. Produced from the AFTERLAP simulator on invented configurations. "
    "It is not measured telemetry, not a real session, and establishes no regulatory or "
    "performance claim."
)

UNITS = {
    "session_time_s": "s",
    "start_time_s": "s",
    "observation_cutoff_s": "s",
    "expires_at_s": "s",
    "energy_j": "J",
    "requested_budget_j": "J",
    "harvest_target_j": "J",
    "progress_m": "m",
    "elapsed_time_s": "s",
    "gap_to_reference_s": "s",
}


def _paths(request: Request) -> Paths:
    settings = getattr(request.app.state, "settings", None)
    root = getattr(settings, "artifact_root", None) if settings is not None else None
    return Paths.default(root).ensure()


def _session_row(db: OrmSession, session_id: str) -> Session:
    row = db.get(Session, session_id)
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"session {session_id} does not exist")
    return row


def build_export_body(db: OrmSession, row: Session, start_s: float | None, end_s: float | None) -> dict:
    """Assemble the complete record. Nothing here reads simulator truth."""
    stored = db.get(Manifest, row.manifest_hash)
    if stored is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, "the session manifest is missing from the store")
    manifest = SessionManifest.model_validate(stored.payload)

    def in_window(value: float) -> bool:
        if start_s is not None and value < start_s:
            return False
        return not (end_s is not None and value > end_s)

    decisions = [
        d.payload
        for d in db.execute(
            select(Decision).where(Decision.session_id == row.id).order_by(Decision.created_at)
        )
        .scalars()
        .all()
        if in_window(float(d.payload.get("created_at_s", 0.0)))
    ]
    executions = [
        e.payload
        for e in db.execute(
            select(ExecutionEventRow)
            .where(ExecutionEventRow.session_id == row.id)
            .order_by(ExecutionEventRow.start_time_s)
        )
        .scalars()
        .all()
        if in_window(e.start_time_s)
    ]
    events = [
        {
            "sequence": e.sequence,
            "event_type": e.event_type,
            "session_time_s": e.session_time_s,
            "schema_version": e.schema_version,
            "payload": e.payload,
        }
        for e in db.execute(
            select(SessionEvent).where(SessionEvent.session_id == row.id).order_by(SessionEvent.sequence)
        )
        .scalars()
        .all()
        if in_window(e.session_time_s)
    ]
    commands = [
        {
            "id": c.id,
            "idempotency_key": c.idempotency_key,
            "operator_id": c.operator_id,
            "expected_revision": c.expected_revision,
            "resulting_event_id": c.resulting_event_id,
            "response": c.response_payload,
        }
        for c in db.execute(
            select(OperatorCommand)
            .where(OperatorCommand.session_id == row.id)
            .order_by(OperatorCommand.created_at)
        )
        .scalars()
        .all()
    ]
    transitions = [
        {
            "decision_id": t.decision_id,
            "from_state": t.from_state,
            "to_state": t.to_state,
            "session_time_s": t.session_time_s,
            "sequence": t.sequence,
            "evidence_event_id": t.evidence_event_id,
            "reason": t.reason,
        }
        for t in db.execute(
            select(LifecycleEvent)
            .where(LifecycleEvent.session_id == row.id)
            .order_by(LifecycleEvent.sequence)
        )
        .scalars()
        .all()
        if in_window(t.session_time_s)
    ]
    outcomes = [
        o.payload
        for o in db.execute(select(OutcomeRecordRow).where(OutcomeRecordRow.session_id == row.id))
        .scalars()
        .all()
    ]
    chunks = [
        {
            "hash": c.hash,
            "car_id": c.car_id,
            "channel_family": c.channel_family,
            "start_session_time_s": c.start_session_time_s,
            "end_session_time_s": c.end_session_time_s,
            "row_count": c.row_count,
            "path": c.path,
            "mapping_revision": c.mapping_revision,
        }
        for c in db.execute(select(TelemetryChunk).where(TelemetryChunk.session_id == row.id)).scalars().all()
        if in_window(c.start_session_time_s)
    ]

    body = {
        "schema": "afterlap.export/1",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "synthetic": bool(row.synthetic),
        "notice": SYNTHETIC_EXPORT_NOTICE if row.synthetic else None,
        "exported_at": datetime.now(UTC).isoformat(),
        "units": UNITS,
        "session": {
            "id": row.id,
            "mode": row.mode,
            "status": row.status,
            "revision": row.revision,
            "session_time_s": row.session_time_s,
            "last_sequence": row.last_sequence,
            "scenario_id": row.scenario_id,
        },
        "selected_range": {"start_session_time_s": start_s, "end_session_time_s": end_s},
        "manifest": manifest.model_dump(mode="json"),
        "hashes": {
            "manifest": row.manifest_hash,
            "track": manifest.track_hash,
            "cars": manifest.car_hashes,
            "ruleset": row.ruleset_hash,
            "model": row.model_hash,
            "objective": manifest.objective_hash,
        },
        "software_versions": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "contract_revision": CONTRACT_REVISION,
        },
        "decisions": decisions,
        "operator_commands": commands,
        "lifecycle_transitions": transitions,
        "execution_events": executions,
        "session_events": events,
        "outcome_records": outcomes,
        "telemetry_chunks": chunks,
        "provenance": {
            "source_capabilities": [c.model_dump(mode="json") for c in manifest.source_capabilities],
            "note": (
                "Every value in this export is SI. Rival stored energy, where present, is an "
                "estimate with a declared interval and is never a measurement."
            ),
        },
    }
    return redact_mapping(body)


def _to_csv(body: dict) -> str:
    """Flat decision log with a units row, for a spreadsheet reader."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "decision_id",
            "created_at_s",
            "observation_cutoff_s",
            "expires_at_s",
            "action_code",
            "status",
            "constraint_status",
            "ruleset_hash",
        ]
    )
    writer.writerow(["", "s", "s", "s", "", "", "", ""])
    for decision in body["decisions"]:
        writer.writerow(
            [
                decision.get("id"),
                decision.get("created_at_s"),
                decision.get("observation_cutoff_s"),
                decision.get("expires_at_s"),
                decision.get("action_code"),
                decision.get("status"),
                (decision.get("constraint_result") or {}).get("status"),
                decision.get("ruleset_hash"),
            ]
        )
    return buffer.getvalue()


@router.post("/exports", response_model=ExportJobResponse, status_code=201)
async def create_export(
    request: Request,
    payload: CreateExportRequest,
    db: CommandDbSession,
    operator_id: OperatorId,
    idempotency_key: IdempotencyKey,
) -> ExportJobResponse:
    row = _session_row(db, payload.session_id)
    if (
        payload.start_session_time_s is not None
        and payload.end_session_time_s is not None
        and payload.end_session_time_s < payload.start_session_time_s
    ):
        raise LifecycleError(ErrorCode.VALIDATION_FAILED, "the selected range ends before it starts")

    paths = _paths(request)
    export_id = f"exp-{uuid.uuid4().hex[:16]}"
    body = build_export_body(db, row, payload.start_session_time_s, payload.end_session_time_s)
    body["export_id"] = export_id
    body["exported_by"] = operator_id
    digest = sha256_json(body)
    body["content_hash"] = digest

    target = paths.resolve_within(f"{export_id}.{payload.format}", root=paths.exports)
    written = _write(target, body, payload.format)

    record = ExportJob(
        id=export_id,
        session_id=row.id,
        format=payload.format,
        status=JobStatus.COMPLETED.value,
        path=str(written),
        hashes={"content": digest, "manifest": row.manifest_hash, "ruleset": row.ruleset_hash},
        synthetic=bool(row.synthetic),
    )
    db.add(record)
    db.flush()
    del idempotency_key

    return ExportJobResponse(
        export_id=export_id,
        status=JobStatus.COMPLETED,
        path=str(written),
        hashes=dict(record.hashes or {}),
        synthetic=bool(row.synthetic),
        created_at=record.created_at or datetime.now(UTC),
    )


def _write(target: Path, body: dict, fmt: str) -> Path:
    if fmt == "json":
        return atomic_write_text(target, json.dumps(body, indent=2, sort_keys=True, default=str) + "\n")
    if fmt == "csv":
        return atomic_write_text(target, _to_csv(body))
    if fmt == "parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - pyarrow is a workspace dependency
            raise LifecycleError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                "parquet export needs pyarrow, which is not installed",
            ) from exc
        table = pa.Table.from_pylist([{"document": json.dumps(body, default=str)}])
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        return atomic_write_bytes(target, buffer.getvalue())
    raise LifecycleError(ErrorCode.VALIDATION_FAILED, f"unsupported export format {fmt!r}")


@router.get("/exports/{export_id}", response_model=ExportJobResponse)
async def get_export(export_id: str, db: DbSession) -> ExportJobResponse:
    record = db.get(ExportJob, export_id)
    if record is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"export {export_id} does not exist")
    return ExportJobResponse(
        export_id=record.id,
        status=JobStatus(record.status),
        path=record.path,
        hashes=dict(record.hashes or {}),
        synthetic=record.synthetic,
        created_at=record.created_at or datetime.now(UTC),
    )


__all__ = ["SYNTHETIC_EXPORT_NOTICE", "UNITS", "build_export_body", "router"]
