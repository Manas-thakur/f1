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

One thing is approximated and it is worth stating plainly: the spawned worker
builds its runtime through `SessionFactory()` with **no recorder**
(`workers/session_worker._build_runtime`), so an out-of-process session
persists nothing at all. Part 2 below therefore persists the dead worker's
own recommendation — rebuilt from its snapshot, byte for byte — through a real
`SessionRecorder`, standing in for the recorder the worker does not have. That
gap is a real defect and it is recorded in `handoffs/A14.md`, not hidden here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from afterlap_api.session import InProcessSessionRuntime, SessionRecorder
from afterlap_api.session.runtime import SNAPSHOT_SCHEMA
from afterlap_contracts import Recommendation, RecommendationStatus
from afterlap_core.rules import load_rule_pack
from afterlap_core.simulation import load_bundle
from workers.session_worker import (
    SessionWorkerHandle,
    WorkerCommand,
    WorkerConfig,
    WorkerUnavailable,
)

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED, open_store, start_session

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

    # A deliberate driver input that lands: it is acknowledged before the kill.
    landed = request("apply_simulator_input", profile_id="harvest").payload
    executed = request("observe", duration_s=1.0).payload
    assert executed["execution_ids"] == [f"exe-{landed['queued_input_id']}"], executed

    # A second input that has NOT landed when the snapshot is taken: it is
    # queued, behind the reaction delay, and must survive the restart.
    pending = request("apply_simulator_input", profile_id="conserve").payload

    snapshot = request("snapshot", label="before the kill", include_payload=True).payload
    payload = snapshot["payload"]
    assert payload is not None, "the worker returned no snapshot payload"

    # --- the process dies. terminate(), no sentinel, no clean stop. --------- #
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


# --------------------------------------------------------------------------- #
# part 1: the process really died, and its snapshot really crossed the boundary
# --------------------------------------------------------------------------- #


def test_a_terminated_session_worker_is_visibly_unavailable(killed_worker: dict[str, Any]):
    handle: SessionWorkerHandle = killed_worker["handle"]
    config: WorkerConfig = killed_worker["config"]

    print(f"\nterminated worker pid {killed_worker['pid']}")
    assert handle.alive is False, "the worker is still running after terminate()"
    assert handle._process is None, "the handle still holds a process reference"

    # Unavailable is *visible*: the handle refuses rather than buffering a
    # command for a process that will never read it.
    with pytest.raises(WorkerUnavailable):
        handle.send(WorkerCommand.now("observe", config.session_id, timeout_s=5.0))

    # The snapshot survived the process boundary: it was pickled through the
    # results queue by a process that no longer exists.
    snapshot = killed_worker["snapshot"]
    assert snapshot["schema"] == SNAPSHOT_SCHEMA
    # The snapshot carries the id of the manifest the worker's own
    # `SessionFactory` minted, *not* `WorkerConfig.session_id`, which is only
    # used to route commands. So a spawned worker's session identity does not
    # match the id the control plane holds. Asserted as observed rather than
    # as intended; it is a real defect and is recorded in handoffs/A14.md.
    assert snapshot["session_id"].startswith("ses-"), snapshot["session_id"]
    assert snapshot["session_id"] != config.session_id, (
        "the worker now propagates WorkerConfig.session_id into the runtime; if that was fixed "
        "deliberately, tighten this assertion to equality"
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

    # The acknowledged command is recorded as acknowledged; the pending one is
    # still queued. That distinction is what makes no-replay decidable.
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

        # A command issued against the *dead* worker's revision is refused as
        # stale rather than executed against a session that restarted at zero.
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


# --------------------------------------------------------------------------- #
# part 2: recovery in the replacement runtime
# --------------------------------------------------------------------------- #


def test_recovery_invalidates_expiring_advice_restores_state_and_never_replays(
    killed_worker: dict[str, Any], tmp_path: Path
):
    snapshot = killed_worker["snapshot"]
    store = open_store(tmp_path / "db")

    # A session row and a recorder for the replacement process. The session id
    # is the dead worker's, so the durable records belong to the same session.
    session = start_session(store.factory, spool_root=tmp_path / "spool")

    # Persist the advice the dead worker published, rebuilt from its own
    # snapshot. (The worker itself had no recorder — see the module docstring.)
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

    # 1. Expiring advice is invalidated *before* anything resumes.
    session.runtime.invalidate("session worker process terminated mid-session")
    for recommendation_id in outstanding:
        assert session.status_of(recommendation_id) is RecommendationStatus.INVALIDATED, (
            f"{recommendation_id} survived the crash as live advice"
        )

    # 2. State restores from the snapshot and the event offset.
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

    # Not ready until it has re-estimated and revalidated. Nothing published.
    assert replacement.ready is False
    assert replacement.last_estimate is None
    assert replacement.last_recommendation is None
    print(f"restored at t={replacement.session_time_s:.2f}s, revision {replacement.revision}, ready=False")

    resumed = replacement.resume_after_restore()
    assert replacement.ready is True
    assert resumed.estimate is not None, "the session resumed without re-estimating"
    assert resumed.rule_context is not None, "the session resumed without re-resolving the rules"
    assert resumed.recommendation is not None
    # Whatever is published after the restart carries a fresh independent check.
    assert resumed.recommendation.constraint_result.checked_at_s >= snapshot["session_time_s"]
    assert resumed.recommendation.id not in outstanding, "the invalidated advice was re-published"
    print(
        f"resumed: estimate cutoff {resumed.estimate.cutoff_s:.2f}s, "
        f"advice {resumed.recommendation.action_code.value}, "
        f"re-checked {resumed.recommendation.constraint_result.status.value} at "
        f"{resumed.recommendation.constraint_result.checked_at_s:.2f}s"
    )

    # 3. The acknowledged driver command is never replayed.
    acknowledged = killed_worker["acknowledged_input_id"]
    pending = killed_worker["pending_input_id"]
    for _ in range(4):
        replacement.advance(1.0)
    execution_ids = {event.id for event in replacement.executions}
    assert f"exe-{acknowledged}" not in execution_ids, (
        "a driver command the driver had already carried out was re-actuated after the restart"
    )

    # ... while the command that had *not* landed is applied exactly once.
    landed = [event for event in replacement.executions if event.id == f"exe-{pending}"]
    assert len(landed) == 1, f"the in-flight command produced {len(landed)} executions, expected 1"
    for _ in range(2):
        replacement.advance(1.0)
    assert len([e for e in replacement.executions if e.id == f"exe-{pending}"]) == 1
    print(
        f"no-replay: acknowledged {acknowledged} produced no execution; "
        f"in-flight {pending} produced exactly one"
    )

    # And the knowledge itself survived: a fresh snapshot still names it.
    _, again = replacement.snapshot("after recovery")
    assert acknowledged in again["acknowledged_driver_inputs"]
