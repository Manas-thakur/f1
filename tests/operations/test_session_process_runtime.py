"""The production session backend: a spawned owner, its transport and its refusals.

`ProcessSessionRuntime` is what a deployment now runs. `InProcessSessionRuntime`
is the development and test adapter, and `Settings.session_runtime_backend`
defaults to `"process"`. That makes the local process boundary a production
code path rather than a laboratory one, so what it does under load, under a
crash and under a malformed message has to be pinned down here.

Three groups of claims, and nothing in any of them is stood in for:

* **Transport.** The refusals happen before execution, so they are asserted by
  driving the real `run_command_loop` over plain `queue.Queue` objects in this
  process and reading what came back. Only the transport differs from
  production; the loop is the same function.
* **Fidelity.** A real operating-system process is spawned, driven to an
  actionable instruction, and the reconstructed `RuntimeTick` is checked field
  by field including nested contract members. A flat summary does not satisfy
  it. The same payload is then checked to carry no simulator truth.
* **Failure.** A real child is terminated with `Process.terminate()` and every
  subsequent call is required to answer explicitly and promptly: an
  unavailable result, never a hang and never a silent success.

`multiprocessing`'s `spawn` start method is asserted on every platform, without
a skip, because a child that inherited the parent's loaded artefacts, database
handles or RNG state would be a different program on Linux from the one that
runs on Windows.
"""

from __future__ import annotations

import contextlib
import json
import multiprocessing as mp
import queue as queue_module
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from afterlap_api.composition import RUNTIME_BUILDER, ProcessSessionFactory
from afterlap_api.db import create_all
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.session.factory import build_manifest, resolve_artefacts
from afterlap_application.process_runtime import (
    ANY_REVISION,
    ProcessSessionRuntime,
    SessionWorkerHandle,
    WorkerBusy,
    WorkerCommand,
    WorkerConfig,
    WorkerResult,
    WorkerUnavailable,
    _tick_payload,
    run_command_loop,
)
from afterlap_application.runtime import (
    RuntimeHealth,
    RuntimePersistence,
    RuntimeRegistry,
    RuntimeTick,
    RuntimeUnavailable,
)
from afterlap_contracts import (
    CapabilityState,
    CheckStatus,
    PlanningResult,
    Recommendation,
    RuleContext,
    SessionManifest,
    SessionMode,
    StateEstimate,
)
from afterlap_core.simulation import WorldState

from .conftest import OPERATOR, RULE_PACK_ID, SCENARIO_ID, SEED, actionable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

COMMAND_TIMEOUT_S = 240.0
"""Generous on purpose: a spawned child imports the whole application first."""

CRASH_TIMEOUT_S = 90.0
"""Long enough that a crash answered inside ten seconds cannot be a timeout."""

CRASH_DETECTION_BUDGET_S = 10.0
MAX_OBSERVES = 40
LOOP_RESULT_TIMEOUT_S = 120.0

TICK_PAYLOAD_KEYS = frozenset(
    {
        "session_time_s",
        "revision",
        "estimate",
        "rule_context",
        "planning",
        "recommendation",
        "executions",
        "finished",
        "has_estimate",
        "estimate_cutoff_s",
        "planning_status",
        "recommendation_id",
        "action_code",
        "constraint_status",
        "execution_ids",
    }
)
"""Everything a tick may carry across the boundary, and nothing else."""

FORBIDDEN_TICK_WORDS = ("world", "truth", "rng_state", "integrator_state")


def _config(session_id: str, **overrides: Any) -> WorkerConfig:
    """A worker configuration for the repository's synthetic scenario."""
    fields: dict[str, Any] = {
        "session_id": session_id,
        "scenario_id": SCENARIO_ID,
        "ruleset_id": RULE_PACK_ID,
        "seed": SEED,
        "runtime_builder": RUNTIME_BUILDER,
    }
    fields.update(overrides)
    return WorkerConfig(**fields)


def _manifest_for(config: WorkerConfig) -> SessionManifest:
    """The frozen identity the control plane resolves before a child exists."""
    artefacts = resolve_artefacts(scenario_id=config.scenario_id, ruleset_id=config.ruleset_id)
    return build_manifest(
        artefacts,
        mode=SessionMode.SIMULATION,
        seed=config.seed,
        label=config.label,
        session_id=config.session_id,
    )


