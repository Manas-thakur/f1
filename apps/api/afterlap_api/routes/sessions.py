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
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import (
    SCHEMA_VERSION,
    CapabilityState,
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
    StreamEventType,
)
from afterlap_contracts.events import SnapshotPayload
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
from afterlap_core.tracks.loader import TrackPackageError, load_track_package
from afterlap_core.tracks.package import ReadinessStatus

from ..db import LifecycleError, acquire_lease, apply_operator_action, body_hash_of
from ..db.models import (
    ControlLease as ControlLeaseRow,
    Decision,
    ExecutionEventRow,
    Manifest,
    Session,
    SnapshotRow,
)
from ..db.repository import append_event, expire_due, next_sequence, require_lease
from ..deps import CommandDbSession, DbSession, IdempotencyKey, OperatorId, require_simulation_mode
from ..errors import CapabilityUnavailable
from ..runtime.port import RuntimeTick
from ..runtime.registry import RuntimeRegistry

if TYPE_CHECKING:
    from ..stream import StreamHub

router = APIRouter()

HEARTBEAT_INTERVAL_S = 10.0


def _hub(request: Request) -> StreamHub:
    return request.app.state.hub


def _registry(request: Request) -> RuntimeRegistry:
    registry = getattr(request.app.state, "runtimes", None)
    if registry is None:
        raise CapabilityUnavailable(
            "session_runtime", "no session runtime registry is attached to this process"
        )
    return registry


def _registry_optional(request: Request) -> RuntimeRegistry | None:
    """The registry if one is attached, else None. Used where absence is normal."""
    return getattr(request.app.state, "runtimes", None)


def _session_row(db: OrmSession, session_id: str) -> Session:
    row = db.get(Session, session_id)
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"session {session_id} does not exist")
    return row


def _manifest_of(db: OrmSession, row: Session) -> SessionManifest:
    stored = db.get(Manifest, row.manifest_hash)
    if stored is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, "the session manifest is missing from the store")
    return SessionManifest.model_validate(stored.payload)


def _geometry_states(
    request: Request, manifest: SessionManifest
) -> tuple[CapabilityState, CapabilityState, list[str]]:
    """``(track_geometry, lateral_geometry, notes)`` from the geometry on disk.

    Read from the *package*, not from the mode. Three facts decide it:

    * a compiled package at or above ``geometry_validated`` genuinely supplies
      metric geometry, so ``track_geometry`` is available;
    * a synthetic sketch supplies invented curvature and widths, so
      ``track_geometry`` is degraded and says why -- never available, because
      that would present a fixture as a circuit;
    * ``lateral_geometry`` follows the *corridor*, never the mode. An unknown
      corridor means ``width_at`` returns ``nan`` and the lateral degree of
      freedom is disabled, so the capability is unavailable however the
      session is driven (D-10).
    """
    from ..session.circuit import (
        MINIMUM_READINESS,
        SYNTHETIC_SKETCH_GEOMETRY_NOTE,
        UNKNOWN_CORRIDOR_NOTE,
    )

    notes: list[str] = []
    if manifest.mode is not SessionMode.SIMULATION:
        notes.append(
            f"Session mode {manifest.mode.value!r} has no simulator geometry; a replay or team-feed "
            "runtime is not implemented."
        )
        return CapabilityState.UNAVAILABLE, CapabilityState.UNAVAILABLE, notes

    if manifest.track_package_hash is None:
        notes.append(SYNTHETIC_SKETCH_GEOMETRY_NOTE)
        return CapabilityState.DEGRADED, CapabilityState.DEGRADED, notes

    from afterlap_core.tracks.package import readiness_rank

    from .catalog import catalogue_paths

    readiness = manifest.track_readiness
    try:
        rung = readiness_rank(ReadinessStatus(readiness)) if readiness else -1
    except ValueError:
        rung = -1
    if rung < readiness_rank(MINIMUM_READINESS):
        notes.append(
            f"Compiled package {manifest.track_id!r} records readiness {readiness!r}, below "
            f"{MINIMUM_READINESS.value}: its geometry may not drive the simulator."
        )
        return CapabilityState.UNAVAILABLE, CapabilityState.UNAVAILABLE, notes

    track_geometry = CapabilityState.AVAILABLE

    corridor_known: bool | None = None
    try:
        package = load_track_package(str(manifest.track_id), catalogue_paths(request))
    except (TrackPackageError, ValueError) as exc:
        notes.append(
            f"The corridor of package {manifest.track_id!r} cannot be re-read ({exc}); lateral "
            "geometry is reported unavailable rather than assumed."
        )
    else:
        if package.package_hash != manifest.track_package_hash:
            notes.append(
                f"Package {manifest.track_id!r} on disk hashes to "
                f"{(package.package_hash or 'unhashed')[:12]} but this session ran "
                f"{manifest.track_package_hash[:12]}; the corridor cannot be confirmed."
            )
        else:
            corridor_known = package.lateral_geometry_known

    if corridor_known:
        return track_geometry, CapabilityState.AVAILABLE, notes
    if corridor_known is False:
        notes.append(UNKNOWN_CORRIDOR_NOTE)
    return track_geometry, CapabilityState.UNAVAILABLE, notes


