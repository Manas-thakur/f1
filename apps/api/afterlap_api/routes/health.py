"""Liveness and readiness.

Liveness means the process loop is alive. Readiness means the capabilities a
decision actually needs are present. A healthy HTTP server with stale telemetry
is deliberately *not* ready.

Three terms decide readiness, and they are reported separately so an operator
can tell them apart:

* **capabilities** — the startup doctor report. Necessary, not sufficient: it
  is measured once and says nothing about what has happened since.
* **storage** — the lifecycle store is probed on every request. The doctor's
  ``storage`` capability covers the artefact tree; a database that has since
  gone away is a different failure and gets its own key.
* **sessions** — whether an attached session could produce a decision *now*.
  A session withdrawing advice on an aged observation makes the process not
  ready, because the decision system it exists to be is not working.

A paused, stopped or finished session is reported in ``detail`` and never
fails readiness. ``infra/api.Dockerfile``'s healthcheck probes this route, so
failing on an idle session would restart a container whose only session an
engineer had deliberately paused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from afterlap_contracts import CapabilityState
from afterlap_contracts.requests import HealthResponse
from afterlap_core.paths import Paths

from ..runtime.port import RuntimeUnavailable
from ..session.runtime import SessionRuntimeError
from ..worker_health import BATCH_WORKER, worker_status

if TYPE_CHECKING:
    from ..runtime.registry import RuntimeRegistry

router = APIRouter()

REQUIRED_FOR_READINESS = ("contracts", "numerics", "storage")

IDLE_LIFECYCLES = frozenset({"paused", "stopped", "finished"})
"""Lifecycles that are idle by an operator's choice, not by a fault."""


@router.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="live", detail={"note": "the process loop is running"})


@router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    capabilities: dict[str, CapabilityState] = getattr(request.app.state, "capabilities", {})
    detail = {name: state.value for name, state in capabilities.items()}

    missing = [
        name
        for name in REQUIRED_FOR_READINESS
        if capabilities.get(name, CapabilityState.UNAVAILABLE) is CapabilityState.UNAVAILABLE
    ]

    store_error = _lifecycle_store_error(request)
    if store_error is not None:
        detail["lifecycle_store"] = store_error
    else:
        detail["lifecycle_store"] = "available"

    idle, unready = _session_health(getattr(request.app.state, "runtimes", None))
    if idle:
        detail["idle_sessions"] = "; ".join(idle)
    if unready:
        detail["sessions"] = "; ".join(unready)

    detail["batch_worker"] = _batch_worker(request).status

    if missing or store_error is not None or unready:
        response.status_code = 503
        if missing:
            detail["missing"] = ", ".join(missing)
        return HealthResponse(status="not_ready", detail=detail)

    return HealthResponse(status="ready", detail=detail)


@router.get("/health/workers")
async def workers(request: Request) -> dict[str, Any]:
    """What each background worker last reported about itself.

    Separate from readiness on purpose. A stale batch worker means queued
    experiments are not being claimed; it does not mean a decision cannot be
    made, and ``ARCHITECTURE.md`` puts experiment work first in line to stop
    when resources run short. Reporting it here keeps a wedged worker visible
    without letting it take the control plane down with it.
    """
    status = _batch_worker(request)
    return {"workers": [status.as_dict()]}


def _batch_worker(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    root = Paths.default(getattr(settings, "artifact_root", None)).artifacts
    return worker_status(root, BATCH_WORKER)


def _lifecycle_store_error(request: Request) -> str | None:
    """Probe the lifecycle store now rather than trusting the startup report.

    ``ARCHITECTURE.md`` makes durable lifecycle writes a precondition for
    issuing advice: a recommendation nobody can audit later is not one this
    system is willing to make. So a store that has gone away since startup is
    a readiness failure, not a warning.
    """
    database = getattr(request.app.state, "database", None)
    engine = getattr(database, "engine", None)
    if engine is None:
        return "no lifecycle store is configured"
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except SQLAlchemyError as exc:
        return f"lifecycle store is unreachable: {type(exc).__name__}"
    return None


def _session_health(registry: RuntimeRegistry | None) -> tuple[list[str], list[str]]:
    """Split attached sessions into deliberately idle and genuinely obstructed."""
    idle: list[str] = []
    unready: list[str] = []
    if registry is None:
        return idle, unready
    for session_id in registry.active_sessions:
        try:
            runtime = registry.get(session_id)
        except RuntimeUnavailable:
            unready.append(f"{session_id}: runtime is not attached")
            continue
        health = _decision_health(runtime)
        if health is None:
            continue
        if health.get("lifecycle") in IDLE_LIFECYCLES:
            idle.append(f"{session_id}: {health['lifecycle']}")
            continue
        obstructions = health.get("obstructions") or ()
        if obstructions:
            unready.append(f"{session_id}: {'; '.join(obstructions)}")
    return idle, unready


def _decision_health(runtime: object) -> dict[str, Any] | None:
    """Ask a runtime whether it can decide, tolerating one that cannot say.

    ``decision_health`` is beyond ``SessionRuntimePort``; an out-of-process
    proxy may not implement it. An absent answer is reported as no information
    rather than as health, so this route never invents a verdict it did not
    measure.
    """
    probe = getattr(runtime, "decision_health", None)
    if probe is None:
        return None
    try:
        health = probe()
    except SessionRuntimeError:
        return {"lifecycle": "running", "obstructions": ("decision health could not be measured",)}
    return {
        "lifecycle": health.lifecycle,
        "obstructions": tuple(health.obstructions),
    }


__all__ = ["IDLE_LIFECYCLES", "REQUIRED_FOR_READINESS", "router"]
