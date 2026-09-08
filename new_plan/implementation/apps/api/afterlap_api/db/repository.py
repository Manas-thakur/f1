"""Transactional operations that carry the lifecycle guarantees.

The atomic selection sequence from ``08_backend/PERSISTENCE_AND_WORKERS.md`` is
implemented once, here, so no route can accidentally skip a step:

    begin transaction
      get existing command by session + idempotency key
      if found: require identical body hash; return its prior result
      lock session / control lease and current recommendation revision
      require authorised operator and valid lease
      require expected revision and current ruleset hash
      require nonterminal state, freshness and execution window
      append operator event and lifecycle transition
      increment revision; insert idempotency record
    commit
    publish committed event

The event append, the revision bump and the outbox row are one transaction, so
a crash between commit and publish loses the notification, never the record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import (
    TERMINAL_RECOMMENDATION_STATUSES,
    ErrorCode,
    OperatorAction,
    Recommendation,
    RecommendationStatus,
    StateEstimate,
    content_hash_of,
)

from .models import (
    ControlLease,
    Decision,
    ExecutionEventRow,
    LifecycleEvent,
    OperatorCommand,
    OutboxRecord,
    PlanCandidate,
    Session,
    SessionEvent,
)


class LifecycleError(Exception):
    """A refused operation, carrying the typed error code the route will return.

    ``persist`` distinguishes two kinds of refusal. A plain validation refusal
    changes nothing and must roll back. A refusal produced *by a guard that
    discovered a real state change* — the recommendation had expired, or the
    ruleset moved on — must keep that change: the recommendation genuinely is
    expired now, and discarding that finding would let the next request see
    stale advice as still actionable.
    """

    def __init__(self, code: ErrorCode, message: str, *, persist: bool = False, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.persist = persist
        self.details = details


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """Result of a committed operator command, plus what to publish."""

    recommendation: Recommendation
    operator_event_id: str
    sequence: int
    session_revision: int
    replayed: bool
    outbox_id: str | None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _lock_session(db: OrmSession, session_id: str) -> Session:
    """Read the session row with a write lock where the engine supports one."""
    statement = select(Session).where(Session.id == session_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update()
    row = db.execute(statement).scalar_one_or_none()
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"session {session_id} does not exist")
    return row


def next_sequence(db: OrmSession, session_id: str) -> int:
    row = _lock_session(db, session_id)
    row.last_sequence += 1
    return row.last_sequence


def append_event(
    db: OrmSession,
    *,
    session_id: str,
    event_type: str,
    session_time_s: float,
    payload: dict[str, Any],
    schema_version: str = "1.0",
    publish: bool = True,
) -> SessionEvent:
    """Append one ordered session event and, optionally, its outbox row."""
    sequence = next_sequence(db, session_id)
    event = SessionEvent(
        id=_new_id("evt"),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        session_time_s=session_time_s,
        payload=payload,
        schema_version=schema_version,
    )
    db.add(event)
    if publish:
        db.add(
            OutboxRecord(
                id=_new_id("out"),
                session_id=session_id,
                sequence=sequence,
                event_type=event_type,
                envelope={
                    "schema_version": schema_version,
                    "session_id": session_id,
                    "sequence": sequence,
                    "event_type": event_type,
                    "session_time_s": session_time_s,
                    "payload": payload,
                },
            )
        )
    return event


def acquire_lease(
    db: OrmSession,
    *,
    session_id: str,
    operator_id: str,
    session_time_s: float,
    ttl_s: float,
    expected_lease_revision: int | None = None,
) -> ControlLease:
    """Grant the single control lease, or refuse if another operator holds it.

    A second operator may observe. It may not race the first through a
    contradictory command, so taking the lease from a live holder is refused.
    """
    _lock_session(db, session_id)
    lease = db.get(ControlLease, session_id)

    if lease is None:
        lease = ControlLease(
            session_id=session_id,
            operator_id=operator_id,
            revision=1,
            granted_at_s=session_time_s,
            expires_at_s=session_time_s + ttl_s,
        )
        db.add(lease)
        return lease

    still_held = session_time_s < lease.expires_at_s and lease.operator_id != operator_id
    if still_held:
        raise LifecycleError(
            ErrorCode.LEASE_NOT_HELD,
            f"operator {lease.operator_id} holds the control lease until {lease.expires_at_s:.1f} s",
            holder=lease.operator_id,
            expires_at_s=lease.expires_at_s,
        )
    if expected_lease_revision is not None and expected_lease_revision != lease.revision:
        raise LifecycleError(
            ErrorCode.STALE_REVISION,
            f"lease revision {expected_lease_revision} is stale; current is {lease.revision}",
            current_revision=lease.revision,
        )

    lease.operator_id = operator_id
    lease.revision += 1
    lease.granted_at_s = session_time_s
    lease.expires_at_s = session_time_s + ttl_s
    lease.updated_at = datetime.now(UTC)
    return lease


def require_lease(db: OrmSession, session_id: str, operator_id: str, session_time_s: float) -> ControlLease:
    lease = db.get(ControlLease, session_id)
    if lease is None:
        raise LifecycleError(ErrorCode.LEASE_NOT_HELD, "no control lease has been acquired")
    if lease.operator_id != operator_id:
        raise LifecycleError(
            ErrorCode.LEASE_NOT_HELD,
            f"the control lease is held by {lease.operator_id}",
            holder=lease.operator_id,
        )
    if session_time_s >= lease.expires_at_s:
        raise LifecycleError(
            ErrorCode.LEASE_NOT_HELD,
            f"the control lease expired at {lease.expires_at_s:.1f} s",
            expires_at_s=lease.expires_at_s,
        )
    return lease


def store_decision(
    db: OrmSession,
    *,
    recommendation: Recommendation,
    estimate: StateEstimate,
    accepted_plans: tuple[Any, ...] = (),
    rejected_plans: tuple[Any, ...] = (),
) -> Decision:
    """Persist a published recommendation with the estimate it was made from."""
    decision = Decision(
        id=recommendation.id,
        session_id=recommendation.session_id,
        revision=recommendation.revision,
        state_revision=recommendation.state_revision,
        ruleset_hash=recommendation.ruleset_hash,
        model_hash=recommendation.model_hash,
        objective_version=recommendation.objective_version,
        status=recommendation.status.value,
        observation_cutoff_s=recommendation.observation_cutoff_s,
        expires_at_s=recommendation.expires_at_s,
        payload=recommendation.model_dump(mode="json"),
        estimate_payload=estimate.model_dump(mode="json"),
    )
    db.add(decision)

    for plan, accepted in ((p, True) for p in accepted_plans):
        db.add(_plan_row(recommendation, plan, accepted))
    for plan, accepted in ((p, False) for p in rejected_plans):
        db.add(_plan_row(recommendation, plan, accepted))

    append_event(
        db,
        session_id=recommendation.session_id,
        event_type="recommendation_updated",
        session_time_s=recommendation.created_at_s,
        # The payload carries its own discriminator so a stored row validates
        # as a StreamEnvelope without the publisher having to repair it.
        payload={
            "event_type": "recommendation_updated",
            "recommendation": recommendation.model_dump(mode="json"),
        },
    )
    return decision


def _plan_row(recommendation: Recommendation, plan: Any, accepted: bool) -> PlanCandidate:
    return PlanCandidate(
        id=f"{recommendation.id}:{plan.id}",
        session_id=recommendation.session_id,
        decision_id=recommendation.id,
        state_revision=plan.state_revision,
        intention=plan.intention.value,
        accepted=accepted,
        payload=plan.model_dump(mode="json"),
    )


_ALLOWED_TRANSITIONS: dict[OperatorAction, tuple[RecommendationStatus, ...]] = {
    OperatorAction.SELECT: (RecommendationStatus.PROPOSED,),
    OperatorAction.REJECT: (RecommendationStatus.PROPOSED, RecommendationStatus.SELECTED),
    OperatorAction.MARK_COMMUNICATED: (RecommendationStatus.SELECTED,),
}

_RESULTING_STATUS: dict[OperatorAction, RecommendationStatus] = {
    OperatorAction.SELECT: RecommendationStatus.SELECTED,
    OperatorAction.REJECT: RecommendationStatus.REJECTED,
    OperatorAction.MARK_COMMUNICATED: RecommendationStatus.COMMUNICATED,
}


def apply_operator_action(
    db: OrmSession,
    *,
    session_id: str,
    recommendation_id: str,
    action: OperatorAction,
    operator_id: str,
    expected_revision: int,
    idempotency_key: str,
    body_hash: str,
    session_time_s: float,
    current_ruleset_hash: str,
    reason: str | None = None,
) -> CommandOutcome:
    """The atomic selection sequence. Every guard is checked inside one transaction."""
    existing = db.execute(
        select(OperatorCommand).where(
            OperatorCommand.session_id == session_id,
            OperatorCommand.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.body_hash != body_hash:
            raise LifecycleError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "the same idempotency key was used with a different request body",
                idempotency_key=idempotency_key,
            )
        stored = existing.response_payload or {}
        return CommandOutcome(
            recommendation=Recommendation.model_validate(stored["recommendation"]),
            operator_event_id=existing.resulting_event_id or existing.id,
            sequence=int(stored.get("sequence", 0)),
            session_revision=int(stored.get("session_revision", 0)),
            replayed=True,
            outbox_id=None,
        )

    session_row = _lock_session(db, session_id)
    require_lease(db, session_id, operator_id, session_time_s)

    decision = db.get(Decision, recommendation_id)
    if decision is None or decision.session_id != session_id:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"recommendation {recommendation_id} does not exist")

    recommendation = Recommendation.model_validate(decision.payload)

    if recommendation.revision != expected_revision:
        raise LifecycleError(
            ErrorCode.STALE_REVISION,
            f"expected revision {expected_revision}, current is {recommendation.revision}",
            current_revision=recommendation.revision,
        )

    # Rule invalidation is processed before selection: a plan checked against a
    # superseded pack is invalid regardless of what the browser still shows.
    if recommendation.ruleset_hash != current_ruleset_hash:
        invalidated = _transition(
            db,
            decision,
            recommendation,
            RecommendationStatus.INVALIDATED,
            session_time_s,
            reason="ruleset changed",
        )
        raise LifecycleError(
            ErrorCode.RECOMMENDATION_INVALIDATED,
            "the ruleset changed after this recommendation was published",
            persist=True,
            current_ruleset_hash=current_ruleset_hash,
            recommendation_revision=invalidated.revision,
        )

    if recommendation.status in TERMINAL_RECOMMENDATION_STATUSES:
        raise LifecycleError(
            ErrorCode.RECOMMENDATION_INVALIDATED,
            f"recommendation is already {recommendation.status.value}",
            status=recommendation.status.value,
        )

    if recommendation.is_expired_at(session_time_s):
        _transition(
            db,
            decision,
            recommendation,
            RecommendationStatus.EXPIRED,
            session_time_s,
            reason="expired before the operator action was processed",
        )
        raise LifecycleError(
            ErrorCode.RECOMMENDATION_EXPIRED,
            f"recommendation expired at {recommendation.expires_at_s:.2f} s",
            persist=True,
            expires_at_s=recommendation.expires_at_s,
            session_time_s=session_time_s,
        )

    allowed = _ALLOWED_TRANSITIONS[action]
    if recommendation.status not in allowed:
        raise LifecycleError(
            ErrorCode.VALIDATION_FAILED,
            f"{action.value} is not allowed from status {recommendation.status.value}",
            status=recommendation.status.value,
        )

    updated = _transition(
        db, decision, recommendation, _RESULTING_STATUS[action], session_time_s, reason=reason
    )

    # An operator action is durable audit, not a stream message: there is no
    # StreamEventType for it, and the lifecycle change it caused is already
    # published by _transition as recommendation_updated. Writing an outbox row
    # here would queue something no client can validate, so it is appended to
    # the event log with publish=False.
    operator_event = append_event(
        db,
        session_id=session_id,
        event_type="operator_action",
        session_time_s=session_time_s,
        payload={
            "action": action.value,
            "operator_id": operator_id,
            "recommendation_id": recommendation_id,
            "reason": reason,
            "resulting_status": updated.status.value,
        },
        publish=False,
    )

    session_row.revision += 1

    db.add(
        OperatorCommand(
            id=_new_id("cmd"),
            session_id=session_id,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            expected_revision=expected_revision,
            operator_id=operator_id,
            resulting_event_id=operator_event.id,
            response_payload={
                "recommendation": updated.model_dump(mode="json"),
                "sequence": operator_event.sequence,
                "session_revision": session_row.revision,
            },
        )
    )

    return CommandOutcome(
        recommendation=updated,
        operator_event_id=operator_event.id,
        sequence=operator_event.sequence,
        session_revision=session_row.revision,
        replayed=False,
        outbox_id=None,
    )


def _transition(
    db: OrmSession,
    decision: Decision,
    recommendation: Recommendation,
    to_status: RecommendationStatus,
    session_time_s: float,
    *,
    reason: str | None = None,
    evidence_event_id: str | None = None,
) -> Recommendation:
    """Move a recommendation to a new status and record the audited transition."""
    updated = recommendation.revise(status=to_status, revision=recommendation.revision + 1)

    sequence = next_sequence(db, decision.session_id)
    db.add(
        LifecycleEvent(
            id=_new_id("lc"),
            decision_id=decision.id,
            session_id=decision.session_id,
            from_state=recommendation.status.value,
            to_state=to_status.value,
            session_time_s=session_time_s,
            sequence=sequence,
            evidence_event_id=evidence_event_id,
            reason=reason,
        )
    )

    decision.status = to_status.value
    decision.revision = updated.revision
    decision.payload = updated.model_dump(mode="json")

    db.add(
        OutboxRecord(
            id=_new_id("out"),
            session_id=decision.session_id,
            sequence=sequence,
            event_type="recommendation_updated",
            envelope={
                "schema_version": "1.0",
                "session_id": decision.session_id,
                "sequence": sequence,
                "event_type": "recommendation_updated",
                "session_time_s": session_time_s,
                "payload": {
                    "event_type": "recommendation_updated",
                    "recommendation": updated.model_dump(mode="json"),
                },
            },
        )
    )
    return updated


def record_execution(
    db: OrmSession,
    *,
    execution: Any,
    session_time_s: float,
) -> Recommendation | None:
    """Record an observed driver action and advance the matching recommendation.

    An unsolicited action is stored without being attributed to any
    recommendation. Selection never implies execution, so only this path can
    move a recommendation into ``executing``.
    """
    db.add(
        ExecutionEventRow(
            id=execution.id,
            session_id=execution.session_id,
            decision_id=execution.recommendation_id,
            observed_profile_id=execution.observed_profile_id.value,
            match_status=execution.match_status.value,
            start_time_s=execution.start_time_s,
            sequence=execution.sequence,
            payload=execution.model_dump(mode="json"),
        )
    )
    append_event(
        db,
        session_id=execution.session_id,
        event_type="execution_observed",
        session_time_s=session_time_s,
        payload={
            "event_type": "execution_observed",
            "execution": execution.model_dump(mode="json"),
        },
    )

    if execution.recommendation_id is None:
        return None

    decision = db.get(Decision, execution.recommendation_id)
    if decision is None:
        return None

    recommendation = Recommendation.model_validate(decision.payload)
    if recommendation.status is not RecommendationStatus.COMMUNICATED:
        # Execution observed against advice that was never communicated is kept
        # as evidence, but it does not fabricate a lifecycle step.
        return recommendation

    return _transition(
        db,
        decision,
        recommendation,
        RecommendationStatus.EXECUTING,
        session_time_s,
        reason="driver execution observed",
        evidence_event_id=execution.id,
    )


def invalidate_outstanding(
    db: OrmSession,
    *,
    session_id: str,
    session_time_s: float,
    reason: str,
) -> list[Recommendation]:
    """Withdraw every nonterminal recommendation, e.g. after a ruleset change."""
    rows = db.execute(
        select(Decision).where(
            Decision.session_id == session_id,
            Decision.status.notin_([s.value for s in TERMINAL_RECOMMENDATION_STATUSES]),
        )
    ).scalars()

    invalidated: list[Recommendation] = []
    for decision in rows:
        recommendation = Recommendation.model_validate(decision.payload)
        invalidated.append(
            _transition(
                db,
                decision,
                recommendation,
                RecommendationStatus.INVALIDATED,
                session_time_s,
                reason=reason,
            )
        )
    return invalidated


def expire_due(db: OrmSession, *, session_id: str, session_time_s: float) -> list[Recommendation]:
    """Expire any recommendation whose window has passed."""
    rows = db.execute(
        select(Decision).where(
            Decision.session_id == session_id,
            Decision.status.notin_([s.value for s in TERMINAL_RECOMMENDATION_STATUSES]),
            Decision.expires_at_s <= session_time_s,
        )
    ).scalars()

    expired: list[Recommendation] = []
    for decision in rows:
        recommendation = Recommendation.model_validate(decision.payload)
        expired.append(
            _transition(
                db,
                decision,
                recommendation,
                RecommendationStatus.EXPIRED,
                session_time_s,
                reason="validity window elapsed",
            )
        )
    return expired


def claim_experiment_job(db: OrmSession, *, worker_id: str, lease_seconds: float = 120.0) -> Any | None:
    """Claim one queued job with ``FOR UPDATE SKIP LOCKED`` where supported.

    Two workers must never publish separate successful reports for one job id.
    """
    from .models import ExperimentJob

    statement = (
        select(ExperimentJob)
        .where(ExperimentJob.status == "queued")
        .order_by(ExperimentJob.created_at)
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    job = db.execute(statement).scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.worker_lease = worker_id
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    job.started_at = datetime.now(UTC)
    return job


def unpublished_outbox(db: OrmSession, *, limit: int = 200) -> list[OutboxRecord]:
    return list(
        db.execute(
            select(OutboxRecord)
            .where(OutboxRecord.published_at.is_(None))
            .order_by(OutboxRecord.created_at)
            .limit(limit)
        ).scalars()
    )


def mark_published(db: OrmSession, record: OutboxRecord) -> None:
    record.published_at = datetime.now(UTC)
    record.attempts += 1


def body_hash_of(payload: Any) -> str:
    """Canonical hash used for idempotency body comparison."""
    return content_hash_of(payload)


__all__ = [
    "CommandOutcome",
    "LifecycleError",
    "acquire_lease",
    "append_event",
    "apply_operator_action",
    "body_hash_of",
    "claim_experiment_job",
    "expire_due",
    "invalidate_outstanding",
    "mark_published",
    "next_sequence",
    "record_execution",
    "require_lease",
    "store_decision",
    "unpublished_outbox",
]
