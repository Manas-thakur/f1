"""Liveness and readiness.

Liveness means the process loop is alive. Readiness means the capabilities a
decision actually needs are present. A healthy HTTP server with stale telemetry
is deliberately *not* ready.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from afterlap_contracts import CapabilityState
from afterlap_contracts.requests import HealthResponse

router = APIRouter()

REQUIRED_FOR_READINESS = ("contracts", "numerics", "storage")


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
    if missing:
        response.status_code = 503
        detail["missing"] = ", ".join(missing)
        return HealthResponse(status="not_ready", detail=detail)

    return HealthResponse(status="ready", detail=detail)
