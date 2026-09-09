"""Stable application boundary between control-plane and session execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """One correlated request to a session runtime."""

    command_id: str
    session_id: str
    kind: str
    expected_revision: int
    deadline_monotonic_s: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """One correlated response from a session runtime."""

    command_id: str
    session_id: str
    revision: int
    ok: bool
    stale: bool = False
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeTick:
    """Observable session state with simulator truth deliberately absent."""

    session_time_s: float
    revision: int
    estimate: StateEstimate | None
    rule_context: RuleContext | None
    planning: PlanningResult | None
    recommendation: Recommendation | None
    executions: tuple[ExecutionEvent, ...] = ()
    finished: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Whether a session owner could decide now, and why it could not.

    Mirrors the in-process ``DecisionHealth`` field for field so a proxy
    reports a measured verdict rather than a narrower one. ``lifecycle`` is
    ``"unavailable"`` only when the owner could not be reached at all, which
    is distinct from an owner that answered "paused".
    """

    lifecycle: str
    observation_age_s: float | None = None
    withdrawing_advice: bool = False
    halted: bool = False
    persistence_state: str = "available"
    obstructions: tuple[str, ...] = ()

    @property
    def idle(self) -> bool:
        return self.lifecycle != "running"

    @property
    def can_decide(self) -> bool:
        return not self.obstructions


@dataclass(frozen=True, slots=True)
class RuntimePersistence:
    """Measured health of one session's lifecycle store.

    Mirrors the in-process ``PersistenceStatus`` so ``/metrics`` reports real
    spool usage under either runtime backend instead of a silent zero.
    """

    state: CapabilityState = CapabilityState.AVAILABLE
    spooled: int = 0
    capacity: int = 0
    last_error: str | None = None
    exhausted: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        return self.state is not CapabilityState.AVAILABLE


@runtime_checkable
class SessionRuntimePort(Protocol):
    """Operations available to HTTP and worker composition roots."""

    def initialise(self, manifest: SessionManifest, scenario_id: str, seed: int) -> RuntimeTick: ...

    def current_tick(self) -> RuntimeTick: ...

    def advance(self, duration_s: float) -> RuntimeTick: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def apply_driver_action(
        self, profile_id: DeploymentProfile, observed_at_s: float, recommendation_id: str | None
    ) -> ExecutionEvent: ...

    def mark_communicated(self, recommendation_id: str, at_s: float | None = None) -> float: ...

    def snapshot(self, label: str | None = None) -> tuple[str, dict[str, Any]]: ...

    def restore(self, payload: dict[str, Any]) -> RuntimeTick: ...

    def stop(self) -> None: ...

    @property
    def revision(self) -> int: ...

    @property
    def session_time_s(self) -> float: ...


class RuntimeUnavailable(Exception):
    """Raised when a session owner cannot safely execute a command."""

    def __init__(self, session_id: str, detail: str) -> None:
        super().__init__(detail)
        self.session_id = session_id
        self.detail = detail


RuntimeFactory = Callable[[str], SessionRuntimePort]


class RuntimeRegistry:
    """Own the runtime attached to each active session."""

    def __init__(self, factory: RuntimeFactory | None = None) -> None:
        self._runtimes: dict[str, SessionRuntimePort] = {}
        self._factory = factory

    def attach(self, session_id: str, runtime: SessionRuntimePort) -> None:
        previous = self._runtimes.get(session_id)
        if previous is not None and previous is not runtime:
            previous.stop()
        self._runtimes[session_id] = runtime

    def get(self, session_id: str) -> SessionRuntimePort:
        runtime = self._runtimes.get(session_id)
        if runtime is not None:
            alive = getattr(runtime, "alive", True)
            if alive:
                return runtime
            raise RuntimeUnavailable(session_id, "the session runtime process exited unexpectedly")
        if self._factory is None:
            raise RuntimeUnavailable(
                session_id,
                "no session runtime is attached; start the session before requesting live state",
            )
        runtime = self._factory(session_id)
        self._runtimes[session_id] = runtime
        return runtime

    def has(self, session_id: str) -> bool:
        return session_id in self._runtimes

    def detach(self, session_id: str) -> None:
        runtime = self._runtimes.pop(session_id, None)
        if runtime is not None:
            runtime.stop()

    def stop_all(self) -> None:
        for session_id in tuple(self._runtimes):
            self.detach(session_id)

    @property
    def active_sessions(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtimes))


__all__ = [
    "RuntimeCommand",
    "RuntimeFactory",
    "RuntimeHealth",
    "RuntimePersistence",
    "RuntimeRegistry",
    "RuntimeResult",
    "RuntimeTick",
    "RuntimeUnavailable",
    "SessionRuntimePort",
]
