"""The boundary between the control plane and the session runtime.

FastAPI never runs physics or a solver. It sends a typed command to the process
that owns one session's dynamics and waits for a correlated result, so a slow
optimisation cannot block the event loop.

Every command carries the session id, the revision it was issued against and an
absolute deadline. A result whose revision no longer matches is discarded: a
completed solve for a superseded state must not overwrite a newer invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from afterlap_contracts import (
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
    """One request to the session runtime."""

    command_id: str
    session_id: str
    kind: str
    expected_revision: int
    deadline_monotonic_s: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """A correlated response. ``stale`` marks a result the caller must discard."""

    command_id: str
    session_id: str
    revision: int
    ok: bool
    stale: bool = False
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeTick:
    """The observable state of a session after advancing it."""

    session_time_s: float
    revision: int
    estimate: StateEstimate | None
    rule_context: RuleContext | None
    planning: PlanningResult | None
    recommendation: Recommendation | None
    executions: tuple[ExecutionEvent, ...] = ()
    finished: bool = False


@runtime_checkable
class SessionRuntimePort(Protocol):
    """What the control plane needs from a session runtime.

    Deliberately small. Anything that needs the complete ``WorldState`` stays
    behind this boundary: the API can never obtain simulator truth through it.
    """

    def initialise(self, manifest: SessionManifest, scenario_id: str, seed: int) -> RuntimeTick:
        """Create the session's dynamics and return its first observable state."""
        ...

    def advance(self, duration_s: float) -> RuntimeTick:
        """Integrate forward, re-estimate, replan and return the new state."""
        ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def apply_driver_action(
        self, profile_id: DeploymentProfile, observed_at_s: float, recommendation_id: str | None
    ) -> ExecutionEvent:
        """Simulator-only deliberate driver input.

        The caller has already checked the session mode; this method assumes
        that check happened and does not repeat it.
        """
        ...

    def snapshot(self, label: str | None = None) -> tuple[str, dict[str, Any]]:
        """Capture complete state, returning ``(hash, payload)``."""
        ...

    def restore(self, payload: dict[str, Any]) -> RuntimeTick: ...

    def stop(self) -> None: ...

    @property
    def revision(self) -> int: ...

    @property
    def session_time_s(self) -> float: ...


class RuntimeUnavailable(Exception):
    """The runtime for this session is not attached.

    Raised rather than returning a fabricated tick, so the API answers 503 and
    the UI shows the session as unavailable.
    """

    def __init__(self, session_id: str, detail: str) -> None:
        super().__init__(detail)
        self.session_id = session_id
        self.detail = detail


__all__ = [
    "RuntimeCommand",
    "RuntimeResult",
    "RuntimeTick",
    "RuntimeUnavailable",
    "SessionRuntimePort",
]
