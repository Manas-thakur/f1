"""The concurrency cases ``backend/TECHNICAL_SPEC.md`` names explicitly.

Test concurrent selection, stale revision, duplicate command,
disconnect/resync, rule change race, interrupted export and worker restart.
"""

from __future__ import annotations

import asyncio
import json
import queue as queue_module
import threading
from pathlib import Path

import pytest
from workers.session_worker import (
    ANY_REVISION,
    SessionWorkerHandle,
    WorkerBusy,
    WorkerCommand,
    WorkerConfig,
    run_command_loop,
)

from afterlap_api.composition import RUNTIME_BUILDER
from afterlap_api.db import LifecycleError
from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import Decision, ExportJob
from afterlap_api.session import DeduplicatingConsumer, OutboxPublisher
from afterlap_api.session.runtime import UNRESOLVED_GAP_THRESHOLD, RuntimeConfig
from afterlap_contracts import (
    DeploymentProfile,
    ErrorCode,
    OperatorAction,
    PlanningStatus,
    RecommendationStatus,
    StreamEventType,
)
from afterlap_core.paths import Paths
from afterlap_core.rules import load_rule_pack

from .conftest import (
    OPERATOR,
    SCENARIO_ID,
    STRICT_RULE_PACK_ID,
    actionable,
    start_session,
)


def _published(session):  # type: ignore[no-untyped-def]
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    tick = session.advance_until(actionable)
    assert tick.recommendation is not None
    return tick.recommendation


def test_a_second_operator_cannot_race_the_lease_holder(db_factory):
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease(OPERATOR)

    with pytest.raises(LifecycleError) as refused:
        session.act(
            recommendation,
            OperatorAction.SELECT,
            idempotency_key="rival-select",
            operator_id="engineer-two",
        )
    assert refused.value.code is ErrorCode.LEASE_NOT_HELD
    assert session.status_of(recommendation.id) is RecommendationStatus.PROPOSED

    outcome = session.act(recommendation, OperatorAction.SELECT, idempotency_key="holder-select")
    assert outcome.recommendation.status is RecommendationStatus.SELECTED


