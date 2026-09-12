"""Spawn-based bounded process transport for one session runtime.

The control plane must never run physics, estimation, planning or a solver on
its event loop, so a session's owner lives in its own process. The transport
below is what makes that safe rather than merely separate.

Every command carries the session id it was issued for, the revision it was
issued against and an **absolute monotonic deadline**. Three refusals happen
before any work starts, because each of them is cheaper to answer than to
execute and wrong to execute at all:

* a command for another session is refused rather than run against this one;
* a command whose ``expected_revision`` no longer matches is answered
  ``stale=True`` and executed *not at all*, so a completed result for an
  outdated state cannot overwrite a newer invalidation;
* a command whose deadline has already passed is refused rather than started,
  because its result is no longer useful and starting it would occupy the
  single-owner loop.

``multiprocessing.get_context("spawn")`` is explicit on every platform. The
child must not inherit the parent's loaded artefacts, open database handles or
RNG state, and spawn is the only start method that holds on Windows, Linux and
macOS alike.

The loop itself (:func:`run_command_loop`) is a plain function over two queue
objects, so a test can drive it in-process with ``queue.Queue`` and production
drives it across ``multiprocessing.Queue``. Only the transport differs.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import multiprocessing as mp
import queue as queue_module
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from afterlap_contracts import (
    CapabilityState,
    DeploymentProfile,
    ExecutionEvent,
    PlanningResult,
    Recommendation,
    RuleContext,
    SessionManifest,
    StateEstimate,
)

from .runtime import RuntimeHealth, RuntimePersistence, RuntimeTick, RuntimeUnavailable

logger = logging.getLogger("afterlap.application.session_process")

CommandKind = Literal[
    "initialise",
    "tick",
    "observe",
    "plan",
    "apply_simulator_input",
    "mark_communicated",
    "pause",
    "resume",
    "snapshot",
    "restore",
    "health",
    "persistence",
    "stop",
]

COMMAND_KINDS: tuple[str, ...] = (
    "initialise",
    "tick",
    "observe",
    "plan",
    "apply_simulator_input",
    "mark_communicated",
    "pause",
    "resume",
    "snapshot",
    "restore",
    "health",
    "persistence",
    "stop",
)

ANY_REVISION = -1
"""``expected_revision`` value meaning 'do not check'."""

DEFAULT_QUEUE_SIZE = 32
DEFAULT_COMMAND_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.1
EXIT_GRACE_S = 1.0
RESULT_PUT_TIMEOUT_S = 30.0
UNREACHABLE_LIFECYCLE = "unavailable"


class WorkerBusy(RuntimeError):
    """The bounded command queue is full; the caller must back off, not buffer."""


class WorkerUnavailable(RuntimeError):
    """The worker is absent, crashed, answered for the wrong command, or missed a deadline."""


@dataclass(frozen=True, slots=True)
class WorkerCommand:
    """One typed request carried across the local process boundary."""

    kind: CommandKind
    session_id: str
    expected_revision: int = ANY_REVISION
    deadline_monotonic_s: float = 0.0
    command_id: str = field(default_factory=lambda: f"cmd-{uuid.uuid4().hex[:12]}")
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in COMMAND_KINDS:
            raise ValueError(f"unknown session worker command {self.kind!r}; expected one of {COMMAND_KINDS}")

    @classmethod
    def now(
        cls,
        kind: CommandKind,
        session_id: str,
        *,
        expected_revision: int = ANY_REVISION,
        timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
        **payload: Any,
    ) -> WorkerCommand:
        """Build a command with an absolute monotonic deadline ``timeout_s`` away."""
        return cls(
            kind=kind,
            session_id=session_id,
            expected_revision=expected_revision,
            deadline_monotonic_s=time.monotonic() + timeout_s,
            payload=payload,
        )

    @property
    def expired(self) -> bool:
        return self.deadline_monotonic_s > 0.0 and time.monotonic() > self.deadline_monotonic_s


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """Correlated response. ``stale`` marks a result the caller must discard."""

    command_id: str
    session_id: str
    revision: int
    ok: bool
    stale: bool = False
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Serializable inputs required to construct one session owner.

    ``runtime_builder`` is a ``"module:function"`` reference the child imports
    to build its own runtime. It has no default: the application layer
    describes *that* a session owner is built out of process, and the
    composition root names *which* adapter builds it. A default here would
    invert the dependency and make this package import the HTTP app.

    ``database_url`` and ``artifact_root`` are what make an out-of-process
    session auditable. Without them the child records nothing, so everything it
    decided dies with the process.
    """

    session_id: str
    scenario_id: str
    ruleset_id: str
    seed: int
    runtime_builder: str
    label: str | None = None
    decision_interval_s: float | None = None
    database_url: str | None = None
    artifact_root: str | None = None
    request_payload: dict[str, Any] | None = None
    manifest_payload: dict[str, Any] | None = None
    manifest_hash: str | None = None


