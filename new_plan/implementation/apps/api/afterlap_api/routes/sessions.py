"""Session lifecycle, operator authority, simulator input and the event stream.

Every mutable route requires an operator identity, the control lease and an
``Idempotency-Key``. Capability and mode checks happen server-side: the
frontend's controls are not the authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from afterlap_contracts import (
    SCHEMA_VERSION,
    ControlLease,
    ErrorCode,
    ExecutionEvent,
    OperatorAction,
    OperatorEvent,
    Recommendation,
    RuntimeCapabilities,
    SessionManifest,
    SessionMode,
    SessionSnapshot,
    SessionSummary,
    SnapshotReference,
    StreamEnvelope,
)
from afterlap_contracts.requests import (
    AcquireLeaseRequest,
    AcquireLeaseResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    CreateSnapshotRequest,
    CreateSnapshotResponse,
    DecisionEvidenceResponse,
    DriverActionRequest,
    DriverActionResponse,
    RecommendationActionRequest,
    RecommendationActionResponse,
    SessionCommandRequest,
    SessionCommandResponse,
    SessionListResponse,
)

from ..db import LifecycleError, acquire_lease, apply_operator_action, body_hash_of
from ..db.models import ControlLease as ControlLeaseRow
from ..db.models import Decision, ExecutionEventRow, Manifest, Session, SnapshotRow
from ..db.repository import expire_due, require_lease
from ..deps import CommandDbSession, DbSession, IdempotencyKey, OperatorId, require_simulation_mode
from ..errors import CapabilityUnavailable
from ..stream import StreamHub

router = APIRouter()

HEARTBEAT_INTERVAL_S = 10.0


def _hub(request: Request) -> StreamHub:
    return request.app.state.hub


def _registry(request: Request):  # type: ignore[no-untyped-def]
    registry = getattr(request.app.state, "runtimes", None)
    if registry is None:
        raise CapabilityUnavailable(
            "session_runtime", "no session runtime registry is attached to this process"
        )
    return registry


def _registry_optional(request: Request):  # type: ignore[no-untyped-def]
    """The registry if one is attached, else None. Used where absence is normal."""
    return getattr(request.app.state, "runtimes", None)


def _session_row(db, session_id: str) -> Session:  # type: ignore[no-untyped-def]
    row = db.get(Session, session_id)
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"session {session_id} does not exist")
    return row


def _manifest_of(db, row: Session) -> SessionManifest:  # type: ignore[no-untyped-def]
    stored = db.get(Manifest, row.manifest_hash)
    if stored is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, "the session manifest is missing from the store")
    return SessionManifest.model_validate(stored.payload)


def _capabilities(request: Request, manifest: SessionManifest) -> RuntimeCapabilities:
    """Report what this session can actually do, from measured state."""
    from afterlap_contracts import CapabilityState

    probed = getattr(request.app.state, "capabilities", {})
    energy_capable = any(
        capability.measures("battery_energy_j") for capability in manifest.source_capabilities
    )
    notes = (
        ["Synthetic scenario. Not measured telemetry and not a calibrated car."] if manifest.synthetic else []
    )
    for capability in manifest.source_capabilities:
        notes.extend(capability.limitations)

    return RuntimeCapabilities(
        own_energy=CapabilityState.AVAILABLE if energy_capable else CapabilityState.UNAVAILABLE,
        rival_energy=CapabilityState.UNAVAILABLE,
        lateral_geometry=(
            CapabilityState.AVAILABLE
            if manifest.mode is SessionMode.SIMULATION
            else CapabilityState.UNAVAILABLE
        ),
        rules_coverage=CapabilityState.DEGRADED,
        solver=probed.get("solver", CapabilityState.UNAVAILABLE),
        learned_model=probed.get("learning", CapabilityState.UNAVAILABLE),
        persistence=CapabilityState.AVAILABLE,
        driver_link=(
            CapabilityState.AVAILABLE
            if manifest.mode is SessionMode.SIMULATION
            else CapabilityState.UNAVAILABLE
        ),
        notes=tuple(dict.fromkeys(notes)),
    )


def _current_recommendation(db, session_id: str) -> Recommendation | None:  # type: ignore[no-untyped-def]
    row = db.execute(
        select(Decision)
        .where(Decision.session_id == session_id)
        .order_by(Decision.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return Recommendation.model_validate(row.payload) if row is not None else None


def _lease_of(db, session_id: str) -> ControlLease | None:  # type: ignore[no-untyped-def]
    row = db.get(ControlLeaseRow, session_id)
    if row is None:
        return None
    return ControlLease(
        session_id=row.session_id,
        operator_id=row.operator_id,
        revision=row.revision,
        granted_at_s=row.granted_at_s,
        expires_at_s=row.expires_at_s,
    )


def _build_snapshot(request: Request, db, row: Session) -> SessionSnapshot:  # type: ignore[no-untyped-def]
    manifest = _manifest_of(db, row)
    state = getattr(request.app.state, "latest_state", {}).get(row.id, {})
    return SessionSnapshot(
        schema_version=SCHEMA_VERSION,
        session_id=row.id,
        revision=row.revision,
        last_sequence=row.last_sequence,
        server_time=datetime.now(UTC),
        session_time_s=row.session_time_s,
        status=row.status,
        manifest=manifest,
        estimate=state.get("estimate"),
        rule_context=state.get("rule_context"),
        recommendation=_current_recommendation(db, row.id),
        lease=_lease_of(db, row.id),
        capabilities=_capabilities(request, manifest),
    )


# --- Session creation and listing ---------------------------------------------------


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    request: Request,
    payload: CreateSessionRequest,
    db: CommandDbSession,
    operator_id: OperatorId,
    idempotency_key: IdempotencyKey,
) -> CreateSessionResponse:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise CapabilityUnavailable(
            "session_factory",
            "the session factory is not attached; scenario and rule packs are unavailable",
        )

    manifest, runtime = factory.create(payload)
    db.add(
        Manifest(
            hash=manifest.content_hash(),
            kind="session",
            schema_version=manifest.schema_version,
            payload=manifest.model_dump(mode="json"),
        )
    )
    row = Session(
        id=manifest.id,
        mode=manifest.mode.value,
        revision=0,
        manifest_hash=manifest.content_hash(),
        status="created",
        session_time_s=0.0,
        last_sequence=0,
        scenario_id=manifest.scenario_id,
        ruleset_hash=manifest.ruleset_hash,
        model_hash=manifest.model_hash,
        synthetic=manifest.synthetic,
        label=manifest.label,
    )
    db.add(row)
    db.flush()

    _registry(request).attach(manifest.id, runtime)
    return CreateSessionResponse(manifest=manifest, snapshot=_build_snapshot(request, db, row))


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    db: DbSession,
    mode: Annotated[SessionMode | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> SessionListResponse:
    statement = select(Session).order_by(Session.created_at.desc()).limit(limit + 1)
    if mode is not None:
        statement = statement.where(Session.mode == mode.value)
    if cursor:
        statement = statement.where(Session.id < cursor)

    rows = db.execute(statement).scalars().all()
    page, next_cursor = rows[:limit], (rows[limit].id if len(rows) > limit else None)
    return SessionListResponse(
        sessions=tuple(
            SessionSummary(
                id=r.id,
                mode=SessionMode(r.mode),
                status=r.status,
                revision=r.revision,
                created_at=r.created_at,
                label=r.label,
                synthetic=r.synthetic,
                scenario_id=r.scenario_id,
            )
            for r in page
        ),
        next_cursor=next_cursor,
    )


@router.get("/sessions/{session_id}/snapshot", response_model=SessionSnapshot)
async def get_snapshot(request: Request, session_id: str, db: DbSession) -> SessionSnapshot:
    return _build_snapshot(request, db, _session_row(db, session_id))


# --- Operator authority ---------------------------------------------------------------


@router.post("/sessions/{session_id}/control-lease", response_model=AcquireLeaseResponse)
async def take_lease(
    session_id: str,
    payload: AcquireLeaseRequest,
    db: CommandDbSession,
    idempotency_key: IdempotencyKey,
) -> AcquireLeaseResponse:
    row = _session_row(db, session_id)
    lease = acquire_lease(
        db,
        session_id=session_id,
        operator_id=payload.operator_id,
        session_time_s=row.session_time_s,
        ttl_s=payload.ttl_s,
        expected_lease_revision=payload.expected_lease_revision,
    )
    db.flush()
    return AcquireLeaseResponse(
        lease=ControlLease(
            session_id=lease.session_id,
            operator_id=lease.operator_id,
            revision=lease.revision,
            granted_at_s=lease.granted_at_s,
            expires_at_s=lease.expires_at_s,
        )
    )


@router.post("/sessions/{session_id}/commands", response_model=SessionCommandResponse)
async def run_command(
    request: Request,
    session_id: str,
    payload: SessionCommandRequest,
    db: CommandDbSession,
    idempotency_key: IdempotencyKey,
) -> SessionCommandResponse:
    row = _session_row(db, session_id)
    require_lease(db, session_id, payload.operator_id, row.session_time_s)

    if row.revision != payload.expected_revision:
        raise LifecycleError(
            ErrorCode.STALE_REVISION,
            f"expected session revision {payload.expected_revision}, current is {row.revision}",
            current_revision=row.revision,
        )

    runtime = _registry(request).get(session_id)
    kind = payload.kind.value

    status_after = row.status
    tick = None

    if kind == "start":
        status_after = "running"
        runtime.resume()
    elif kind == "pause":
        status_after = "paused"
        runtime.pause()
    elif kind == "resume":
        status_after = "running"
        runtime.resume()
    elif kind == "stop":
        status_after = "stopped"
        runtime.stop()
    elif kind == "step":
        tick = runtime.advance(payload.step_duration_s or 1.0)
        _remember_state(request, session_id, tick)

    # The runtime records decisions and events through the recorder, which
    # commits in its OWN transaction and increments this row's sequence there.
    # The copy loaded before that call is therefore stale, and a
    # read-modify-write on it silently discards the recorder's increments --
    # the response reports a revision the row does not hold, and the client's
    # next expected_revision is rejected as stale.
    #
    # Increment in SQL instead, so the arithmetic happens on current values
    # whatever else committed in the meantime, then re-read what landed.
    values: dict[str, object] = {
        "revision": Session.revision + 1,
        "last_sequence": Session.last_sequence + 1,
        "status": status_after,
    }
    if kind == "step" and tick is not None:
        values["session_time_s"] = tick.session_time_s

    db.execute(update(Session).where(Session.id == session_id).values(**values))
    db.flush()
    db.expire(row)

    return SessionCommandResponse(
        accepted=True, revision=row.revision, sequence=row.last_sequence, status=row.status
    )


def _remember_state(request: Request, session_id: str, tick) -> None:  # type: ignore[no-untyped-def]
    """Cache the last observable state so a snapshot request does not re-run physics."""
    store = getattr(request.app.state, "latest_state", None)
    if store is None:
        store = {}
        request.app.state.latest_state = store
    store[session_id] = {"estimate": tick.estimate, "rule_context": tick.rule_context}


# --- Recommendation lifecycle ---------------------------------------------------------


@router.post(
    "/sessions/{session_id}/recommendations/{recommendation_id}/actions",
    response_model=RecommendationActionResponse,
)
async def act_on_recommendation(
    request: Request,
    session_id: str,
    recommendation_id: str,
    payload: RecommendationActionRequest,
    db: CommandDbSession,
    idempotency_key: IdempotencyKey,
) -> RecommendationActionResponse:
    row = _session_row(db, session_id)

    # Expiry is evaluated before anything else, so advice the browser still
    # shows cannot be acted on after its window closed.
    expire_due(db, session_id=session_id, session_time_s=row.session_time_s)

    outcome = apply_operator_action(
        db,
        session_id=session_id,
        recommendation_id=recommendation_id,
        action=payload.action,
        operator_id=payload.operator_id,
        expected_revision=payload.expected_revision,
        idempotency_key=idempotency_key,
        body_hash=body_hash_of(payload.model_dump(mode="json")),
        session_time_s=row.session_time_s,
        current_ruleset_hash=row.ruleset_hash,
        reason=payload.reason,
    )
    db.flush()

    # Tell the runtime when the engineer actually communicated, so the observed
    # execution can carry delay_from_communication_s. Without this the
    # operator-to-execution delay -- a metric the operations specification
    # names -- was never measured, and every recorded execution reported None.
    # Only after the durable transition has committed: a refused command must
    # not move the runtime's clock.
    if (
        payload.action is OperatorAction.MARK_COMMUNICATED
        and not outcome.replayed
        and _registry_optional(request) is not None
    ):
        runtime = _registry(request).get(session_id)
        runtime.mark_communicated(recommendation_id, row.session_time_s)

    return RecommendationActionResponse(
        recommendation=outcome.recommendation,
        operator_event=OperatorEvent(
            schema_version=SCHEMA_VERSION,
            id=outcome.operator_event_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            recommendation_id=recommendation_id,
            expected_revision=payload.expected_revision,
            operator_id=payload.operator_id,
            action=payload.action,
            reason=payload.reason,
            session_time_s=row.session_time_s,
            sequence=outcome.sequence,
            resulting_status=outcome.recommendation.status,
        ),
    )


# --- Simulator driver input -----------------------------------------------------------


@router.post("/sessions/{session_id}/simulator/driver-action", response_model=DriverActionResponse)
async def driver_action(
    request: Request,
    session_id: str,
    payload: DriverActionRequest,
    db: CommandDbSession,
    idempotency_key: IdempotencyKey,
) -> DriverActionResponse:
    row = _session_row(db, session_id)
    manifest = _manifest_of(db, row)

    # Server-side enforcement: a replay or live_team session refuses this
    # regardless of what the client rendered.
    require_simulation_mode(manifest.mode, "simulator driver action")

    require_lease(db, session_id, payload.operator_id, row.session_time_s)

    runtime = _registry(request).get(session_id)
    execution = runtime.apply_driver_action(
        payload.profile_id, payload.observed_at_s, payload.recommendation_id
    )

    # The runtime already recorded this through its own recorder, which owns the
    # durable write and its bounded spool. This route was written before the
    # runtime existed and recorded it a second time, which violated
    # execution_event's primary key and turned every driver action into a 500.
    # Read the resulting lifecycle state back instead of writing it again, and
    # return the recommendation this execution actually relates to. Returning
    # the session's newest recommendation instead would report a fresh proposal
    # as the outcome of executing an older one.
    updated: Recommendation | None = None
    if execution.recommendation_id is not None:
        decision = db.get(Decision, execution.recommendation_id)
        if decision is not None:
            updated = Recommendation.model_validate(decision.payload)
    return DriverActionResponse(execution=execution, recommendation=updated)


# --- Snapshots -------------------------------------------------------------------------


@router.post("/sessions/{session_id}/snapshots", response_model=CreateSnapshotResponse, status_code=201)
async def create_snapshot(
    request: Request,
    session_id: str,
    payload: CreateSnapshotRequest,
    db: CommandDbSession,
    idempotency_key: IdempotencyKey,
) -> CreateSnapshotResponse:
    row = _session_row(db, session_id)
    runtime = _registry(request).get(session_id)
    snapshot_hash, complete_state = runtime.snapshot(payload.label)

    store = request.app.state.artifact_store
    store.put_json(complete_state)

    record = SnapshotRow(
        id=f"snap-{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        snapshot_hash=snapshot_hash,
        session_time_s=row.session_time_s,
        label=payload.label,
    )
    db.add(record)
    db.flush()

    return CreateSnapshotResponse(
        snapshot=SnapshotReference(
            snapshot_id=record.id,
            session_id=session_id,
            snapshot_hash=snapshot_hash,
            session_time_s=row.session_time_s,
            label=payload.label,
            created_at=record.created_at or datetime.now(UTC),
        )
    )


# --- Decision evidence ------------------------------------------------------------------


@router.get("/decisions/{decision_id}", response_model=DecisionEvidenceResponse)
async def get_decision(decision_id: str, db: DbSession) -> DecisionEvidenceResponse:
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"decision {decision_id} does not exist")

    executions = (
        db.execute(select(ExecutionEventRow).where(ExecutionEventRow.decision_id == decision_id))
        .scalars()
        .all()
    )

    return DecisionEvidenceResponse(
        recommendation=Recommendation.model_validate(decision.payload),
        estimate_revision=int(decision.estimate_payload["revision"]),
        execution_events=tuple(ExecutionEvent.model_validate(e.payload) for e in executions),
    )


# --- Stream --------------------------------------------------------------------------------


@router.websocket("/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: str, after_sequence: int = 0) -> None:
    """Resume from ``after_sequence``; a cursor outside the buffer resyncs."""
    hub: StreamHub = websocket.app.state.hub
    await websocket.accept()

    subscriber, _ = await hub.subscribe(session_id, after_sequence)
    started = time.monotonic()

    async def _pump() -> None:
        while True:
            envelope: StreamEnvelope = await subscriber.queue.get()
            await websocket.send_text(envelope.model_dump_json())

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            await websocket.send_text(hub.heartbeat(session_id, time.monotonic() - started).model_dump_json())

    pump = asyncio.create_task(_pump())
    beat = asyncio.create_task(_heartbeat())
    try:
        # The client sends nothing; this read detects the disconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        for task in (pump, beat):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await hub.unsubscribe(subscriber)


__all__ = ["router"]
