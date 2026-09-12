"""Lifecycle and operator-authority guarantees against a real database.

These run on SQLite with foreign keys enabled. The same code path runs on
PostgreSQL; only the row-locking hint differs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from afterlap_api.db import (
    LifecycleError,
    acquire_lease,
    apply_operator_action,
    body_hash_of,
    command_transaction,
    create_all,
    create_db_engine,
    create_session_factory,
    expire_due,
    invalidate_outstanding,
    record_execution,
    store_decision,
    transaction,
)
from afterlap_api.db.models import (
    Decision,
    LifecycleEvent,
    OperatorCommand,
    OutboxRecord,
    Session,
    SessionEvent,
)
from afterlap_contracts import (
    ErrorCode,
    ExecutionMatch,
    OperatorAction,
    Recommendation,
    RecommendationStatus,
    fixtures as fx,
)

SESSION_ID = fx.FIXTURE_SESSION_ID
RULESET_HASH = fx.FIXTURE_RULESET_HASH
OPERATOR = "engineer-1"


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'test.sqlite3').as_posix()}")
    create_all(engine)
    return create_session_factory(engine)


def _seed(factory, *, recommendation: Recommendation | None = None) -> Recommendation:
    """Create a session, take the lease and publish one recommendation."""
    published = recommendation or fx.recommendation()
    manifest = fx.session_manifest()
    with transaction(factory) as db:
        db.add(
            Session(
                id=SESSION_ID,
                mode=manifest.mode.value,
                revision=0,
                manifest_hash=manifest.content_hash(),
                status="running",
                session_time_s=12.3,
                last_sequence=100,
                scenario_id=manifest.scenario_id,
                ruleset_hash=RULESET_HASH,
                synthetic=True,
            )
        )
    with transaction(factory) as db:
        acquire_lease(db, session_id=SESSION_ID, operator_id=OPERATOR, session_time_s=10.0, ttl_s=120.0)
        store_decision(db, recommendation=published, estimate=fx.state_estimate())
    return published


def _act(
    factory,
    *,
    action=OperatorAction.SELECT,
    expected_revision=1,
    key="idem-1",
    session_time_s=12.6,
    operator=OPERATOR,
    ruleset_hash=RULESET_HASH,
    reason=None,
    recommendation_id="rec-001",
):
    body = {
        "action": action.value,
        "expected_revision": expected_revision,
        "operator_id": operator,
        "reason": reason,
    }
    with command_transaction(factory) as db:
        return apply_operator_action(
            db,
            session_id=SESSION_ID,
            recommendation_id=recommendation_id,
            action=action,
            operator_id=operator,
            expected_revision=expected_revision,
            idempotency_key=key,
            body_hash=body_hash_of(body),
            session_time_s=session_time_s,
            current_ruleset_hash=ruleset_hash,
            reason=reason,
        )


def test_selection_records_a_decision_without_execution(factory):
    _seed(factory)
    outcome = _act(factory)

    assert outcome.recommendation.status is RecommendationStatus.SELECTED
    assert outcome.replayed is False

    with transaction(factory) as db:
        executions = db.execute(select(SessionEvent).where(SessionEvent.event_type == "execution_observed"))
        assert executions.first() is None, "selection must not create an execution event"
        transitions = db.execute(select(LifecycleEvent)).scalars().all()
        assert [(t.from_state, t.to_state) for t in transitions] == [("proposed", "selected")]


def test_execution_requires_communication_first(factory):
    _seed(factory)
    _act(factory, action=OperatorAction.SELECT, expected_revision=1, key="k1")

    with transaction(factory) as db:
        result = record_execution(db, execution=fx.execution_event(), session_time_s=13.1)
        assert result is not None
        assert result.status is RecommendationStatus.SELECTED

    _act(factory, action=OperatorAction.MARK_COMMUNICATED, expected_revision=2, key="k2")

    with transaction(factory) as db:
        advanced = record_execution(
            db,
            execution=fx.execution_event().revise(id="exec-002", sequence=52),
            session_time_s=13.4,
        )
        assert advanced is not None
        assert advanced.status is RecommendationStatus.EXECUTING


def test_unsolicited_execution_is_not_attributed(factory):
    _seed(factory)
    with transaction(factory) as db:
        result = record_execution(
            db,
            execution=fx.execution_event(match=ExecutionMatch.UNSOLICITED),
            session_time_s=13.1,
        )
        assert result is None

    with transaction(factory) as db:
        decision = db.get(Decision, "rec-001")
        assert decision is not None
        assert decision.status == RecommendationStatus.PROPOSED.value


def test_identical_command_replays_the_original_result(factory):
    _seed(factory)
    first = _act(factory, key="idem-A")
    second = _act(factory, key="idem-A")

    assert second.replayed is True
    assert second.recommendation.revision == first.recommendation.revision
    assert second.sequence == first.sequence

    with transaction(factory) as db:
        commands = db.execute(select(OperatorCommand)).scalars().all()
        assert len(commands) == 1, "a retry must not create a second operator command"
        transitions = db.execute(select(LifecycleEvent)).scalars().all()
        assert len(transitions) == 1, "a retry must not create a second lifecycle transition"


def test_same_key_with_a_different_body_is_a_conflict(factory):
    _seed(factory)
    _act(factory, key="idem-B", reason=None)

    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, key="idem-B", reason="changed my mind")
    assert excinfo.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_stale_expected_revision_is_refused(factory):
    _seed(factory)
    _act(factory, key="k1", expected_revision=1)

    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, action=OperatorAction.MARK_COMMUNICATED, key="k2", expected_revision=1)
    assert excinfo.value.code is ErrorCode.STALE_REVISION
    assert excinfo.value.details["current_revision"] == 2


def test_two_operators_cannot_both_hold_the_lease(factory):
    _seed(factory)

    with transaction(factory) as db, pytest.raises(LifecycleError) as excinfo:
        acquire_lease(db, session_id=SESSION_ID, operator_id="engineer-2", session_time_s=20.0, ttl_s=60.0)
    assert excinfo.value.code is ErrorCode.LEASE_NOT_HELD
    assert excinfo.value.details["holder"] == OPERATOR


def test_an_observer_cannot_act(factory):
    _seed(factory)
    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, operator="engineer-2", key="k-obs")
    assert excinfo.value.code is ErrorCode.LEASE_NOT_HELD


def test_lease_can_be_taken_after_it_expires(factory):
    _seed(factory)
    with transaction(factory) as db:
        lease = acquire_lease(
            db, session_id=SESSION_ID, operator_id="engineer-2", session_time_s=200.0, ttl_s=60.0
        )
    assert lease.operator_id == "engineer-2"
    assert lease.revision == 2


def test_selection_after_expiry_is_refused_and_expires_the_record(factory):
    _seed(factory)

    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, session_time_s=25.0, key="late")
    assert excinfo.value.code is ErrorCode.RECOMMENDATION_EXPIRED

    with transaction(factory) as db:
        decision = db.get(Decision, "rec-001")
        assert decision is not None
        assert decision.status == RecommendationStatus.EXPIRED.value


def test_rule_invalidation_is_processed_before_selection(factory):
    _seed(factory)

    with pytest.raises(LifecycleError) as excinfo:
        _act(
            factory,
            key="stale-rules",
            ruleset_hash="sha256:4c27e1a043ee99489a73c39df2a0d98d055fa21e8e028c9343da935b5458d207",
        )
    assert excinfo.value.code is ErrorCode.RECOMMENDATION_INVALIDATED

    with transaction(factory) as db:
        decision = db.get(Decision, "rec-001")
        assert decision is not None
        assert decision.status == RecommendationStatus.INVALIDATED.value
        transitions = db.execute(select(LifecycleEvent)).scalars().all()
        assert [(t.from_state, t.to_state) for t in transitions] == [("proposed", "invalidated")]


def test_invalidate_outstanding_withdraws_every_nonterminal_recommendation(factory):
    _seed(factory)
    with transaction(factory) as db:
        withdrawn = invalidate_outstanding(
            db, session_id=SESSION_ID, session_time_s=14.0, reason="safety car"
        )
    assert [r.status for r in withdrawn] == [RecommendationStatus.INVALIDATED]

    with transaction(factory) as db:
        again = invalidate_outstanding(db, session_id=SESSION_ID, session_time_s=15.0, reason="safety car")
    assert again == [], "a terminal recommendation is not invalidated twice"


def test_expire_due_only_expires_elapsed_windows(factory):
    _seed(factory)
    with transaction(factory) as db:
        assert expire_due(db, session_id=SESSION_ID, session_time_s=15.0) == []
    with transaction(factory) as db:
        expired = expire_due(db, session_id=SESSION_ID, session_time_s=25.0)
    assert [r.status for r in expired] == [RecommendationStatus.EXPIRED]


def test_a_terminal_recommendation_cannot_be_selected(factory):
    _seed(factory)
    _act(factory, action=OperatorAction.REJECT, key="rej", expected_revision=1)

    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, action=OperatorAction.SELECT, key="after-reject", expected_revision=2)
    assert excinfo.value.code is ErrorCode.RECOMMENDATION_INVALIDATED


def test_mark_communicated_requires_selection_first(factory):
    _seed(factory)
    with pytest.raises(LifecycleError) as excinfo:
        _act(factory, action=OperatorAction.MARK_COMMUNICATED, key="comm", expected_revision=1)
    assert excinfo.value.code is ErrorCode.VALIDATION_FAILED


def test_every_lifecycle_change_writes_an_outbox_row_in_the_same_transaction(factory):
    _seed(factory)
    _act(factory)

    with transaction(factory) as db:
        outbox = db.execute(select(OutboxRecord).order_by(OutboxRecord.sequence)).scalars().all()
        events = db.execute(select(SessionEvent).order_by(SessionEvent.sequence)).scalars().all()

    assert outbox, "a committed lifecycle change must leave a publishable record"
    assert all(row.published_at is None for row in outbox)
    sequences = [row.sequence for row in outbox]
    assert len(set(sequences)) == len(sequences)
    assert max(sequences) <= max(e.sequence for e in events)


def test_a_failed_command_leaves_no_partial_write(factory):
    _seed(factory)

    with pytest.raises(LifecycleError):
        _act(factory, key="doomed", expected_revision=99)

    with transaction(factory) as db:
        commands = db.execute(select(OperatorCommand)).scalars().all()
        transitions = db.execute(select(LifecycleEvent)).scalars().all()
        decision = db.get(Decision, "rec-001")

    assert commands == []
    assert transitions == []
    assert decision is not None
    assert decision.status == RecommendationStatus.PROPOSED.value
    assert decision.revision == 1


def test_a_decision_keeps_the_estimate_it_was_made_from(factory):
    _seed(factory)
    _act(factory)

    with transaction(factory) as db:
        decision = db.get(Decision, "rec-001")
        assert decision is not None
        assert decision.estimate_payload["revision"] == 4
        assert decision.estimate_payload["cutoff_s"] == 12.2
        assert decision.observation_cutoff_s == 12.2


def test_session_sequence_is_unique_and_monotonic(factory):
    _seed(factory)
    _act(factory, key="a", expected_revision=1)
    _act(factory, action=OperatorAction.MARK_COMMUNICATED, key="b", expected_revision=2)

    with transaction(factory) as db:
        events = db.execute(select(SessionEvent).order_by(SessionEvent.sequence)).scalars().all()

    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert sequences[0] > 100, "sequences continue from the session's last_sequence"