class _AlwaysAlive:
    """A stand-in child that is reachable, so transport can be tested without spawn."""

    exitcode: int | None = None
    pid: int = -1

    def is_alive(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> None:
        return None

    def terminate(self) -> None:
        return None


def _release(handle: SessionWorkerHandle) -> None:
    """Drop a handle whose ``_process`` is a stand-in, without joining a child."""
    handle._process = None
    for pipe in (handle._commands, handle._results):
        with contextlib.suppress(Exception):
            for _ in range(32):
                pipe.get(True, 0.2)
    handle.stop()


class _LoopHarness:
    """`run_command_loop` served in this process over plain `queue.Queue` objects.

    The loop is a plain function over two queue objects precisely so a drill can
    do this: production swaps the transport for `multiprocessing.Queue` and
    changes nothing else, so a refusal proved here is the refusal production
    performs.
    """

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.commands: queue_module.Queue[Any] = queue_module.Queue(maxsize=8)
        self.results: queue_module.Queue[Any] = queue_module.Queue(maxsize=8)
        self.thread = threading.Thread(
            target=run_command_loop, args=(self.commands, self.results, config), daemon=True
        )
        self.thread.start()

    def send(self, item: Any) -> None:
        self.commands.put(item)

    def request(self, command: WorkerCommand) -> WorkerResult:
        self.commands.put(command)
        result = self.results.get(True, LOOP_RESULT_TIMEOUT_S)
        assert isinstance(result, WorkerResult), f"the loop produced a {type(result).__name__}"
        assert result.command_id == command.command_id, "the loop answered a different command"
        return result

    def state(self) -> WorkerResult:
        """The current revision and clock, read without changing either."""
        return self.request(WorkerCommand.now("tick", self.config.session_id, timeout_s=COMMAND_TIMEOUT_S))

    def close(self) -> None:
        self.commands.put(None)
        self.thread.join(60.0)


@pytest.fixture(scope="module")
def command_loop() -> Iterator[_LoopHarness]:
    """One initialised loop shared by the transport claims, which never advance it."""
    harness = _LoopHarness(_config("ops-process-transport"))
    first = harness.request(
        WorkerCommand.now("initialise", harness.config.session_id, timeout_s=COMMAND_TIMEOUT_S)
    )
    assert first.ok is True, first.detail
    yield harness
    harness.close()


@pytest.fixture(scope="module")
def spawned_session() -> Iterator[dict[str, Any]]:
    """A real spawned child driven to an actionable instruction.

    Module-scoped because both tick claims are about the *same* crossing: the
    tick that came back and the payload it came back in.
    """
    config = _config("ops-process-tick")
    runtime = ProcessSessionRuntime(config, queue_size=8, command_timeout_s=COMMAND_TIMEOUT_S)
    started = time.monotonic()
    first = runtime.initialise(_manifest_for(config), config.scenario_id, config.seed)
    tick = first
    observes = 0
    for _ in range(MAX_OBSERVES):
        tick = runtime.advance(1.0)
        observes += 1
        if actionable(tick):
            break
    elapsed = time.monotonic() - started
    yield {
        "config": config,
        "runtime": runtime,
        "initial": first,
        "tick": tick,
        "observes": observes,
        "elapsed_s": elapsed,
    }
    runtime.stop()


@pytest.fixture(scope="module")
def dead_session() -> Iterator[dict[str, Any]]:
    """A real child terminated mid-session, plus how fast the next command answered.

    `Process.terminate()`, so the child gets no chance to flush, answer or say
    goodbye. Everything asserted from this fixture is behaviour against a
    process that no longer exists.
    """
    config = _config("ops-process-crash")
    runtime = ProcessSessionRuntime(config, queue_size=8, command_timeout_s=CRASH_TIMEOUT_S)
    runtime.initialise(_manifest_for(config), config.scenario_id, config.seed)
    runtime.advance(1.0)
    pid = runtime._handle._process.pid
    assert isinstance(pid, int) and pid > 0
    runtime._handle.kill()

    started = time.monotonic()
    with pytest.raises(RuntimeUnavailable) as refusal:
        runtime.advance(1.0)
    elapsed_s = time.monotonic() - started

    yield {
        "config": config,
        "runtime": runtime,
        "pid": pid,
        "refusal": refusal.value,
        "elapsed_s": elapsed_s,
    }
    runtime.stop()


def test_the_session_worker_uses_the_spawn_start_method_on_every_platform():
    """`spawn` is chosen explicitly, never inherited from the platform default."""
    handle = SessionWorkerHandle(_config("ops-process-spawn"))
    try:
        platform_default = mp.get_context().get_start_method()
        print(f"\n{sys.platform}: platform default {platform_default!r}, worker {handle._context!r}")
        assert handle._context.get_start_method() == "spawn", (
            f"on {sys.platform} the session worker context starts children with "
            f"{handle._context.get_start_method()!r}, so the child would inherit parent state"
        )
        assert handle._context.Process is mp.get_context("spawn").Process
        assert "spawn" in mp.get_all_start_methods()
    finally:
        handle.stop()


def test_a_command_for_another_session_is_refused_and_never_executed(command_loop: _LoopHarness):
    """A worker owns exactly one session and will not run another one's command."""
    before = command_loop.state()

    foreign = WorkerCommand.now("observe", "some-other-session", timeout_s=COMMAND_TIMEOUT_S, duration_s=1.0)
    refused = command_loop.request(foreign)
    print(f"\nforeign command refused: {refused.detail}")
    assert refused.ok is False
    assert refused.stale is False
    assert command_loop.config.session_id in (refused.detail or "")

    after = command_loop.state()
    assert after.revision == before.revision, "a command for another session advanced this one"
    assert after.payload["session_time_s"] == before.payload["session_time_s"]


def test_a_stale_expected_revision_is_answered_stale_and_never_executed(command_loop: _LoopHarness):
    """A result for an outdated state must never overwrite a newer invalidation."""
    before = command_loop.state()

    stale = command_loop.request(
        WorkerCommand.now(
            "observe",
            command_loop.config.session_id,
            expected_revision=before.revision - 1,
            timeout_s=COMMAND_TIMEOUT_S,
            duration_s=1.0,
        )
    )
    print(f"stale command refused: {stale.detail}")
    assert stale.stale is True
    assert stale.ok is False
    assert stale.revision == before.revision

    after = command_loop.state()
    assert after.revision == before.revision, "a stale command was executed anyway"
    assert after.payload["session_time_s"] == before.payload["session_time_s"]


def test_an_already_expired_deadline_is_refused_before_execution(command_loop: _LoopHarness):
    """A result nobody can still use is not worth occupying the single-owner loop."""
    before = command_loop.state()

    expired = WorkerCommand(
        kind="observe",
        session_id=command_loop.config.session_id,
        expected_revision=ANY_REVISION,
        deadline_monotonic_s=max(1e-9, time.monotonic() - 1.0),
        payload={"duration_s": 1.0},
    )
    assert expired.expired is True, "the drill did not actually build an expired command"

    refused = command_loop.request(expired)
    print(f"expired command refused: {refused.detail}")
    assert refused.ok is False
    assert "deadline expired" in (refused.detail or "")

    after = command_loop.state()
    assert after.revision == before.revision, "an expired command was executed anyway"
    assert after.payload["session_time_s"] == before.payload["session_time_s"]


def test_a_malformed_command_is_discarded_and_the_next_one_is_still_served(command_loop: _LoopHarness):
    """A junk message must not wedge the owner or be answered as if it were work."""
    command_loop.send("this is not a WorkerCommand")

    good = WorkerCommand.now("tick", command_loop.config.session_id, timeout_s=COMMAND_TIMEOUT_S)
    served = command_loop.request(good)
    assert served.ok is True
    assert served.command_id == good.command_id
    assert command_loop.results.empty(), "the malformed command produced a result of its own"


def test_a_malformed_result_is_reported_unavailable_rather_than_returned():
    """Something that is not a `WorkerResult` never reaches the caller as one."""
    handle = SessionWorkerHandle(_config("ops-process-bad-result"), queue_size=4)
    handle._process = _AlwaysAlive()
    try:
        handle._results.put({"session_id": "ops-process-bad-result", "ok": True})
        with pytest.raises(WorkerUnavailable) as refusal:
            handle.receive(timeout_s=30.0)
        print(f"\nmalformed result refused: {refusal.value}")
        assert "malformed" in str(refusal.value)
        assert "dict" in str(refusal.value), "the refusal does not name the type that arrived"
    finally:
        _release(handle)


def test_a_result_for_another_session_is_never_accepted_as_this_ones():
    """Correlation is by session as well as by command; a cross-talking result is refused."""
    handle = SessionWorkerHandle(_config("ops-process-cross-talk"), queue_size=4)
    handle._process = _AlwaysAlive()
    try:
        command = WorkerCommand.now("tick", handle.config.session_id, timeout_s=COMMAND_TIMEOUT_S)
        handle._results.put(
            WorkerResult(
                command_id=command.command_id,
                session_id="a-different-session",
                revision=7,
                ok=True,
                payload={"session_time_s": 99.0},
            )
        )
        with pytest.raises(WorkerUnavailable) as refusal:
            handle.request(command, timeout_s=30.0)
        print(f"\ncross-session result refused: {refusal.value}")
        assert "a-different-session" in str(refusal.value)
        assert handle.config.session_id in str(refusal.value)
    finally:
        _release(handle)


def test_a_full_command_queue_refuses_rather_than_buffering():
    """Back-pressure is a refusal. An unbounded queue would hide a stalled owner."""
    handle = SessionWorkerHandle(_config("ops-process-busy"), queue_size=1)
    handle._process = _AlwaysAlive()
    try:
        handle.send(WorkerCommand.now("tick", handle.config.session_id, timeout_s=COMMAND_TIMEOUT_S))
        with pytest.raises(WorkerBusy) as busy:
            for _ in range(8):
                handle.send(WorkerCommand.now("tick", handle.config.session_id, timeout_s=COMMAND_TIMEOUT_S))
        print(f"\nbounded queue refused: {busy.value}")
        assert "back off" in str(busy.value)
    finally:
        _release(handle)

    runtime = ProcessSessionRuntime(
        _config("ops-process-busy-proxy"), queue_size=1, command_timeout_s=CRASH_TIMEOUT_S
    )
    proxied = runtime._handle
    proxied._process = _AlwaysAlive()
    try:
        proxied._commands.put(
            WorkerCommand.now("tick", proxied.config.session_id, timeout_s=COMMAND_TIMEOUT_S), False
        )
        started = time.monotonic()
        with pytest.raises(RuntimeUnavailable) as unavailable:
            runtime.advance(1.0)
        elapsed_s = time.monotonic() - started
        print(f"proxy surfaced back-pressure in {elapsed_s:.3f} s: {unavailable.value.detail}")
        assert unavailable.value.session_id == proxied.config.session_id
        assert "full" in unavailable.value.detail
        assert "back off" in unavailable.value.detail
        assert elapsed_s < CRASH_DETECTION_BUDGET_S, "a full queue was waited out rather than refused"
    finally:
        _release(proxied)


def test_the_complete_runtime_tick_survives_the_process_boundary(spawned_session: dict[str, Any]):
    """Every field the console reads crosses in full, nested members included.

    A flat summary would leave `/sessions/{id}/snapshot` without an estimate,
    rule context, planning result or recommendation under the production
    backend, which is the difference between a working console and a blank one.
    """
    runtime: ProcessSessionRuntime = spawned_session["runtime"]
    initial: RuntimeTick = spawned_session["initial"]

    assert initial.revision == 1, (
        "initialise returned the parent's empty placeholder rather than a tick built from the "
        f"child's own current_tick(); revision was {initial.revision}"
    )
    assert runtime.current_tick() is not None

    tick: RuntimeTick = spawned_session["tick"]
    print(
        f"\nspawned child reached an actionable instruction after {spawned_session['observes']} "
        f"observe(s) in {spawned_session['elapsed_s']:.2f} s at t={tick.session_time_s:.2f}s"
    )
    assert actionable(tick), (
        f"the spawned session published no actionable advice within {MAX_OBSERVES} observes"
    )

    assert isinstance(tick.estimate, StateEstimate)
    assert isinstance(tick.rule_context, RuleContext)
    assert isinstance(tick.planning, PlanningResult)
    assert isinstance(tick.recommendation, Recommendation)

    assert tick.estimate.session_id == spawned_session["config"].session_id
    assert tick.estimate.quality.channels, "the nested per-channel quality was flattened away"
    assert all(channel.channel for channel in tick.estimate.quality.channels)
    print(
        f"estimate cutoff {tick.estimate.cutoff_s:.2f}s over "
        f"{len(tick.estimate.quality.channels)} channel(s), overall {tick.estimate.quality.overall.value}"
    )

    ceiling_w = tick.rule_context.applicable_limits.deployment_ceiling_w
    assert isinstance(ceiling_w, float), "the resolved deployment ceiling did not survive the boundary"
    assert ceiling_w > 0.0
    assert tick.rule_context.ruleset_hash.startswith("sha256:")
    print(f"rule context ceiling {ceiling_w:.0f} W, {len(tick.rule_context.coverage)} coverage entr(ies)")

    assert tick.planning.status.value == "ok"
    assert tick.planning.duration_ms >= 0.0
    assert tick.recommendation.constraint_result.status is CheckStatus.PASS
    assert tick.recommendation.id
    print(
        f"advice {tick.recommendation.action_code.value} checked "
        f"{tick.recommendation.constraint_result.status.value} by "
        f"{tick.planning.status.value} planning in {tick.planning.duration_ms:.2f} ms"
    )

    assert runtime.current_tick().revision == tick.revision
    assert runtime.session_time_s == pytest.approx(tick.session_time_s, abs=1e-9)


def test_no_simulator_truth_crosses_the_process_boundary_in_a_tick(spawned_session: dict[str, Any]):
    """The child owns the `WorldState`; nothing about it may leave the child."""
    runtime: ProcessSessionRuntime = spawned_session["runtime"]

    payload = runtime._request("tick").payload
    assert set(payload) == set(TICK_PAYLOAD_KEYS), (
        f"the wire payload carries {sorted(set(payload) - TICK_PAYLOAD_KEYS)} beyond the allowed set "
        f"and is missing {sorted(TICK_PAYLOAD_KEYS - set(payload))}"
    )
    assert set(_tick_payload(spawned_session["tick"])) == set(TICK_PAYLOAD_KEYS)

    _assert_no_simulator_truth(payload)

    text = json.dumps(payload).lower()
    for forbidden in FORBIDDEN_TICK_WORDS:
        assert forbidden not in text, f"the tick payload mentions {forbidden!r}"
    print(f"\ntick payload: {len(text)} chars, keys {sorted(payload)}")


def _assert_no_simulator_truth(node: Any, path: str = "$") -> None:
    """Refuse any simulator-truth key, or any `WorldState`, anywhere in a payload."""
    assert not isinstance(node, WorldState), f"{path} carries a WorldState across the boundary"
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            assert "world" not in lowered, f"{path}.{key} names simulator truth"
            assert "truth" not in lowered, f"{path}.{key} names simulator truth"
            _assert_no_simulator_truth(value, f"{path}.{key}")
    elif isinstance(node, list | tuple):
        for index, value in enumerate(node):
            _assert_no_simulator_truth(value, f"{path}[{index}]")


def test_a_crashed_child_is_refused_promptly_rather_than_waited_out(dead_session: dict[str, Any]):
    """Crash detection, not deadline expiry: the answer arrives long before the timeout."""
    elapsed_s: float = dead_session["elapsed_s"]
    refusal: RuntimeUnavailable = dead_session["refusal"]
    print(
        f"\nterminated child pid {dead_session['pid']}; the next command was refused in "
        f"{elapsed_s:.3f} s against a {CRASH_TIMEOUT_S:.0f} s command timeout: {refusal.detail}"
    )
    assert refusal.session_id == dead_session["config"].session_id
    assert "not running" in refusal.detail
    assert elapsed_s < CRASH_DETECTION_BUDGET_S, (
        f"the crash took {elapsed_s:.1f} s to surface, which is a timeout expiring rather than a "
        "dead child being noticed"
    )


def test_decision_health_never_raises_when_the_child_is_dead(dead_session: dict[str, Any]):
    """Readiness must answer with a health document, not with an error body."""
    runtime: ProcessSessionRuntime = dead_session["runtime"]

    health = runtime.decision_health()
    print(f"\nhealth after the crash: {health}")
    assert isinstance(health, RuntimeHealth)
    assert health.lifecycle == "unavailable"
    assert health.obstructions, "a dead session owner reported no obstruction at all"
    assert health.can_decide is False
    assert health.persistence_state == CapabilityState.UNAVAILABLE.value

    again = runtime.decision_health()
    assert again.lifecycle == "unavailable", "the second probe of a dead child disagreed with the first"


def test_persistence_on_a_dead_child_is_unavailable_and_not_an_empty_spool(dead_session: dict[str, Any]):
    """An unknown spool depth is not a spool depth of zero."""
    runtime: ProcessSessionRuntime = dead_session["runtime"]

    status = runtime.persistence
    print(f"\npersistence after the crash: {status}")
    assert isinstance(status, RuntimePersistence)
    assert status.state is CapabilityState.UNAVAILABLE
    assert status.last_error, "the unreachable spool reported no reason"
    assert status.degraded is True
    assert status != RuntimePersistence(), (
        "a dead child reported the default healthy empty spool, which reads on /metrics as a store "
        "with nothing waiting rather than a store nobody can see"
    )


def test_the_registry_refuses_a_runtime_whose_process_has_exited(dead_session: dict[str, Any]):
    """A session whose owner died is unavailable, not silently re-served."""
    runtime: ProcessSessionRuntime = dead_session["runtime"]
    session_id: str = dead_session["config"].session_id

    registry = RuntimeRegistry()
    registry.attach(session_id, runtime)
    assert registry.has(session_id) is True
    assert registry.active_sessions == (session_id,)

    with pytest.raises(RuntimeUnavailable) as refusal:
        registry.get(session_id)
    print(f"\nregistry refusal: {refusal.value.detail}")
    assert refusal.value.session_id == session_id
    assert "exited" in refusal.value.detail


def test_stopping_a_process_runtime_joins_the_child_and_closes_both_queues():
    """A stopped session leaves no process and no open pipe, and stops twice safely."""
    config = _config("ops-process-stop")
    runtime = ProcessSessionRuntime(config, queue_size=8, command_timeout_s=COMMAND_TIMEOUT_S)
    runtime.initialise(_manifest_for(config), config.scenario_id, config.seed)
    handle = runtime._handle
    assert handle.alive is True
    pid = handle._process.pid
    assert isinstance(pid, int) and pid > 0

    runtime.stop()
    print(f"\nstopped child pid {pid}: alive={handle.alive}, closed={handle._closed}")
    assert runtime.stopped is True
    assert runtime.alive is False
    assert handle.alive is False
    assert handle._process is None, "the handle still holds a process reference after stop()"
    assert handle._closed is True, "stop() left the command and result queues open"

    runtime.stop()
    assert runtime.stopped is True
    assert handle.alive is False
    assert handle._closed is True


def test_pause_resume_step_and_stop_round_trip_through_the_process_proxy():
    """Lifecycle control really reaches the child and moves its revision and clock."""
    config = _config("ops-process-lifecycle")
    runtime = ProcessSessionRuntime(config, queue_size=8, command_timeout_s=COMMAND_TIMEOUT_S)
    try:
        runtime.initialise(_manifest_for(config), config.scenario_id, config.seed)
        opening_revision = runtime.revision
        assert runtime.session_time_s == pytest.approx(0.0)

        stepped = runtime.advance(1.0)
        assert stepped.revision > opening_revision
        assert runtime.revision == stepped.revision
        assert runtime.session_time_s == pytest.approx(1.0)

        runtime.pause()
        assert runtime.paused is True
        paused_revision = runtime.revision
        assert paused_revision > stepped.revision, "pause did not reach the child"

        runtime.advance(1.0)
        assert runtime.session_time_s == pytest.approx(1.0), "a paused session advanced its own clock"

        runtime.resume()
        assert runtime.paused is False
        assert runtime.revision > paused_revision, "resume did not reach the child"

        resumed = runtime.advance(1.0)
        assert resumed.session_time_s == pytest.approx(2.0)
        assert runtime.session_time_s == pytest.approx(2.0)
        print(
            f"\nlifecycle: revision {opening_revision} -> {runtime.revision}, "
            f"session clock {runtime.session_time_s:.2f}s"
        )
    finally:
        runtime.stop()

    assert runtime.stopped is True
    assert runtime.alive is False


def test_the_process_backend_serves_a_real_estimate_through_the_http_app(tmp_path: Path):
    """The production default, end to end: the console is not blank under `process`.

    No adapter is substituted. `Settings.session_runtime_backend` is left at
    what a deployment runs, so `POST /sessions` spawns a real child, `step`
    crosses the boundary twice, and the snapshot the browser reads is built
    from what the child actually estimated.
    """
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
        artifact_root=tmp_path,
        session_runtime_backend="process",
        session_queue_size=8,
        session_command_timeout_s=COMMAND_TIMEOUT_S,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        create_all(app.state.database.engine)
        assert isinstance(app.state.session_factory, ProcessSessionFactory), (
            "the application did not compose the production session backend"
        )

        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
                "label": "process backend drill",
            },
            headers={"Idempotency-Key": "process-backend-create", "X-Operator-Id": OPERATOR},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]
        runtime = app.state.runtimes.get(session_id)
        assert isinstance(runtime, ProcessSessionRuntime)
        assert runtime.alive is True, "POST /sessions returned before its child was running"
        print(f"\nspawned session {session_id} on the process backend")

        lease = client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": OPERATOR, "ttl_s": 600.0},
            headers={"Idempotency-Key": "process-backend-lease"},
        )
        assert lease.status_code == 200, lease.text

        step = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={
                "kind": "step",
                "expected_revision": 0,
                "operator_id": OPERATOR,
                "step_duration_s": 1.0,
            },
            headers={"Idempotency-Key": "process-backend-step"},
        )
        assert step.status_code == 200, step.text
        assert step.json()["accepted"] is True

        snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        body = snapshot.json()
        assert body["estimate"] is not None, (
            "the production backend served a snapshot with no estimate, so the console would be blank"
        )
        assert body["estimate"]["session_id"] == session_id
        assert body["estimate"]["quality"]["channels"], "the estimate arrived without its channel quality"
        assert body["rule_context"] is not None, "the snapshot carries no resolved rule context"
        assert body["session_time_s"] == pytest.approx(1.0)
        print(
            f"snapshot at t={body['session_time_s']:.2f}s with "
            f"{len(body['estimate']['quality']['channels'])} channel(s) of quality"
        )

        text = json.dumps(body).lower()
        for forbidden in ("worldstate", "world_state", "rng_state", "integrator_state"):
            assert forbidden not in text

        spooled = sorted((tmp_path / "artifacts" / "spool" / session_id).glob("*.json"))
        assert spooled == [], (
            "the spawned session could not reach the lifecycle store and spooled its own audit "
            f"trail instead: {[path.name for path in spooled]}"
        )

        stored = client.post(
            f"/api/v1/sessions/{session_id}/snapshots",
            json={"label": "process backend"},
            headers={"Idempotency-Key": "process-backend-snapshot"},
        )
        assert stored.status_code == 201, stored.text
        snapshot_hash = stored.json()["snapshot"]["snapshot_hash"]
        print(f"snapshot hash across the boundary: {snapshot_hash}")
        assert snapshot_hash.startswith("sha256:")


