"""Durable side of the session loop.

This module owns no lifecycle rules. Every transition goes through the
coordinator's ``afterlap_api.db.repository`` helpers — ``store_decision``,
``record_execution``, ``invalidate_outstanding``, ``expire_due``,
``apply_operator_action``, ``append_event`` — inside ``command_transaction``.
What this class adds is the *failure* behaviour the architecture requires:

* a database failure spools the write in a bounded durable spool and raises a
  visible persistence warning (it does not pretend the write happened);
* an exhausted spool halts new recommendations, so no advice is ever issued that
  cannot later be audited;
* a recovered database drains the spool in spooled order, preserving sequence
  continuity.

A :class:`~afterlap_api.db.LifecycleError` is a *refusal*, not an outage. It is
re-raised untouched so the route still returns its typed error and nothing is
spooled: the guard genuinely decided, and repeating it later would be wrong.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from afterlap_contracts import (
    CapabilityState,
    ExecutionEvent,
    OutcomeRecord,
    Recommendation,
    StateEstimate,
)

from ..db import (
    LifecycleError,
    append_event,
    command_transaction,
    expire_due,
    invalidate_outstanding,
    record_execution,
    store_decision,
)
from ..db.models import OutcomeRecordRow
from .degradation import PersistenceStatus
from .spool import BoundedSpool, SpoolFull

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session as OrmSession, sessionmaker

logger = logging.getLogger("afterlap.session.recorder")


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """What one durable write actually did."""

    kind: str
    committed: bool
    spooled: bool = False
    halted: bool = False
    detail: str | None = None

    @property
    def durable(self) -> bool:
        return self.committed


class SessionRecorder:
    """Persists one session's lifecycle, degrading visibly rather than silently."""

    def __init__(
        self,
        factory: sessionmaker[OrmSession],
        *,
        session_id: str,
        spool: BoundedSpool | None = None,
    ) -> None:
        self._factory = factory
        self.session_id = session_id
        self._spool = spool
        self._last_error: str | None = None
        self._exhausted = False
        self._failures = 0

    def accepts_new_recommendations(self) -> bool:
        """False once the spool is exhausted: halt rather than lose the audit trail."""
        return not self._exhausted

    def status(self) -> PersistenceStatus:
        spooled = len(self._spool) if self._spool is not None else 0
        capacity = self._spool.capacity if self._spool is not None else 0
        if self._exhausted:
            state = CapabilityState.UNAVAILABLE
        elif spooled or self._last_error is not None:
            state = CapabilityState.DEGRADED
        else:
            state = CapabilityState.AVAILABLE
        warnings: list[str] = []
        if state is not CapabilityState.AVAILABLE:
            warnings.append(
                f"session store degraded: {spooled}/{capacity} writes spooled, "
                f"{self._failures} failure(s); last error {self._last_error!r}"
            )
        return PersistenceStatus(
            state=state,
            spooled=spooled,
            capacity=capacity,
            last_error=self._last_error,
            exhausted=self._exhausted,
            warnings=tuple(warnings),
        )

    def publish_recommendation(
        self,
        *,
        recommendation: Recommendation,
        estimate: StateEstimate,
        accepted: tuple[Any, ...] = (),
        rejected: tuple[Any, ...] = (),
        session_time_s: float,
    ) -> RecordOutcome:
        if self._exhausted:
            return RecordOutcome(
                kind="store_decision",
                committed=False,
                halted=True,
                detail="the persistence spool is exhausted; new recommendations are halted",
            )

        def write(db: OrmSession) -> None:
            store_decision(
                db,
                recommendation=recommendation,
                estimate=estimate,
                accepted_plans=accepted,
                rejected_plans=rejected,
            )

        return self._attempt(
            "store_decision",
            write,
            session_time_s=session_time_s,
            payload={
                "recommendation": recommendation.model_dump(mode="json"),
                "estimate": estimate.model_dump(mode="json"),
            },
        )

    def record_driver_execution(self, *, execution: ExecutionEvent, session_time_s: float) -> RecordOutcome:
        def write(db: OrmSession) -> None:
            record_execution(db, execution=execution, session_time_s=session_time_s)

        return self._attempt(
            "record_execution",
            write,
            session_time_s=session_time_s,
            payload={"execution": execution.model_dump(mode="json")},
        )

    def invalidate_all(self, *, reason: str, session_time_s: float) -> RecordOutcome:
        def write(db: OrmSession) -> None:
            invalidate_outstanding(
                db, session_id=self.session_id, session_time_s=session_time_s, reason=reason
            )

        return self._attempt(
            "invalidate_outstanding",
            write,
            session_time_s=session_time_s,
            payload={"reason": reason},
        )

    def expire(self, *, session_time_s: float) -> RecordOutcome:
        def write(db: OrmSession) -> None:
            expire_due(db, session_id=self.session_id, session_time_s=session_time_s)

        return self._attempt("expire_due", write, session_time_s=session_time_s, payload={})

    def record_outcome(self, *, outcome: OutcomeRecord, session_time_s: float) -> RecordOutcome:
        """Store a named checkpoint outcome and its ordered session event.

        There is no repository helper for outcome rows, so the insert is here.
        It is a plain append of an immutable record; no status transition and no
        revision change happens, which is why it does not belong in the
        lifecycle module.
        """

        def write(db: OrmSession) -> None:
            db.add(
                OutcomeRecordRow(
                    id=outcome.id,
                    session_id=outcome.session_id,
                    decision_id=outcome.decision_id,
                    checkpoint_id=outcome.checkpoint.checkpoint_id,
                    event_observed=outcome.event_observed,
                    payload=outcome.model_dump(mode="json"),
                )
            )
            append_event(
                db,
                session_id=outcome.session_id,
                event_type="quality_changed",
                session_time_s=session_time_s,
                payload={
                    "event_type": "quality_changed",
                    "channels": [],
                    "message": (
                        f"outcome recorded at checkpoint {outcome.checkpoint.checkpoint_id} "
                        f"(observed={outcome.event_observed})"
                    ),
                },
            )

        return self._attempt(
            "record_outcome",
            write,
            session_time_s=session_time_s,
            payload={"outcome": outcome.model_dump(mode="json")},
        )

    def append_session_event(
        self, *, event_type: str, session_time_s: float, payload: dict[str, Any]
    ) -> RecordOutcome:
        def write(db: OrmSession) -> None:
            append_event(
                db,
                session_id=self.session_id,
                event_type=event_type,
                session_time_s=session_time_s,
                payload=payload,
            )

        return self._attempt(
            "append_event",
            write,
            session_time_s=session_time_s,
            payload={"event_type": event_type, "payload": payload},
        )

    def drain_spool(self) -> tuple[int, int]:
        """Replay spooled writes in order. Returns ``(replayed, remaining)``.

        Replay stops at the first entry that fails again, so ordering is never
        broken by skipping ahead.
        """
        if self._spool is None or not len(self._spool):
            self._exhausted = False
            return 0, 0
        entries = list(self._spool.entries)
        replayed = 0
        for entry in entries:
            handler = self._REPLAY.get(entry.kind)
            if handler is None:
                logger.warning("no spool replay handler for %s; leaving it spooled", entry.kind)
                break
            try:
                with command_transaction(self._factory) as db:
                    handler(self, db, entry.payload, entry.session_time_s)
            except LifecycleError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                break
            replayed += 1
        remaining = self._spool.entries[replayed:]
        self._spool.drain()
        for entry in remaining:
            self._spool.append(
                kind=entry.kind,
                session_time_s=entry.session_time_s,
                payload=entry.payload,
                reason=entry.reason,
            )
        if not remaining:
            self._exhausted = False
            self._last_error = None
        return replayed, len(remaining)

    def _attempt(
        self,
        kind: str,
        write: Callable[[OrmSession], None],
        *,
        session_time_s: float,
        payload: dict[str, Any],
    ) -> RecordOutcome:
        try:
            with command_transaction(self._factory) as db:
                write(db)
        except LifecycleError:
            raise
        except Exception as exc:
            return self._degrade(kind, exc, session_time_s=session_time_s, payload=payload)
        return RecordOutcome(kind=kind, committed=True)

    def _degrade(
        self,
        kind: str,
        exc: BaseException,
        *,
        session_time_s: float,
        payload: dict[str, Any],
    ) -> RecordOutcome:
        self._failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("session store write %s failed: %s", kind, self._last_error)
        if self._spool is None:
            self._exhausted = True
            return RecordOutcome(
                kind=kind,
                committed=False,
                halted=True,
                detail=f"no spool is configured and the store failed: {self._last_error}",
            )
        try:
            self._spool.append(
                kind=kind, session_time_s=session_time_s, payload=payload, reason=self._last_error
            )
        except SpoolFull as full:
            self._exhausted = True
            return RecordOutcome(kind=kind, committed=False, halted=True, detail=str(full))
        if self._spool.full:
            self._exhausted = True
            return RecordOutcome(
                kind=kind,
                committed=False,
                spooled=True,
                halted=True,
                detail="spooled; the spool is now full and new recommendations are halted",
            )
        return RecordOutcome(kind=kind, committed=False, spooled=True, detail=f"spooled: {self._last_error}")

    def _replay_decision(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        store_decision(
            db,
            recommendation=Recommendation.model_validate(payload["recommendation"]),
            estimate=StateEstimate.model_validate(payload["estimate"]),
        )

    def _replay_execution(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        record_execution(
            db,
            execution=ExecutionEvent.model_validate(payload["execution"]),
            session_time_s=session_time_s,
        )

    def _replay_invalidate(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        invalidate_outstanding(
            db,
            session_id=self.session_id,
            session_time_s=session_time_s,
            reason=str(payload.get("reason", "replayed from spool")),
        )

    def _replay_expire(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        expire_due(db, session_id=self.session_id, session_time_s=session_time_s)

    def _replay_outcome(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        outcome = OutcomeRecord.model_validate(payload["outcome"])
        db.add(
            OutcomeRecordRow(
                id=outcome.id,
                session_id=outcome.session_id,
                decision_id=outcome.decision_id,
                checkpoint_id=outcome.checkpoint.checkpoint_id,
                event_observed=outcome.event_observed,
                payload=outcome.model_dump(mode="json"),
            )
        )

    def _replay_event(self, db: OrmSession, payload: dict[str, Any], session_time_s: float) -> None:
        append_event(
            db,
            session_id=self.session_id,
            event_type=str(payload["event_type"]),
            session_time_s=session_time_s,
            payload=dict(payload["payload"]),
        )

    _REPLAY: dict[str, Callable[[SessionRecorder, OrmSession, dict[str, Any], float], None]] = {
        "store_decision": _replay_decision,
        "record_execution": _replay_execution,
        "invalidate_outstanding": _replay_invalidate,
        "expire_due": _replay_expire,
        "record_outcome": _replay_outcome,
        "append_event": _replay_event,
    }


def new_outcome_id() -> str:
    return f"out-{uuid.uuid4().hex[:16]}"


__all__ = ["RecordOutcome", "SessionRecorder", "new_outcome_id"]