def test_concurrent_selections_of_one_recommendation_produce_exactly_one_transition(db_factory):
    """Two threads racing the same recommendation: one wins, one is refused."""
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease()

    results: list[object] = []
    barrier = threading.Barrier(2)

    def select(key: str) -> None:
        barrier.wait()
        try:
            results.append(session.act(recommendation, OperatorAction.SELECT, idempotency_key=key))
        except Exception as exc:
            results.append(exc)

    threads = [threading.Thread(target=select, args=(f"race-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30.0)

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1, f"two selections both succeeded: {results}"
    assert len(failures) == 1
    assert session.status_of(recommendation.id) is RecommendationStatus.SELECTED

    with command_transaction(db_factory) as db:
        from afterlap_api.db.models import LifecycleEvent

        transitions = (
            db.query(LifecycleEvent).filter_by(decision_id=recommendation.id, to_state="selected").all()
        )
        assert len(transitions) == 1, "the race produced two selected transitions"


def test_a_stale_expected_revision_is_refused(db_factory):
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease()
    session.act(recommendation, OperatorAction.SELECT, idempotency_key="s1")

    with pytest.raises(LifecycleError) as refused:
        session.act(
            recommendation,
            OperatorAction.MARK_COMMUNICATED,
            idempotency_key="c-stale",
            expected_revision=0,
        )
    assert refused.value.code is ErrorCode.STALE_REVISION
    assert refused.value.details["current_revision"] == 1
    assert session.status_of(recommendation.id) is RecommendationStatus.SELECTED


def test_a_planning_result_for_a_superseded_revision_is_discarded(db_factory):
    """A completed solve must not overwrite a newer invalidation."""
    session = start_session(db_factory)
    tick = session.advance(1.0)
    runtime = session.runtime
    assert tick.estimate is not None and tick.rule_context is not None

    request = runtime.open_plan_request(tick.estimate, tick.rule_context)
    assert request is not None
    issued_revision = request.revision

    new_revision = runtime.invalidate("ruleset changed mid-solve")
    assert new_revision > issued_revision

    result = runtime.planner.plan(request)
    application = runtime.accept_plan_result(request, result)
    assert application.applied is False
    assert application.discarded is True
    assert application.issued_revision == issued_revision
    assert application.current_revision == new_revision
    assert "discarded" in application.reason

    fresh = runtime.open_plan_request(tick.estimate, tick.rule_context)
    assert fresh is not None
    assert runtime.accept_plan_result(fresh, runtime.planner.plan(fresh)).applied is True


def test_the_same_idempotency_key_and_body_returns_the_prior_result(db_factory):
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease()

    first = session.act(recommendation, OperatorAction.SELECT, idempotency_key="dup-1")
    second = session.act(recommendation, OperatorAction.SELECT, idempotency_key="dup-1")
    assert second.replayed is True
    assert second.recommendation.model_dump() == first.recommendation.model_dump()
    assert second.sequence == first.sequence

    with command_transaction(db_factory) as db:
        from afterlap_api.db.models import LifecycleEvent

        assert (
            db.query(LifecycleEvent).filter_by(decision_id=recommendation.id, to_state="selected").count()
            == 1
        )


def test_the_same_idempotency_key_with_a_different_body_is_a_conflict(db_factory):
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease()
    session.act(recommendation, OperatorAction.SELECT, idempotency_key="dup-2")

    with pytest.raises(LifecycleError) as conflict:
        session.act(
            recommendation,
            OperatorAction.SELECT,
            idempotency_key="dup-2",
            reason="a different body under the same key",
        )
    assert conflict.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_a_rule_change_arriving_with_a_selection_is_processed_first(db_factory):
    """API.md: if selection arrives with a rule invalidation, invalidate first."""
    session = start_session(db_factory)
    recommendation = _published(session)
    session.take_lease()

    strict = load_rule_pack(STRICT_RULE_PACK_ID)
    assert strict.ruleset_hash != recommendation.ruleset_hash
    with command_transaction(db_factory) as db:
        from afterlap_api.db.models import Session as SessionRow

        row = db.get(SessionRow, session.session_id)
        assert row is not None
        row.ruleset_hash = strict.ruleset_hash

    with pytest.raises(LifecycleError) as refused:
        session.act(recommendation, OperatorAction.SELECT, idempotency_key="race-rules")
    assert refused.value.code is ErrorCode.RECOMMENDATION_INVALIDATED
    assert session.status_of(recommendation.id) is RecommendationStatus.INVALIDATED


def test_swapping_the_rule_pack_invalidates_outstanding_advice_in_the_runtime(db_factory):
    session = start_session(db_factory)
    recommendation = _published(session)
    runtime = session.runtime
    before = runtime.revision

    revision = runtime.set_rule_pack(load_rule_pack(STRICT_RULE_PACK_ID), reason="pack promoted")
    assert revision > before
    assert runtime.last_recommendation is None
    assert session.status_of(recommendation.id) is RecommendationStatus.INVALIDATED
    assert runtime.rule_pack.ruleset_hash == load_rule_pack(STRICT_RULE_PACK_ID).ruleset_hash

    tick = session.advance(1.0)
    assert tick.rule_context is not None
    assert tick.rule_context.ruleset_hash == runtime.rule_pack.ruleset_hash
    if tick.recommendation is not None:
        assert tick.recommendation.ruleset_hash == runtime.rule_pack.ruleset_hash


def test_an_unresolved_gap_threshold_keeps_eligibility_unknown(db_factory):
    """The eligibility policy is declared, and declaring it unresolved suppresses advice."""
    config = RuntimeConfig(driver_reaction_delay_s=0.35, eligibility=UNRESOLVED_GAP_THRESHOLD)
    session = start_session(db_factory, config=config)
    session.advance(1.0)
    session.runtime.queue_driver_input(DeploymentProfile.HARVEST)
    for _ in range(28):
        tick = session.advance(1.0)
    assert tick.rule_context is not None
    assert tick.rule_context.eligibility.value == "unknown"
    assert tick.recommendation is not None
    assert tick.recommendation.action_code.value == "withdraw_advice"


def test_a_client_that_disconnects_and_returns_receives_the_gap(db_factory):
    from afterlap_api.stream import StreamHub

    hub = StreamHub(buffer_size=256, client_queue=256)
    session = start_session(db_factory)
    session.advance(1.0)

    async def scenario() -> tuple[list[int], list[int], bool]:
        publisher = OutboxPublisher(db_factory, hub)
        subscriber, _ = await hub.subscribe(session.session_id, 0)
        await publisher.drain_once()
        seen: list[int] = []
        while not subscriber.queue.empty():
            seen.append(subscriber.queue.get_nowait().sequence)
        await hub.unsubscribe(subscriber)

        session.advance(1.0)
        await publisher.drain_once()

        reconnected, resync = await hub.subscribe(session.session_id, max(seen))
        gap: list[int] = []
        while not reconnected.queue.empty():
            gap.append(reconnected.queue.get_nowait().sequence)
        return seen, gap, resync

    seen, gap, resync = asyncio.run(scenario())
    assert seen and gap
    assert resync is False, "a cursor inside the buffer must not force a resync"
    assert min(gap) > max(seen), "the replay repeated envelopes the client already had"
    assert gap == sorted(gap)


def test_an_interrupted_export_leaves_no_partial_file(db_factory, tmp_path, monkeypatch):
    """A failure mid-write must not leave a half-written export a reader could load."""
    from afterlap_api.routes import exports as export_routes

    session = start_session(db_factory)
    session.advance(1.0)
    session.sync()

    paths = Paths.default(tmp_path).ensure()
    target = paths.exports / "interrupted.json"

    def explode(path: Path, text: str) -> Path:
        raise OSError("the export volume disappeared mid-write")

    monkeypatch.setattr(export_routes, "atomic_write_text", explode)
    with command_transaction(db_factory) as db:
        from afterlap_api.db.models import Session as SessionRow

        row = db.get(SessionRow, session.session_id)
        assert row is not None
        body = export_routes.build_export_body(db, row, None, None)
    with pytest.raises(OSError):
        export_routes._write(target, body, "json")

    assert not target.exists(), "an interrupted export left a file behind"
    assert list(paths.exports.glob("*.staging")) == []
    with command_transaction(db_factory) as db:
        assert db.query(ExportJob).count() == 0, "a failed export was recorded as a job"

    monkeypatch.undo()
    written = export_routes._write(target, body, "json")
    reloaded = json.loads(Path(written).read_text(encoding="utf-8"))
    assert reloaded["session"]["id"] == session.session_id
    assert reloaded["hashes"]["ruleset"] == session.manifest.ruleset_hash


def _drive(config: WorkerConfig):  # type: ignore[no-untyped-def]
    """Run the worker loop in this process over plain queues."""
    commands: queue_module.Queue = queue_module.Queue(maxsize=8)
    results: queue_module.Queue = queue_module.Queue(maxsize=8)
    thread = threading.Thread(target=run_command_loop, args=(commands, results, config), daemon=True)
    thread.start()
    return commands, results, thread


def test_the_worker_loop_refuses_stale_and_expired_commands(db_factory):
    session = start_session(db_factory)
    config = WorkerConfig(
        session_id=session.session_id,
        scenario_id=SCENARIO_ID,
        ruleset_id="synthetic-pack-v1",
        seed=42,
        runtime_builder=RUNTIME_BUILDER,
    )
    commands, results, thread = _drive(config)
    try:
        init = WorkerCommand.now("initialise", config.session_id)
        commands.put(init)
        first = results.get(True, 60.0)
        assert first.ok is True and first.command_id == init.command_id
        revision = first.revision

        observe = WorkerCommand.now("observe", config.session_id, expected_revision=revision, duration_s=1.0)
        commands.put(observe)
        second = results.get(True, 60.0)
        assert second.ok is True and second.stale is False
        assert second.payload["has_estimate"] is True
        moved = second.revision
        assert moved != revision

        stale = WorkerCommand.now("observe", config.session_id, expected_revision=revision, duration_s=1.0)
        commands.put(stale)
        third = results.get(True, 60.0)
        assert third.stale is True and third.ok is False
        assert third.revision == moved, "a stale command was executed anyway"

        expired = WorkerCommand(
            kind="observe",
            session_id=config.session_id,
            expected_revision=ANY_REVISION,
            deadline_monotonic_s=1.0,
            payload={"duration_s": 1.0},
        )
        commands.put(expired)
        fourth = results.get(True, 60.0)
        assert fourth.ok is False and "deadline expired" in (fourth.detail or "")
        assert fourth.revision == moved
    finally:
        commands.put(None)
        thread.join(30.0)


def test_the_worker_queue_is_bounded_and_refuses_rather_than_buffering(db_factory):
    session = start_session(db_factory)
    handle = SessionWorkerHandle(
        WorkerConfig(
            session_id=session.session_id,
            scenario_id=SCENARIO_ID,
            ruleset_id="synthetic-pack-v1",
            seed=42,
            runtime_builder=RUNTIME_BUILDER,
        ),
        queue_size=1,
    )
    handle._process = _AlwaysAlive()  # type: ignore[assignment]
    handle.send(WorkerCommand.now("observe", session.session_id))
    with pytest.raises(WorkerBusy):
        for _ in range(8):
            handle.send(WorkerCommand.now("observe", session.session_id))


class _AlwaysAlive:
    def is_alive(self) -> bool:
        return True


@pytest.mark.slow
def test_a_spawned_worker_process_serves_and_restarts(db_factory):
    """The real ``spawn`` transport, end to end, including a restart."""
    session = start_session(db_factory)
    config = WorkerConfig(
        session_id=session.session_id,
        scenario_id=SCENARIO_ID,
        ruleset_id="synthetic-pack-v1",
        seed=42,
        runtime_builder=RUNTIME_BUILDER,
    )
    handle = SessionWorkerHandle(config, queue_size=4)
    handle.start()
    try:
        assert handle.alive
        first = handle.request(WorkerCommand.now("initialise", config.session_id), timeout_s=180.0)
        assert first.ok is True, first.detail
        observed = handle.request(
            WorkerCommand.now("observe", config.session_id, duration_s=1.0), timeout_s=180.0
        )
        assert observed.ok is True
        assert observed.payload["has_estimate"] is True
        snapshot = handle.request(
            WorkerCommand.now("snapshot", config.session_id, label="worker"), timeout_s=180.0
        )
        assert snapshot.ok is True and snapshot.payload["snapshot_hash"].startswith("sha256:")
    finally:
        handle.kill()
    assert handle.alive is False

    restarted = SessionWorkerHandle(config, queue_size=4)
    restarted.start()
    try:
        assert restarted.alive
        again = restarted.request(WorkerCommand.now("initialise", config.session_id), timeout_s=180.0)
        assert again.ok is True
        assert again.revision == 1
    finally:
        restarted.stop()


def test_a_reconnecting_client_deduplicates_repeated_deliveries(db_factory):
    from afterlap_api.stream import StreamHub

    hub = StreamHub(buffer_size=256, client_queue=256)
    session = start_session(db_factory)
    session.advance(1.0)

    async def scenario() -> DeduplicatingConsumer:
        publisher = OutboxPublisher(db_factory, hub)
        first, _ = await hub.subscribe(session.session_id, 0)
        await publisher.drain_once()
        consumer = DeduplicatingConsumer()
        while not first.queue.empty():
            consumer.offer(first.queue.get_nowait())
        await hub.unsubscribe(first)
        again, _ = await hub.subscribe(session.session_id, 0)
        while not again.queue.empty():
            consumer.offer(again.queue.get_nowait())
        return consumer

    consumer = asyncio.run(scenario())
    assert consumer.accepted
    assert consumer.duplicates > 0, "the reconnect delivered no overlap to deduplicate"
    sequences = [e.sequence for e in consumer.accepted]
    assert len(sequences) == len(set(sequences))
    assert all(e.event_type is not StreamEventType.HEARTBEAT for e in consumer.accepted)


def test_a_withdrawn_decision_is_still_a_published_decision(db_factory):
    """A withdrawal is a decision record, not an absence of one."""
    session = start_session(db_factory)
    tick = session.advance(1.0)
    assert tick.recommendation is not None
    assert tick.planning is not None
    assert tick.planning.status in (
        PlanningStatus.OK,
        PlanningStatus.INPUT_UNAVAILABLE,
        PlanningStatus.RULES_UNKNOWN,
        PlanningStatus.NO_FEASIBLE_CANDIDATE,
    )
    with command_transaction(db_factory) as db:
        assert db.get(Decision, tick.recommendation.id) is not None