@dataclass(frozen=True, slots=True)
class QueuedInput:
    """A driver input accepted now and applied after the reaction delay."""

    id: str
    apply_at_s: float
    delay_s: float


class _Queue(Protocol):
    def put(self, item: Any, block: bool = ..., timeout: float | None = ...) -> None: ...

    def get(self, block: bool = ..., timeout: float | None = ...) -> Any: ...


def run_command_loop(commands: _Queue, results: _Queue, config: WorkerConfig) -> None:
    """Serve commands serially until a stop request or process termination."""
    runtime: Any = None
    while True:
        try:
            command = commands.get(True, 1.0)
        except queue_module.Empty:
            continue
        if command is None:
            return
        if not isinstance(command, WorkerCommand):
            logger.error(
                "session worker %s discarded a malformed command of type %s",
                config.session_id,
                type(command).__name__,
            )
            continue
        result, runtime, finished = _execute(command, runtime, config)
        try:
            results.put(result, block=True, timeout=RESULT_PUT_TIMEOUT_S)
        except queue_module.Full:
            logger.exception(
                "session worker %s dropped the result for %s: the result queue stayed full for %.0f s",
                config.session_id,
                command.command_id,
                RESULT_PUT_TIMEOUT_S,
            )
        if finished:
            return


def _execute(command: WorkerCommand, runtime: Any, config: WorkerConfig) -> tuple[WorkerResult, Any, bool]:
    revision = 0 if runtime is None else int(runtime.revision)
    if command.session_id != config.session_id:
        return _fail(command, revision, f"this worker owns session {config.session_id!r}"), runtime, False
    if command.expired:
        return (
            _fail(command, revision, "absolute monotonic deadline expired before execution"),
            runtime,
            False,
        )
    if command.kind != "initialise" and runtime is None:
        return _fail(command, revision, "the session has not been initialised"), runtime, False
    if command.expected_revision not in (ANY_REVISION, revision):
        return (
            WorkerResult(
                command_id=command.command_id,
                session_id=command.session_id,
                revision=revision,
                ok=False,
                stale=True,
                detail=(
                    f"command was issued against revision {command.expected_revision}; "
                    f"the session is at {revision}, so the result is discarded"
                ),
            ),
            runtime,
            False,
        )
    try:
        return _dispatch(command, runtime, config)
    except Exception as exc:
        logger.exception("session worker command %s failed", command.kind)
        return _fail(command, revision, f"{type(exc).__name__}: {exc}"), runtime, False


def _dispatch(command: WorkerCommand, runtime: Any, config: WorkerConfig) -> tuple[WorkerResult, Any, bool]:
    if command.kind == "initialise":
        if runtime is not None:
            return _fail(command, int(runtime.revision), "the session is already initialised"), runtime, False
        runtime = _resolve_builder(config.runtime_builder)(config)
        return _ok(command, runtime, _tick_payload(runtime.current_tick())), runtime, False
    if command.kind == "tick":
        return _ok(command, runtime, _tick_payload(runtime.current_tick())), runtime, False
    if command.kind == "observe":
        tick = runtime.advance(float(command.payload.get("duration_s", 1.0)))
        return _ok(command, runtime, _tick_payload(tick)), runtime, False
    if command.kind == "plan":
        tick = runtime.decide_now()
        return _ok(command, runtime, _tick_payload(tick)), runtime, False
    if command.kind == "apply_simulator_input":
        if "observed_at_s" not in command.payload:
            queued = runtime.queue_driver_input(
                DeploymentProfile(command.payload["profile_id"]),
                recommendation_id=command.payload.get("recommendation_id"),
            )
            return (
                _ok(
                    command,
                    runtime,
                    {
                        "queued_input_id": queued.id,
                        "apply_at_s": queued.apply_at_s,
                        "reaction_delay_s": queued.delay_s,
                    },
                ),
                runtime,
                False,
            )
        execution = runtime.apply_driver_action(
            DeploymentProfile(command.payload["profile_id"]),
            float(command.payload["observed_at_s"]),
            command.payload.get("recommendation_id"),
        )
        return _ok(command, runtime, {"execution": execution.model_dump(mode="json")}), runtime, False
    if command.kind == "mark_communicated":
        moment = runtime.mark_communicated(
            str(command.payload["recommendation_id"]), command.payload.get("at_s")
        )
        return _ok(command, runtime, {"communicated_at_s": moment}), runtime, False
    if command.kind == "pause":
        runtime.pause()
        return _ok(command, runtime, {"paused": True}), runtime, False
    if command.kind == "resume":
        runtime.resume()
        return _ok(command, runtime, {"paused": False}), runtime, False
    if command.kind == "snapshot":
        digest, payload = runtime.snapshot(command.payload.get("label"))
        include = bool(command.payload.get("include_payload", False))
        return (
            _ok(
                command,
                runtime,
                {
                    "snapshot_hash": digest,
                    "session_time_s": payload["session_time_s"],
                    "payload": payload if include else None,
                },
            ),
            runtime,
            False,
        )
    if command.kind == "restore":
        tick = runtime.restore(dict(command.payload["snapshot"]))
        return _ok(command, runtime, _tick_payload(tick)), runtime, False
    if command.kind == "health":
        return _ok(command, runtime, _health_payload(runtime)), runtime, False
    if command.kind == "persistence":
        return _ok(command, runtime, _persistence_payload(runtime)), runtime, False
    runtime.stop()
    return _ok(command, runtime, {"stopped": True}), runtime, True


