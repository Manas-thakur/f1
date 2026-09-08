"""Session-runtime worker process.

Protocol (``backend/PERSISTENCE_AND_WORKERS.md``, "Worker protocol"): the
worker accepts ``Initialise``, ``Observe``, ``Plan``, ``ApplySimulatorInput``,
``Pause``, ``Snapshot`` and ``Stop`` over a **bounded** typed queue. Every
command carries the session id, the revision it was issued against and an
**absolute monotonic deadline**.

Two refusals are the point of the protocol and are implemented before any work
happens:

* a command whose ``expected_revision`` no longer matches the runtime's is
  answered ``stale=True`` and executed *not at all*, so a completed result for an
  outdated state cannot overwrite a newer invalidation;
* a command whose absolute deadline has already passed is refused rather than
  started, because a result that arrives after its deadline is not useful and
  starting it would occupy the single-owner loop.

``multiprocessing`` uses the ``spawn`` start method explicitly: the child must
not inherit the parent's loaded artefacts or its RNG state.

The loop itself (:func:`run_command_loop`) is a plain function over two queue
objects, so it can be driven in-process with ``queue.Queue`` in a test and in a
separate process with ``multiprocessing.Queue`` in production. Only the
transport differs.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as mp
import queue as queue_module
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

logger = logging.getLogger("afterlap.workers.session")

CommandKind = Literal[
    "initialise",
    "observe",
    "plan",
    "apply_simulator_input",
    "pause",
    "resume",
    "snapshot",
    "stop",
]

COMMAND_KINDS: tuple[str, ...] = (
    "initialise",
    "observe",
    "plan",
    "apply_simulator_input",
    "pause",
    "resume",
    "snapshot",
    "stop",
)

ANY_REVISION = -1
"""``expected_revision`` value meaning 'do not check' — used only by Initialise."""

DEFAULT_QUEUE_SIZE = 32
DEFAULT_COMMAND_TIMEOUT_S = 30.0


class WorkerBusy(RuntimeError):
    """The bounded command queue is full; the caller must back off, not buffer."""


class WorkerUnavailable(RuntimeError):
    """The worker process is not running, or did not answer in time."""


@dataclass(frozen=True, slots=True)
class WorkerCommand:
    """One typed request to the session worker."""

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
    """Everything the child needs to build the runtime for itself."""

    session_id: str
    scenario_id: str
    ruleset_id: str
    seed: int
    label: str | None = None
    decision_interval_s: float | None = None


class _Queue(Protocol):
    def put(self, item: Any, block: bool = ..., timeout: float | None = ...) -> None: ...

    def get(self, block: bool = ..., timeout: float | None = ...) -> Any: ...


def run_command_loop(commands: _Queue, results: _Queue, config: WorkerConfig) -> None:
    """Serve commands until ``stop``. One owner, one session, no concurrency."""
    runtime: Any = None
    while True:
        try:
            command = commands.get(True, 1.0)
        except queue_module.Empty:
            continue
        if command is None:
            return
        result, runtime, finished = _execute(command, runtime, config)
        results.put(result)
        if finished:
            return


def _execute(command: WorkerCommand, runtime: Any, config: WorkerConfig) -> tuple[WorkerResult, Any, bool]:
    revision = 0 if runtime is None else runtime.revision

    if command.session_id != config.session_id:
        return (
            _fail(command, revision, f"this worker owns session {config.session_id!r}"),
            runtime,
            False,
        )
    if command.expired:
        return (
            _fail(command, revision, "absolute monotonic deadline expired before execution"),
            runtime,
            False,
        )
    if command.kind != "initialise" and runtime is None:
        return _fail(command, revision, "the session has not been initialised"), runtime, False
    if (
        command.expected_revision != ANY_REVISION
        and runtime is not None
        and command.expected_revision != revision
    ):
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
    from afterlap_contracts import DeploymentProfile

    if command.kind == "initialise":
        runtime = _build_runtime(config)
        return _ok(command, runtime, {"session_time_s": runtime.session_time_s}), runtime, False

    if command.kind == "observe":
        tick = runtime.advance(float(command.payload.get("duration_s", 1.0)))
        return _ok(command, runtime, _tick_payload(tick)), runtime, False

    if command.kind == "plan":
        tick = runtime.decide_now()
        return _ok(command, runtime, _tick_payload(tick)), runtime, False

    if command.kind == "apply_simulator_input":
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

    runtime.stop()
    return _ok(command, runtime, {"stopped": True}), runtime, True


def _build_runtime(config: WorkerConfig) -> Any:
    from afterlap_api.session.factory import SessionFactory
    from afterlap_contracts import SessionMode
    from afterlap_contracts.requests import CreateSessionRequest

    factory = SessionFactory()
    _, runtime = factory.create(
        CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id=config.scenario_id,
            ruleset_id=config.ruleset_id,
            seed=config.seed,
            label=config.label,
        )
    )
    return runtime


def _tick_payload(tick: Any) -> dict[str, Any]:
    """JSON-shaped summary. No ``WorldState`` and no contract object crosses the queue."""
    recommendation = tick.recommendation
    return {
        "session_time_s": tick.session_time_s,
        "revision": tick.revision,
        "has_estimate": tick.estimate is not None,
        "estimate_cutoff_s": None if tick.estimate is None else tick.estimate.cutoff_s,
        "planning_status": None if tick.planning is None else tick.planning.status.value,
        "recommendation_id": None if recommendation is None else recommendation.id,
        "action_code": None if recommendation is None else recommendation.action_code.value,
        "constraint_status": (
            None if recommendation is None else recommendation.constraint_result.status.value
        ),
        "execution_ids": [event.id for event in tick.executions],
        "finished": tick.finished,
    }


def _ok(command: WorkerCommand, runtime: Any, payload: dict[str, Any]) -> WorkerResult:
    return WorkerResult(
        command_id=command.command_id,
        session_id=command.session_id,
        revision=runtime.revision,
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


def worker_main(commands: Any, results: Any, config: WorkerConfig) -> None:  # pragma: no cover
    """Child entry point. Importable at module level so ``spawn`` can find it."""
    logging.basicConfig(level=logging.WARNING)
    run_command_loop(commands, results, config)


class SessionWorkerHandle:
    """Parent-side handle to one spawned session worker."""

    def __init__(self, config: WorkerConfig, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        if queue_size < 1:
            raise ValueError("the command queue must be bounded to at least one command")
        self.config = config
        self._context = mp.get_context("spawn")
        self._commands: Any = self._context.Queue(maxsize=queue_size)
        self._results: Any = self._context.Queue(maxsize=queue_size)
        self._process: Any = None

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
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

    def send(self, command: WorkerCommand) -> None:
        """Enqueue one command. Refuses rather than growing the bounded queue."""
        if not self.alive:
            raise WorkerUnavailable("the session worker process is not running")
        try:
            self._commands.put(command, False)
        except queue_module.Full as exc:
            raise WorkerBusy(
                "the session worker command queue is full; back off rather than buffering commands"
            ) from exc

    def receive(self, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S) -> WorkerResult:
        try:
            return cast(WorkerResult, self._results.get(True, timeout_s))
        except queue_module.Empty as exc:
            raise WorkerUnavailable(f"no result within {timeout_s} s") from exc

    def request(
        self, command: WorkerCommand, *, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S
    ) -> WorkerResult:
        self.send(command)
        result = self.receive(timeout_s)
        while result.command_id != command.command_id:
            result = self.receive(timeout_s)
        return result

    def stop(self, *, timeout_s: float = 10.0) -> None:
        if self._process is None:
            return
        if self._process.is_alive():
            with contextlib.suppress(queue_module.Full):
                self._commands.put(None, False)
            self._process.join(timeout_s)
        if self._process.is_alive():  # pragma: no cover - the child ignored the sentinel
            self._process.terminate()
            self._process.join(timeout_s)
        self._process = None

    def kill(self) -> None:
        """Terminate the child without a clean stop, to exercise crash recovery."""
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(5.0)
        self._process = None


__all__ = [
    "ANY_REVISION",
    "COMMAND_KINDS",
    "DEFAULT_COMMAND_TIMEOUT_S",
    "DEFAULT_QUEUE_SIZE",
    "SessionWorkerHandle",
    "WorkerBusy",
    "WorkerCommand",
    "WorkerConfig",
    "WorkerResult",
    "WorkerUnavailable",
    "run_command_loop",
    "worker_main",
]