def test_a_snapshot_taken_across_the_boundary_restores_the_same_session_time():
    """Snapshot and restore both survive the process boundary.

    The snapshot is captured in the child, its hash and complete state cross
    back, the session is then driven forward, and restoring that state puts it
    back where the snapshot was taken. A proxy that returned a hash without a
    usable state, or accepted a restore it never applied, would pass a hash
    check and still lose the session.
    """
    config = _config("ops-process-restore")
    runtime = ProcessSessionRuntime(config, queue_size=8, command_timeout_s=COMMAND_TIMEOUT_S)
    runtime.initialise(_manifest_for(config), config.scenario_id, config.seed)
    try:
        runtime.advance(1.0)
        digest, state = runtime.snapshot("restore drill")
        assert digest.startswith("sha256:")
        assert state["session_time_s"] == pytest.approx(runtime.session_time_s)
        captured_at_s = runtime.session_time_s

        moved = runtime.advance(1.0)
        assert moved.session_time_s > captured_at_s, "the session did not move before the restore"

        restored = runtime.restore(state)
        assert restored.session_time_s == pytest.approx(captured_at_s)
        assert runtime.session_time_s == pytest.approx(captured_at_s)

        again, regained = runtime.snapshot("restore drill again")
        assert again == digest, "restoring produced a different state from the one captured"
        assert regained["session_time_s"] == pytest.approx(captured_at_s)
        print(f"\nrestored to t={captured_at_s:.2f}s from {digest[:23]} across the boundary")
    finally:
        runtime.stop()
