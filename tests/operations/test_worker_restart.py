"""Session-worker termination mid-session, and recovery from its snapshot.

**Genuinely causes the condition.** `tests/backend/test_recovery.py` simulates
the crash by detaching the runtime from the registry inside one process. This
drill spawns a real operating-system process with `multiprocessing`'s `spawn`
start method, drives a real session inside it over the bounded typed queues,
takes a real snapshot that is serialised *across the process boundary*, and
then terminates the process with `Process.terminate()`. The child gets no
chance to clean up: there is no sentinel, no `stop`, no flush.

Everything asserted afterwards is therefore recovery from a snapshot produced
by a process that no longer exists.

The drill runs the worker in the shape that used to be its defect: a
`WorkerConfig` with no `database_url`, which records nothing. That is now an
explicit choice rather than the only behaviour available, and
`test_an_out_of_process_session_persists_its_own_decisions` drives a second
worker configured with a store and reads its rows back from the database. So
part 3 below still rebuilds the dead worker's advice through a real
`SessionRecorder` to have something to invalidate, and that is a property of
this particular unconfigured worker rather than of the worker protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from workers.session_worker import (
    SessionWorkerHandle,
    WorkerCommand,
    WorkerConfig,
    WorkerUnavailable,
)

from afterlap_api.composition import RUNTIME_BUILDER
from afterlap_api.session import InProcessSessionRuntime, SessionRecorder
from afterlap_api.session.runtime import SNAPSHOT_SCHEMA
from afterlap_contracts import Recommendation, RecommendationStatus
from afterlap_core.rules import load_rule_pack
from afterlap_core.simulation import load_bundle

from .conftest import (
    RULE_PACK_ID,
    SCENARIO_ID,
    SEED,
    _persist_session_row,
    open_store,
    start_session,
)

if TYPE_CHECKING:
    from pathlib import Path

MAX_OBSERVES = 40
COMMAND_TIMEOUT_S = 240.0


@pytest.fixture(scope="module")
def killed_worker(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Drive a real worker process to an actionable instruction, then kill it.

    Module-scoped so the *same* dead process's snapshot is what both tests
    below work from. Spawning and driving takes about two seconds; doing it
    once keeps the two claims about one event rather than two.
    """
    config = WorkerConfig(
        session_id="ops-worker-drill",
        scenario_id=SCENARIO_ID,
        ruleset_id=RULE_PACK_ID,
        seed=SEED,
        runtime_builder=RUNTIME_BUILDER,
    )
    handle = SessionWorkerHandle(config)
    handle.start()
    assert handle.alive, "the worker process did not start"
    pid = handle._process.pid
    assert isinstance(pid, int) and pid > 0

    def request(kind: str, **payload: Any) -> Any:
        result = handle.request(
            WorkerCommand.now(kind, config.session_id, timeout_s=COMMAND_TIMEOUT_S, **payload),  # type: ignore[arg-type]
            timeout_s=COMMAND_TIMEOUT_S,
        )
        assert result.ok, f"{kind} failed in the worker: {result.detail}"
        return result

    request("initialise")

    actionable_at: float | None = None
    recommendation_id: str | None = None
    for _ in range(MAX_OBSERVES):
        tick = request("observe", duration_s=1.0).payload
        if tick["constraint_status"] == "pass" and tick["action_code"] != "withdraw_advice":
            actionable_at = tick["session_time_s"]
            recommendation_id = tick["recommendation_id"]
            break
    assert actionable_at is not None, "the worker never reached an actionable instruction"

    landed = request("apply_simulator_input", profile_id="harvest").payload
    executed = request("observe", duration_s=1.0).payload
    assert executed["execution_ids"] == [f"exe-{landed['queued_input_id']}"], executed

    pending = request("apply_simulator_input", profile_id="conserve").payload

    snapshot = request("snapshot", label="before the kill", include_payload=True).payload
    payload = snapshot["payload"]
    assert payload is not None, "the worker returned no snapshot payload"

    handle.kill()
    process_after = handle._process

    return {
        "config": config,
        "handle": handle,
        "pid": pid,
        "process_after_kill": process_after,
        "actionable_at_s": actionable_at,
        "recommendation_id": recommendation_id,
        "acknowledged_input_id": landed["queued_input_id"],
        "pending_input_id": pending["queued_input_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "snapshot": payload,
        "root": tmp_path_factory.mktemp("worker-restart"),
    }


def test_a_terminated_session_worker_is_visibly_unavailable(killed_worker: dict[str, Any]):
    handle: SessionWorkerHandle = killed_worker["handle"]
    config: WorkerConfig = killed_worker["config"]

    print(f"\nterminated worker pid {killed_worker['pid']}")
    assert handle.alive is False, "the worker is still running after terminate()"
    assert handle._process is None, "the handle still holds a process reference"

    with pytest.raises(WorkerUnavailable):
        handle.send(WorkerCommand.now("observe", config.session_id, timeout_s=5.0))

    snapshot = killed_worker["snapshot"]
    assert snapshot["schema"] == SNAPSHOT_SCHEMA
    assert snapshot["session_id"] == config.session_id, (
        "the worker's runtime owns a different session id from the one commands route by, so its "
        "durable records would be unreachable from the commands that produced them"
    )
    assert snapshot["session_time_s"] > 26.0, snapshot["session_time_s"]
    offset = snapshot["event_offset"]
    assert offset["sequence"] >= 1, offset
    assert offset["newest_event_time_s"] is not None
    assert offset["delivered_event_ids"], "the event offset names no delivered observations"
    assert killed_worker["snapshot_hash"].startswith("sha256:")
    print(
        f"snapshot at t={snapshot['session_time_s']:.2f}s, revision {snapshot['revision']}, "
        f"event sequence {offset['sequence']}, "
        f"{len(offset['delivered_event_ids'])} delivered observation ids"
    )

    assert killed_worker["acknowledged_input_id"] in snapshot["acknowledged_driver_inputs"]
    queued_ids = {q["id"] for q in snapshot["queued_driver_inputs"]}
    assert killed_worker["pending_input_id"] in queued_ids
    assert killed_worker["acknowledged_input_id"] not in queued_ids


def test_a_replacement_worker_process_starts_and_serves_the_same_session(killed_worker: dict[str, Any]):
    """A restart is a new process, and it must actually serve commands."""
    config: WorkerConfig = killed_worker["config"]
    replacement = SessionWorkerHandle(config)
    replacement.start()
    try:
        assert replacement.alive
        assert replacement._process.pid != killed_worker["pid"]
        result = replacement.request(
            WorkerCommand.now("initialise", config.session_id, timeout_s=COMMAND_TIMEOUT_S),
            timeout_s=COMMAND_TIMEOUT_S,
        )
        assert result.ok, result.detail
        print(f"\nreplacement worker pid {replacement._process.pid} initialised")

        stale = replacement.request(
            WorkerCommand.now(
                "observe",
                config.session_id,
                expected_revision=killed_worker["snapshot"]["revision"],
                timeout_s=COMMAND_TIMEOUT_S,
                duration_s=1.0,
            ),
            timeout_s=COMMAND_TIMEOUT_S,
        )
        assert stale.ok is False and stale.stale is True, stale
        print(f"stale command refused: {stale.detail}")
    finally:
        replacement.stop()


def test_recovery_invalidates_expiring_advice_restores_state_and_never_replays(
    killed_worker: dict[str, Any], tmp_path: Path
):
    snapshot = killed_worker["snapshot"]
    store = open_store(tmp_path / "db")

    session = start_session(store.factory, spool_root=tmp_path / "spool")

    published = snapshot["recommendations"]
    assert published, "the dead worker's snapshot carries no published advice"
    recorder: SessionRecorder = session.recorder  # type: ignore[assignment]
    outstanding: list[str] = []
    live_estimate = session.runtime.last_estimate or session.advance(1.0).estimate
    assert live_estimate is not None
    for body in published.values():
        recommendation = Recommendation.model_validate(body).revise(session_id=session.session_id)
        if recommendation.status is not RecommendationStatus.PROPOSED:
            continue
        outcome = recorder.publish_recommendation(
            recommendation=recommendation,
            estimate=live_estimate,
            session_time_s=snapshot["session_time_s"],
        )
        assert outcome.committed, outcome
        outstanding.append(recommendation.id)
    assert outstanding, "no outstanding advice existed to invalidate"
    print(
        f"\noutstanding advice carried over the crash: {len(outstanding)} recommendation(s), "
        f"newest {outstanding[-1]}"
    )

    session.runtime.invalidate("session worker process terminated mid-session")
    for recommendation_id in outstanding:
        assert session.status_of(recommendation_id) is RecommendationStatus.INVALIDATED, (
            f"{recommendation_id} survived the crash as live advice"
        )

    replacement = InProcessSessionRuntime(
        bundle=load_bundle(SCENARIO_ID),
        pack=load_rule_pack(RULE_PACK_ID),
        planner=session.runtime.planner,
        config=session.runtime.config,
        recorder=recorder,
    )
    replacement.initialise(session.manifest, SCENARIO_ID, SEED)
    replacement.restore(snapshot)

    assert replacement.session_time_s == pytest.approx(snapshot["session_time_s"], abs=1e-9)
    assert replacement.revision > snapshot["revision"], "the restored session reuses a stale revision"

    assert replacement.ready is False
    assert replacement.last_estimate is None
    assert replacement.last_recommendation is None
    print(f"restored at t={replacement.session_time_s:.2f}s, revision {replacement.revision}, ready=False")

    resumed = replacement.resume_after_restore()
    assert replacement.ready is True
    assert resumed.estimate is not None, "the session resumed without re-estimating"
    assert resumed.rule_context is not None, "the session resumed without re-resolving the rules"
    assert resumed.recommendation is not None
    assert resumed.recommendation.constraint_result.checked_at_s >= snapshot["session_time_s"]
    assert resumed.recommendation.id not in outstanding, "the invalidated advice was re-published"
    print(
        f"resumed: estimate cutoff {resumed.estimate.cutoff_s:.2f}s, "
        f"advice {resumed.recommendation.action_code.value}, "
        f"re-checked {resumed.recommendation.constraint_result.status.value} at "
        f"{resumed.recommendation.constraint_result.checked_at_s:.2f}s"
    )

    acknowledged = killed_worker["acknowledged_input_id"]
    pending = killed_worker["pending_input_id"]
    for _ in range(4):
        replacement.advance(1.0)
    execution_ids = {event.id for event in replacement.executions}
    assert f"exe-{acknowledged}" not in execution_ids, (
        "a driver command the driver had already carried out was re-actuated after the restart"
    )

    landed = [event for event in replacement.executions if event.id == f"exe-{pending}"]
    assert len(landed) == 1, f"the in-flight command produced {len(landed)} executions, expected 1"
    for _ in range(2):
        replacement.advance(1.0)
    assert len([e for e in replacement.executions if e.id == f"exe-{pending}"]) == 1
    print(
        f"no-replay: acknowledged {acknowledged} produced no execution; "
        f"in-flight {pending} produced exactly one"
    )

    _, again = replacement.snapshot("after recovery")
    assert acknowledged in again["acknowledged_driver_inputs"]


def test_an_out_of_process_session_persists_its_own_decisions(tmp_path: Path):
    """A configured worker writes its own audit trail, in its own process.

    Nothing here is stood in for. A second operating-system process is spawned
    with a `database_url` and an `artifact_root`, driven to an actionable
    instruction, and stopped; the rows are then read back from the SQLite file
    the *child* wrote. Before this, `SessionFactory()` in the child had no
    recorder, so everything an out-of-process session decided died with it.
    """
    from sqlalchemy import select

    from afterlap_api.db.engine import create_db_engine, create_session_factory, transaction
    from afterlap_api.db.models import Decision, Session as SessionRow

    store = open_store(tmp_path / "db", "worker.sqlite3")
    database = store.path
    config = WorkerConfig(
        session_id="ops-worker-durable",
        scenario_id=SCENARIO_ID,
        ruleset_id=RULE_PACK_ID,
        seed=SEED,
        runtime_builder=RUNTIME_BUILDER,
        database_url=f"sqlite+pysqlite:///{database.as_posix()}",
        artifact_root=str(tmp_path / "artifacts-root"),
    )
    _persist_session_row(store.factory, _manifest_for(config))

    handle = SessionWorkerHandle(config)
    assert handle.records_durably is True
    handle.start()
    try:

        def request(kind: str, **payload: Any) -> Any:
            result = handle.request(
                WorkerCommand.now(kind, config.session_id, timeout_s=COMMAND_TIMEOUT_S, **payload),  # type: ignore[arg-type]
                timeout_s=COMMAND_TIMEOUT_S,
            )
            assert result.ok, f"{kind} failed in the worker: {result.detail}"
            return result

        request("initialise")
        published: list[str] = []
        for _ in range(MAX_OBSERVES):
            tick = request("observe", duration_s=1.0).payload
            if tick["recommendation_id"] is not None:
                published.append(tick["recommendation_id"])
            if tick["constraint_status"] == "pass" and tick["action_code"] != "withdraw_advice":
                break
        assert published, "the worker published no advice to record"
    finally:
        handle.stop()

    assert database.is_file(), "the child process wrote no database at all"
    engine = create_db_engine(config.database_url)
    with transaction(create_session_factory(engine)) as db:
        rows = list(db.execute(select(Decision.id, Decision.session_id)).all())
        sessions = list(db.execute(select(SessionRow.id)).scalars())
    engine.dispose()

    recorded = {row[0] for row in rows}
    print(f"\nthe child recorded {len(recorded)} decision(s) for session(s) {sessions}")
    assert recorded, "an out-of-process session recorded no decisions"
    assert recorded >= set(published[:1]), (
        f"the worker's published advice {published[:1]} is not in its own store {sorted(recorded)}"
    )
    assert {row[1] for row in rows} == {config.session_id}, (
        "the child's records carry a different session id from the one commands route by"
    )


def _manifest_for(config: WorkerConfig) -> Any:
    """The session row the control plane registers before spawning a worker.

    Lifecycle rows stay the control plane's to create: a decision has a foreign
    key onto its session, so a worker recording into a session nobody
    registered would be writing an orphan.
    """
    from afterlap_api.session.factory import build_manifest, resolve_artefacts
    from afterlap_contracts import SessionMode

    artefacts = resolve_artefacts(scenario_id=config.scenario_id, ruleset_id=config.ruleset_id)
    return build_manifest(
        artefacts,
        mode=SessionMode.SIMULATION,
        seed=config.seed,
        label=config.label,
        session_id=config.session_id,
    )
