"""Crash, outage and restart behaviour.

``08_backend/TECHNICAL_SPEC.md``:

    Handle worker crash with a visible unavailable state and restore from a
    consistent snapshot/log offset. Never replay a previously acknowledged human
    actuator command merely because the process restarted. A temporary DB outage
    uses a bounded durable spool with sequence continuity; if exhausted, stop
    issuing new advice.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import OperationalError

from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import Decision, OutboxRecord
from afterlap_api.runtime import RuntimeRegistry
from afterlap_api.runtime.port import RuntimeUnavailable
from afterlap_api.session import (
    BoundedSpool,
    DeduplicatingConsumer,
    InProcessSessionRuntime,
    OutboxPublisher,
    SessionRecorder,
)
from afterlap_api.session.runtime import SNAPSHOT_SCHEMA
from afterlap_contracts import (
    CheckStatus,
    DeploymentProfile,
    ExecutionMatch,
    RecommendationStatus,
    StreamEventType,
)
from afterlap_core.rules import load_rule_pack
from afterlap_core.simulation import load_bundle

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED, actionable, start_session


def _fresh_runtime(session, bundle=None, pack=None) -> InProcessSessionRuntime:  # type: ignore[no-untyped-def]
    """A replacement process for the same session, as a restart would build one."""
    runtime = InProcessSessionRuntime(
        bundle=bundle or load_bundle(SCENARIO_ID),
        pack=pack or load_rule_pack(RULE_PACK_ID),
        planner=session.runtime.planner,
        config=session.runtime.config,
        recorder=session.recorder,
    )
    runtime.initialise(session.manifest, SCENARIO_ID, SEED)
    return runtime


# --- worker crash mid-session -------------------------------------------------------


def test_a_worker_crash_invalidates_expiring_advice_and_resumes_only_when_ready(db_factory):
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    live = tick.recommendation
    assert live is not None and live.status is RecommendationStatus.PROPOSED

    _, snapshot = session.runtime.snapshot("before the crash")
    assert snapshot["schema"] == SNAPSHOT_SCHEMA
    assert snapshot["event_offset"]["newest_event_time_s"] is not None
    assert snapshot["event_offset"]["sequence"] >= 0

    # --- the worker dies. The registry reports the session unavailable rather
    # --- than serving the state nobody is computing any more.
    registry = RuntimeRegistry()
    registry.attach(session.session_id, session.runtime)
    registry.detach(session.session_id)
    with pytest.raises(RuntimeUnavailable):
        registry.get(session.session_id)

    # Outstanding advice that could expire is invalidated before anything resumes.
    assert session.recorder is not None
    session.recorder.invalidate_all(reason="session worker crashed", session_time_s=tick.session_time_s)
    assert session.status_of(live.id) is RecommendationStatus.INVALIDATED

    # --- restart: restore from the snapshot and the event offset --------------
    restored = _fresh_runtime(session)
    restored.restore(snapshot)
    assert restored.session_time_s == pytest.approx(tick.session_time_s, abs=1e-9)
    assert restored.revision > snapshot["revision"], "the restored session reuses a stale revision"
    # Not ready: nothing has been re-estimated or revalidated yet, so nothing is
    # published and the session must not be operated.
    assert restored.ready is False
    assert restored.last_estimate is None
    assert restored.last_recommendation is None

    resumed = restored.resume_after_restore()
    assert restored.ready is True
    assert resumed.estimate is not None, "the session resumed without re-estimating"
    assert resumed.rule_context is not None, "the session resumed without re-resolving the rules"
    assert resumed.recommendation is not None
    # Whatever is published after the restart carries a fresh independent check.
    assert resumed.recommendation.constraint_result.checked_at_s >= tick.session_time_s
    assert resumed.recommendation.id != live.id, "the invalidated advice was re-published"
    registry.attach(session.session_id, restored)
    assert registry.get(session.session_id) is restored


def test_a_previously_acknowledged_driver_command_is_never_replayed_on_reconnection(db_factory):
    session = start_session(db_factory)
    session.advance(1.0)
    runtime = session.runtime

    queued = runtime.queue_driver_input(DeploymentProfile.PUSH)
    tick = session.advance(1.0)
    assert [e.id for e in tick.executions] == [f"exe-{queued.id}"]
    acknowledged = runtime.executions[0]

    # The snapshot records which deliberate commands have already been applied.
    _, snapshot = runtime.snapshot("after the driver acted")
    assert queued.id in snapshot["acknowledged_driver_inputs"]
    assert snapshot["queued_driver_inputs"] == []

    restored = _fresh_runtime(session)
    restored.restore(snapshot)
    restored.resume_after_restore()
    for _ in range(3):
        restored.advance(1.0)

    # The restart must not re-actuate a command the driver already carried out.
    assert acknowledged.id not in {e.id for e in restored.executions}
    assert restored.executions == (), "a previously acknowledged driver command was replayed"

    # A command that had *not* yet landed is still pending after a restart, and
    # is applied exactly once.
    pending = runtime.queue_driver_input(DeploymentProfile.CONSERVE)
    _, mid_flight = runtime.snapshot("with a command in flight")
    assert pending.id in {q["id"] for q in mid_flight["queued_driver_inputs"]}
    assert pending.id not in mid_flight["acknowledged_driver_inputs"]

    second = _fresh_runtime(session)
    second.restore(mid_flight)
    second.resume_after_restore()
    landed = [e for e in second.executions if e.id == f"exe-{pending.id}"]
    assert len(landed) == 1
    for _ in range(2):
        second.advance(1.0)
    assert len([e for e in second.executions if e.id == f"exe-{pending.id}"]) == 1


# --- database outage ----------------------------------------------------------------


class _OutageFactory:
    """A session factory that fails while ``down`` and works afterwards."""

    def __init__(self, real) -> None:  # type: ignore[no-untyped-def]
        self._real = real
        self.down = True

    def __call__(self):  # type: ignore[no-untyped-def]
        if self.down:
            raise OperationalError("SELECT 1", {}, Exception("database is unavailable"))
        return self._real()


def test_a_database_outage_spools_with_sequence_continuity_and_warns(db_factory, tmp_path):
    session = start_session(db_factory, with_recorder=False)
    ticks = [session.advance(1.0) for _ in range(3)]
    published = [t.recommendation for t in ticks if t.recommendation is not None]
    assert len(published) >= 3

    outage = _OutageFactory(db_factory)
    spool = BoundedSpool(tmp_path / "spool", session.session_id, capacity=16)
    recorder = SessionRecorder(outage, session_id=session.session_id, spool=spool)  # type: ignore[arg-type]

    for tick in ticks:
        assert tick.estimate is not None and tick.recommendation is not None
        outcome = recorder.publish_recommendation(
            recommendation=tick.recommendation,
            estimate=tick.estimate,
            session_time_s=tick.session_time_s,
        )
        assert outcome.committed is False and outcome.spooled is True

    status = recorder.status()
    assert status.degraded and status.warnings and not status.exhausted
    # Sequence continuity: entries keep the order they were spooled in.
    positions = [entry.position for entry in spool.entries]
    assert positions == sorted(positions) == list(range(1, len(positions) + 1))
    spooled_ids = [entry.payload["recommendation"]["id"] for entry in spool.entries]
    assert spooled_ids == [r.id for r in published[:3]]

    # Recovery drains in the same order and nothing is lost.
    outage.down = False
    replayed, remaining = recorder.drain_spool()
    assert (replayed, remaining) == (3, 0)
    with command_transaction(db_factory) as db:
        stored = (
            db.query(Decision).filter_by(session_id=session.session_id).order_by(Decision.created_at).all()
        )
        assert [row.id for row in stored] == spooled_ids
    assert recorder.status().degraded is False


def test_an_exhausted_spool_stops_new_advice_reaching_the_store(db_factory, tmp_path):
    session = start_session(db_factory, with_recorder=False)
    ticks = [session.advance(1.0) for _ in range(3)]

    outage = _OutageFactory(db_factory)
    spool = BoundedSpool(tmp_path / "spool", session.session_id, capacity=2)
    recorder = SessionRecorder(outage, session_id=session.session_id, spool=spool)  # type: ignore[arg-type]

    results = []
    for tick in ticks:
        assert tick.estimate is not None and tick.recommendation is not None
        results.append(
            recorder.publish_recommendation(
                recommendation=tick.recommendation,
                estimate=tick.estimate,
                session_time_s=tick.session_time_s,
            )
        )
    assert results[0].spooled is True and results[0].halted is False
    assert results[1].spooled is True and results[1].halted is True  # the spool is now full
    assert results[2].committed is False and results[2].spooled is False and results[2].halted is True
    assert recorder.accepts_new_recommendations() is False
    assert len(spool) == 2, "a write was accepted past the spool's capacity"
    assert recorder.status().exhausted is True


# --- crash between commit and delivery ------------------------------------------------


def test_a_crash_after_commit_before_delivery_still_delivers_exactly_once_after_dedup(db_factory):
    """The transactional outbox closes the commit/publish gap."""
    from afterlap_api.stream import StreamHub

    # A wide client queue: this test is about the outbox, not about slow-client
    # backpressure, which test_stream.py covers separately.
    hub = StreamHub(buffer_size=1024, client_queue=512)
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    recommendation = tick.recommendation
    assert recommendation is not None

    session.take_lease()
    outcome = session.act(
        recommendation,
        __import__("afterlap_contracts", fromlist=["OperatorAction"]).OperatorAction.SELECT,
        idempotency_key="select-after-crash",
    )
    assert outcome.recommendation.status is RecommendationStatus.SELECTED

    # --- the process dies here: the lifecycle change is committed, nothing was
    # --- published, and the outbox still holds the notification.
    with command_transaction(db_factory) as db:
        unpublished = db.query(OutboxRecord).filter(OutboxRecord.published_at.is_(None)).all()
        assert unpublished, "the committed lifecycle change left no outbox row"
        pending_sequences = {(r.session_id, r.sequence) for r in unpublished}
    assert hub.subscriber_count(session.session_id) == 0

    async def restart_and_drain() -> tuple[DeduplicatingConsumer, int, int]:
        subscriber, resync = await hub.subscribe(session.session_id, 0)
        assert resync is False
        publisher = OutboxPublisher(db_factory, hub)
        first = await publisher.drain_once()
        # A second drain is what a restart mid-publish looks like. Delivery is
        # at least once; the consumer deduplicates.
        for record in list(publisher.undeliverable):
            assert record.event_type not in {e.value for e in StreamEventType}
        second_hub_deliveries = 0
        consumer = DeduplicatingConsumer()
        while not subscriber.queue.empty():
            consumer.offer(subscriber.queue.get_nowait())
        # Replay the same envelopes a second time, as an at-least-once
        # transport would after a crash between publish and mark-published.
        replayed = list(consumer.accepted)
        for envelope in replayed:
            second_hub_deliveries += 0 if consumer.offer(envelope) else 1
        return consumer, first.published, second_hub_deliveries

    consumer, published, duplicates_rejected = asyncio.run(restart_and_drain())

    assert published > 0, "the publisher delivered nothing after the restart"
    delivered = {(e.session_id, e.sequence) for e in consumer.accepted}
    assert pending_sequences & delivered, "the committed change was never delivered"
    assert duplicates_rejected == len(consumer.accepted)
    assert consumer.duplicates == len(consumer.accepted)
    # Exactly once after dedup: no sequence appears twice in the accepted set.
    sequences = [e.sequence for e in consumer.accepted]
    assert len(sequences) == len(set(sequences))
    # The lifecycle change itself is among the delivered lossless events.
    updates = consumer.of_type(StreamEventType.RECOMMENDATION_UPDATED)
    assert updates, "no recommendation_updated envelope reached the client"
    assert any(e.payload.recommendation.status is RecommendationStatus.SELECTED for e in updates)

    with command_transaction(db_factory) as db:
        still_pending = db.query(OutboxRecord).filter(OutboxRecord.published_at.is_(None)).all()
    # Only rows that cannot be represented on the stream contract remain.
    assert all(r.event_type not in {e.value for e in StreamEventType} for r in still_pending)


def test_an_execution_survives_a_restart_and_the_lifecycle_is_intact(db_factory):
    """A crash after the driver acted must not lose the execution evidence."""
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    recommendation = tick.recommendation
    assert recommendation is not None

    session.take_lease()
    from afterlap_contracts import OperatorAction

    selected = session.act(recommendation, OperatorAction.SELECT, idempotency_key="s1")
    communicated = session.act(
        selected.recommendation, OperatorAction.MARK_COMMUNICATED, idempotency_key="c1"
    )
    assert communicated.recommendation.status is RecommendationStatus.COMMUNICATED
    session.runtime.mark_communicated(recommendation.id)
    queued = session.runtime.queue_driver_input(DeploymentProfile.PUSH, recommendation_id=recommendation.id)
    executed = session.advance(1.0)
    assert [e.id for e in executed.executions] == [f"exe-{queued.id}"]
    assert executed.executions[0].match_status in (
        ExecutionMatch.MATCHED,
        ExecutionMatch.DIFFERENT_PROFILE,
    )
    assert session.status_of(recommendation.id) is RecommendationStatus.EXECUTING

    _, snapshot = session.runtime.snapshot("after execution")
    restored = _fresh_runtime(session)
    restored.restore(snapshot)
    restored.resume_after_restore()
    # The durable record is untouched by the restart, and nothing re-executes.
    assert session.status_of(recommendation.id) is RecommendationStatus.EXECUTING
    assert restored.executions == ()
    assert restored.last_recommendation is not None
    assert restored.last_recommendation.constraint_result.status in (
        CheckStatus.PASS,
        CheckStatus.UNKNOWN,
        CheckStatus.FAIL,
    )
