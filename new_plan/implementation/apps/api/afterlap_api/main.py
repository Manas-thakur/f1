"""FastAPI application factory.

The control plane only. Physics and solver work happen in the session runtime
process; nothing here blocks the asyncio event loop on a numerical routine.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION, CapabilityState
from afterlap_core.diagnostics import run_doctor
from afterlap_core.paths import ArtifactStore, Paths

from .deps import Database, Settings
from .errors import install_error_handlers
from .observability import RequestMetrics, configure_logging, metrics_response
from .routes import health, models, rulesets, sessions
from .runtime import RuntimeRegistry
from .stream import StreamHub

logger = logging.getLogger("afterlap.api")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    paths = Paths.default(settings.artifact_root).ensure()
    app.state.database = Database(settings.database_url)
    app.state.hub = StreamHub(buffer_size=settings.stream_buffer)
    app.state.runtimes = RuntimeRegistry()
    app.state.artifact_store = ArtifactStore(paths.artifacts / "objects")
    app.state.latest_state = {}
    app.state.started_at = time.monotonic()
    app.state.metrics = RequestMetrics()

    # Readiness is decided from measured capabilities, not from the fact that
    # the process started.
    report = run_doctor(paths)
    app.state.capabilities = report.capability_map()
    unavailable = [c.name for c in report.unavailable]
    if unavailable:
        logger.warning("starting with unavailable capabilities: %s", ", ".join(unavailable))

    try:
        yield
    finally:
        app.state.runtimes.stop_all()
        app.state.database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    resolved = settings or Settings.from_environment()

    app = FastAPI(
        title="AFTERLAP control plane",
        version="0.1.0",
        description=(
            "Engineer decision support for electrical deployment and racing battles. "
            "Synthetic scenarios only; the driver link is simulator-only."
        ),
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )
    app.state.settings = resolved

    install_error_handlers(app)

    @app.middleware("http")
    async def _request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.observe(request.url.path, response.status_code, duration_ms)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    app.include_router(health.router, prefix=API_PREFIX, tags=["health"])
    app.include_router(sessions.router, prefix=API_PREFIX, tags=["sessions"])
    app.include_router(rulesets.router, prefix=API_PREFIX, tags=["rulesets"])
    app.include_router(models.router, prefix=API_PREFIX, tags=["models"])

    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> JSONResponse:
        return metrics_response(app)

    @app.get(f"{API_PREFIX}/version", tags=["health"])
    async def _version() -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_revision": CONTRACT_REVISION,
            "capabilities": {
                name: state.value if isinstance(state, CapabilityState) else str(state)
                for name, state in app.state.capabilities.items()
            },
        }

    return app


app = create_app()


__all__ = ["API_PREFIX", "app", "create_app", "lifespan"]