def _resolve_builder(reference: str) -> Any:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("runtime_builder must use the form 'module:function'")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def _tick_payload(tick: Any) -> dict[str, Any]:
    """The complete observable tick, plus the flat summary the drills read.

    Every field the control plane and the browser read is carried in full:
    a summary alone would leave ``/sessions/{id}`` without an estimate, rule
    context, planning result, recommendation or execution list under the
    process backend, which is the difference between a working console and a
    blank one. No ``WorldState`` and no simulator truth appears here.
    """
    return {
        "session_time_s": tick.session_time_s,
        "revision": tick.revision,
        "estimate": None if tick.estimate is None else tick.estimate.model_dump(mode="json"),
        "rule_context": None if tick.rule_context is None else tick.rule_context.model_dump(mode="json"),
        "planning": None if tick.planning is None else tick.planning.model_dump(mode="json"),
        "recommendation": (
            None if tick.recommendation is None else tick.recommendation.model_dump(mode="json")
        ),
        "executions": [event.model_dump(mode="json") for event in tick.executions],
        "finished": tick.finished,
        "has_estimate": tick.estimate is not None,
        "estimate_cutoff_s": None if tick.estimate is None else tick.estimate.cutoff_s,
        "planning_status": None if tick.planning is None else tick.planning.status.value,
        "recommendation_id": None if tick.recommendation is None else tick.recommendation.id,
        "action_code": None if tick.recommendation is None else tick.recommendation.action_code.value,
        "constraint_status": (
            None if tick.recommendation is None else tick.recommendation.constraint_result.status.value
        ),
        "execution_ids": [event.id for event in tick.executions],
    }


def _health_payload(runtime: Any) -> dict[str, Any]:
    probe = getattr(runtime, "decision_health", None)
    if probe is None:
        return {"lifecycle": "running", "obstructions": []}
    health = probe()
    return {
        "lifecycle": health.lifecycle,
        "observation_age_s": health.observation_age_s,
        "withdrawing_advice": bool(health.withdrawing_advice),
        "halted": bool(health.halted),
        "persistence_state": health.persistence_state,
        "obstructions": list(health.obstructions),
    }


def _persistence_payload(runtime: Any) -> dict[str, Any]:
    status = getattr(runtime, "persistence", None)
    if status is None:
        return {}
    return {
        "state": status.state.value,
        "spooled": int(status.spooled),
        "capacity": int(status.capacity),
        "last_error": status.last_error,
        "exhausted": bool(status.exhausted),
        "warnings": list(status.warnings),
    }


def _ok(command: WorkerCommand, runtime: Any, payload: dict[str, Any]) -> WorkerResult:
    return WorkerResult(
        command_id=command.command_id,
        session_id=command.session_id,
        revision=int(runtime.revision),
        ok=True,
        payload=payload,
    )


def _fail(command: WorkerCommand, revision: int, detail: str) -> WorkerResult:
    return WorkerResult(
        command_id=command.command_id,
        session_id=command.session_id,
        revision=revision,
        ok=False,
        detail=detail,
    )