def _capabilities(request: Request, manifest: SessionManifest) -> RuntimeCapabilities:
    """Report what this session can actually do, from measured state."""
    probed = getattr(request.app.state, "capabilities", {})
    energy_capable = any(
        capability.measures("battery_energy_j") for capability in manifest.source_capabilities
    )
    notes = (
        ["Synthetic scenario. Not measured telemetry and not a calibrated car."] if manifest.synthetic else []
    )
    track_geometry, lateral_geometry, geometry_notes = _geometry_states(request, manifest)
    notes.extend(geometry_notes)
    for capability in manifest.source_capabilities:
        notes.extend(capability.limitations)

    return RuntimeCapabilities(
        own_energy=CapabilityState.AVAILABLE if energy_capable else CapabilityState.UNAVAILABLE,
        rival_energy=CapabilityState.UNAVAILABLE,
        lateral_geometry=lateral_geometry,
        track_geometry=track_geometry,
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


def _current_recommendation(db: OrmSession, session_id: str) -> Recommendation | None:
    row = db.execute(
        select(Decision)
        .where(Decision.session_id == session_id)
        .order_by(Decision.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return Recommendation.model_validate(row.payload) if row is not None else None


def _lease_of(db: OrmSession, session_id: str) -> ControlLease | None:
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


def _build_snapshot(request: Request, db: OrmSession, row: Session) -> SessionSnapshot:
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
        track_id=manifest.track_id,
        track_package_hash=manifest.track_package_hash,
        event_id=manifest.event_id,
        event_package_hash=manifest.event_package_hash,
        conditions_id=manifest.conditions_id,
        conditions_hash=manifest.conditions_hash,
        track_readiness=manifest.track_readiness,
        geometry_provenance=manifest.geometry_provenance,
    )
    db.add(row)
    db.flush()

    sequence = next_sequence(db, row.id)
    snapshot = _build_snapshot(request, db, row)
    append_event(
        db,
        session_id=row.id,
        event_type=StreamEventType.SNAPSHOT.value,
        session_time_s=row.session_time_s,
        payload=SnapshotPayload(snapshot=snapshot).model_dump(mode="json"),
        schema_version=SCHEMA_VERSION,
        sequence=sequence,
    )
    db.flush()

    _registry(request).attach(manifest.id, runtime)
    return CreateSessionResponse(manifest=manifest, snapshot=snapshot)


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


def _remember_state(request: Request, session_id: str, tick: RuntimeTick) -> None:
    """Cache the last observable state so a snapshot request does not re-run physics."""
    store = getattr(request.app.state, "latest_state", None)
    if store is None:
        store = {}
        request.app.state.latest_state = store
    store[session_id] = {"estimate": tick.estimate, "rule_context": tick.rule_context}
    _observe_decision_metrics(request, session_id, tick)


def _observe_decision_metrics(request: Request, session_id: str, tick: RuntimeTick) -> None:
    """Record planner time, observation age and spool depth for one decision.

    Planner time and end-to-end observation age are recorded separately and
    deliberately: a fast solver on a stale feed would otherwise look identical
    to a fast solver on a fresh one, which is the confusion
    ``operations/TECHNICAL_SPEC.md`` asks the two metrics to prevent.
    """
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is None:
        return
    if tick.planning is not None:
        metrics.observe_planner(tick.planning.duration_ms)
    if tick.estimate is not None:
        metrics.observe_observation_age(max(0.0, tick.session_time_s - tick.estimate.cutoff_s))
    registry = _registry_optional(request)
    if registry is None or not registry.has(session_id):
        return
    persistence = getattr(registry.get(session_id), "persistence", None)
    if persistence is not None:
        metrics.spool_depth = persistence.spooled


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

    require_simulation_mode(manifest.mode, "simulator driver action")

    require_lease(db, session_id, payload.operator_id, row.session_time_s)

    runtime = _registry(request).get(session_id)
    execution = runtime.apply_driver_action(
        payload.profile_id, payload.observed_at_s, payload.recommendation_id
    )

    updated: Recommendation | None = None
    if execution.recommendation_id is not None:
        decision = db.get(Decision, execution.recommendation_id)
        if decision is not None:
            updated = Recommendation.model_validate(decision.payload)
    return DriverActionResponse(execution=execution, recommendation=updated)


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
        track_id=row.track_id,
        track_package_hash=row.track_package_hash,
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