def worker_main(commands: Any, results: Any, config: WorkerConfig) -> None:
    """Importable child-process entry point for spawn semantics."""
    logging.basicConfig(level=logging.WARNING)
    run_command_loop(commands, results, config)


class SessionWorkerHandle:
    """Parent-side lifecycle and correlation for one spawned owner."""

    def __init__(self, config: WorkerConfig, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        if queue_size < 1:
            raise ValueError("the command queue must be bounded to at least one command")
        self.config = config
        self._context = mp.get_context("spawn")
        self._commands: Any = self._context.Queue(maxsize=queue_size)
        self._results: Any = self._context.Queue(maxsize=queue_size)
        self._process: Any = None
        self._closed = False
        self._request_lock = threading.Lock()

    def start(self) -> None:
        if self.alive:
            return
        if self._closed:
            raise WorkerUnavailable("this session worker handle was already shut down")
        self._process = self._context.Process(
            target=worker_main,
            args=(self._commands, self._results, self.config),
            name=f"afterlap-session-{self.config.session_id}",
            daemon=True,
        )
        self._process.start()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    @property
    def exitcode(self) -> int | None:
        return None if self._process is None else self._process.exitcode

    @property
    def records_durably(self) -> bool:
        """Whether this worker's session writes a durable audit trail."""
        return self.config.database_url is not None

    def send(self, command: WorkerCommand) -> None:
        """Enqueue one command. Refuses rather than growing the bounded queue."""
        if not self.alive:
            raise WorkerUnavailable(self.exit_detail)
        try:
            self._commands.put(command, block=False)
        except queue_module.Full as exc:
            raise WorkerBusy(
                "the session worker command queue is full; back off rather than buffering commands"
            ) from exc

    def receive(self, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S) -> WorkerResult:
        """Take the next result, noticing a crashed child instead of waiting it out."""
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise WorkerUnavailable(
                    self.exit_detail if not self.alive else f"no result within {timeout_s} s"
                )
            try:
                item = self._results.get(True, min(POLL_INTERVAL_S, remaining))
            except queue_module.Empty:
                if self.alive:
                    continue
                return self._final_result()
            return self._validated(item)

    def request(
        self, command: WorkerCommand, *, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S
    ) -> WorkerResult:
        """Send one command and return *its* result, never another command's."""
        with self._request_lock:
            self.send(command)
            deadline = time.monotonic() + timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise WorkerUnavailable(f"no correlated result within {timeout_s} s")
                result = self.receive(remaining)
                if result.session_id != self.config.session_id:
                    raise WorkerUnavailable(
                        f"the session worker answered for session {result.session_id!r}, "
                        f"but this worker owns {self.config.session_id!r}"
                    )
                if result.command_id == command.command_id:
                    return result
                logger.warning(
                    "session worker %s produced a result for %s while %s was outstanding; discarding it",
                    self.config.session_id,
                    result.command_id,
                    command.command_id,
                )

    def stop(self, *, timeout_s: float = 10.0) -> None:
        """Ask the child to finish, then join it, then close both queues."""
        process = self._process
        if process is not None:
            if process.is_alive():
                with contextlib.suppress(queue_module.Full):
                    self._commands.put(None, block=False)
                process.join(timeout_s)
            if process.is_alive():
                process.terminate()
                process.join(timeout_s)
            self._process = None
        self._close_queues()

    def kill(self) -> None:
        """Terminate the child without a clean stop, to exercise crash recovery."""
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(5.0)
        self._process = None

    def _final_result(self) -> WorkerResult:
        """One last look for a result the child flushed as it exited."""
        try:
            item = self._results.get(True, EXIT_GRACE_S)
        except queue_module.Empty as exc:
            raise WorkerUnavailable(self.exit_detail) from exc
        return self._validated(item)

    def _validated(self, item: Any) -> WorkerResult:
        if not isinstance(item, WorkerResult):
            raise WorkerUnavailable(
                f"the session worker returned a malformed result of type {type(item).__name__}"
            )
        return item

    def _close_queues(self) -> None:
        if self._closed:
            return
        self._closed = True
        for pipe in (self._commands, self._results):
            with contextlib.suppress(Exception):
                pipe.close()
            with contextlib.suppress(Exception):
                pipe.join_thread()

    @property
    def exit_detail(self) -> str:
        """Why the child cannot be reached, including its exit code when known."""
        suffix = "" if self.exitcode is None else f" with exit code {self.exitcode}"
        return f"the session worker process is not running{suffix}"


class ProcessSessionRuntime:
    """``SessionRuntimePort`` proxy backed by one spawned Python process.

    The production adapter. Physics, estimation, planning and solver work all
    happen in the child; this object only correlates commands with results and
    rehydrates the contract models a tick carries.
    """

    def __init__(
        self,
        config: WorkerConfig,
        *,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    ) -> None:
        self.config = config
        self._handle = SessionWorkerHandle(config, queue_size=queue_size)
        self._lock = threading.RLock()
        self._timeout_s = command_timeout_s
        self._revision = 0
        self._session_time_s = 0.0
        self._paused = False
        self._stopped = False
        self._last_tick = RuntimeTick(
            session_time_s=0.0,
            revision=0,
            estimate=None,
            rule_context=None,
            planning=None,
            recommendation=None,
        )

    @property
    def alive(self) -> bool:
        return self._handle.alive

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def session_time_s(self) -> float:
        return self._session_time_s

    def initialise(self, manifest: SessionManifest, scenario_id: str, seed: int) -> RuntimeTick:
        with self._lock:
            if manifest.id != self.config.session_id or scenario_id != self.config.scenario_id:
                raise RuntimeUnavailable(
                    manifest.id, "runtime configuration does not match the session manifest"
                )
            if seed != self.config.seed:
                raise RuntimeUnavailable(manifest.id, "runtime seed does not match the session manifest")
            self._handle.start()
            return self._tick(self._request("initialise", expected_revision=ANY_REVISION))

    def current_tick(self) -> RuntimeTick:
        with self._lock:
            return self._last_tick

    def advance(self, duration_s: float) -> RuntimeTick:
        with self._lock:
            if duration_s <= 0.0:
                raise ValueError("advance needs a positive duration")
            return self._tick(self._request("observe", duration_s=duration_s))

    def decide_now(self) -> RuntimeTick:
        with self._lock:
            return self._tick(self._request("plan"))

    def pause(self) -> None:
        with self._lock:
            self._request("pause")
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._request("resume")
            self._paused = False

    def queue_driver_input(
        self, profile_id: DeploymentProfile, *, recommendation_id: str | None = None
    ) -> QueuedInput:
        """Accept an input now; the child applies it after the reaction delay."""
        with self._lock:
            result = self._request(
                "apply_simulator_input",
                profile_id=profile_id.value,
                recommendation_id=recommendation_id,
            )
            return QueuedInput(
                id=str(result.payload["queued_input_id"]),
                apply_at_s=float(result.payload["apply_at_s"]),
                delay_s=float(result.payload["reaction_delay_s"]),
            )

    def apply_driver_action(
        self, profile_id: DeploymentProfile, observed_at_s: float, recommendation_id: str | None
    ) -> ExecutionEvent:
        with self._lock:
            result = self._request(
                "apply_simulator_input",
                profile_id=profile_id.value,
                observed_at_s=observed_at_s,
                recommendation_id=recommendation_id,
            )
            return ExecutionEvent.model_validate(result.payload["execution"])

    def mark_communicated(self, recommendation_id: str, at_s: float | None = None) -> float:
        with self._lock:
            result = self._request("mark_communicated", recommendation_id=recommendation_id, at_s=at_s)
            return float(result.payload["communicated_at_s"])

    def snapshot(self, label: str | None = None) -> tuple[str, dict[str, Any]]:
        with self._lock:
            result = self._request("snapshot", label=label, include_payload=True)
            payload = result.payload.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeUnavailable(self.config.session_id, "the runtime returned no snapshot payload")
            return str(result.payload["snapshot_hash"]), payload

    def restore(self, payload: dict[str, Any]) -> RuntimeTick:
        with self._lock:
            return self._tick(self._request("restore", snapshot=payload))

    def decision_health(self) -> RuntimeHealth:
        """A measured verdict, or an explicit unreachable one. Never raises.

        ``/health/ready`` must answer with a health document even when a
        session owner has died; an exception here would replace the readiness
        body with an error body and hide every other session's state.
        """
        if not self.alive:
            return RuntimeHealth(
                lifecycle=UNREACHABLE_LIFECYCLE,
                persistence_state=CapabilityState.UNAVAILABLE.value,
                obstructions=(self._handle.exit_detail,),
            )
        try:
            result = self._request("health", expected_revision=ANY_REVISION)
        except RuntimeUnavailable as exc:
            return RuntimeHealth(
                lifecycle=UNREACHABLE_LIFECYCLE,
                persistence_state=CapabilityState.UNAVAILABLE.value,
                obstructions=(exc.detail,),
            )
        payload = result.payload
        age = payload.get("observation_age_s")
        return RuntimeHealth(
            lifecycle=str(payload.get("lifecycle", "running")),
            observation_age_s=None if age is None else float(age),
            withdrawing_advice=bool(payload.get("withdrawing_advice", False)),
            halted=bool(payload.get("halted", False)),
            persistence_state=str(payload.get("persistence_state", CapabilityState.AVAILABLE.value)),
            obstructions=tuple(str(item) for item in payload.get("obstructions", ())),
        )

    @property
    def persistence(self) -> RuntimePersistence:
        """Spool depth and lifecycle-store health, measured in the child.

        Reported as unavailable rather than empty when the child cannot be
        reached: an unknown spool depth is not a spool depth of zero.
        """
        if not self.alive:
            return RuntimePersistence(
                state=CapabilityState.UNAVAILABLE,
                last_error=self._handle.exit_detail,
            )
        try:
            result = self._request("persistence", expected_revision=ANY_REVISION)
        except RuntimeUnavailable as exc:
            return RuntimePersistence(state=CapabilityState.UNAVAILABLE, last_error=exc.detail)
        payload = result.payload
        if not payload:
            return RuntimePersistence()
        return RuntimePersistence(
            state=CapabilityState(payload["state"]),
            spooled=int(payload["spooled"]),
            capacity=int(payload["capacity"]),
            last_error=payload.get("last_error"),
            exhausted=bool(payload.get("exhausted", False)),
            warnings=tuple(str(item) for item in payload.get("warnings", ())),
        )

    def stop(self) -> None:
        """Stop the session, join the child and close both queues. Idempotent."""
        with self._lock:
            if self.alive:
                with contextlib.suppress(RuntimeUnavailable):
                    self._request("stop", expected_revision=ANY_REVISION)
            self._handle.stop()
            self._stopped = True

    def _request(
        self,
        kind: CommandKind,
        *,
        expected_revision: int | None = None,
        **payload: Any,
    ) -> WorkerResult:
        with self._lock:
            expected = self._revision if expected_revision is None else expected_revision
            command = WorkerCommand.now(
                kind,
                self.config.session_id,
                expected_revision=expected,
                timeout_s=self._timeout_s,
                **payload,
            )
            try:
                result = self._handle.request(command, timeout_s=self._timeout_s)
            except (WorkerBusy, WorkerUnavailable) as exc:
                raise RuntimeUnavailable(self.config.session_id, str(exc)) from exc
            if result.stale:
                raise RuntimeUnavailable(self.config.session_id, result.detail or "stale runtime result")
            if not result.ok:
                raise RuntimeUnavailable(
                    self.config.session_id, result.detail or "session runtime command failed"
                )
            self._revision = result.revision
            if "session_time_s" in result.payload:
                self._session_time_s = float(result.payload["session_time_s"])
            return result

    def _tick(self, result: WorkerResult) -> RuntimeTick:
        payload = result.payload
        self._session_time_s = float(payload["session_time_s"])
        tick = RuntimeTick(
            session_time_s=self._session_time_s,
            revision=result.revision,
            estimate=_model(StateEstimate, payload.get("estimate")),
            rule_context=_model(RuleContext, payload.get("rule_context")),
            planning=_model(PlanningResult, payload.get("planning")),
            recommendation=_model(Recommendation, payload.get("recommendation")),
            executions=tuple(ExecutionEvent.model_validate(item) for item in payload.get("executions", ())),
            finished=bool(payload.get("finished", False)),
        )
        self._last_tick = tick
        return tick


def _model(model: Any, payload: Any) -> Any:
    return None if payload is None else model.model_validate(payload)


__all__ = [
    "ANY_REVISION",
    "COMMAND_KINDS",
    "DEFAULT_COMMAND_TIMEOUT_S",
    "DEFAULT_QUEUE_SIZE",
    "EXIT_GRACE_S",
    "POLL_INTERVAL_S",
    "ProcessSessionRuntime",
    "QueuedInput",
    "SessionWorkerHandle",
    "WorkerBusy",
    "WorkerCommand",
    "WorkerConfig",
    "WorkerResult",
    "WorkerUnavailable",
    "run_command_loop",
    "worker_main",
]
