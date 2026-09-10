"""FastAPI application factory.

The control plane only. Physics and solver work happen in the session runtime
process; nothing here blocks the asyncio event loop on a numerical routine.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response

from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION, CapabilityState
from afterlap_core.diagnostics import run_doctor
from afterlap_core.paths import ArtifactStore, Paths

from .composition import ProcessSessionFactory
from .db import ensure_schema
from .deps import Database, Settings
from .errors import install_error_handlers
from .observability import RequestMetrics, configure_logging, metrics_response
from .routes import catalog, experiments, exports, health, models, rulesets, sessions
from .runtime import RuntimeRegistry
from .session import OutboxPublisher, SessionFactory, SessionRecorder
from .session.spool import BoundedSpool
from .stream import StreamHub

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi.responses import JSONResponse

logger = logging.getLogger("afterlap.api")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    paths = Paths.default(settings.artifact_root).ensure()
    app.state.database = Database(settings.database_url)

    logger.info("database schema: %s", ensure_schema(app.state.database.engine))

    app.state.hub = StreamHub(buffer_size=settings.stream_buffer)
    app.state.runtimes = RuntimeRegistry()
    app.state.artifact_store = ArtifactStore(paths.artifacts / "objects")
    app.state.latest_state = {}
    app.state.started_at = time.monotonic()
    app.state.metrics = RequestMetrics()
    app.state.reports_root = paths.reports

    def _recorder(session_id: str) -> SessionRecorder:
        """One durable recorder per session, with a bounded local spool.

        A store outage spools; an exhausted spool halts new recommendations so
        auditability is preserved rather than advice continuing unrecorded.
        """
        return SessionRecorder(
            app.state.database.factory,
            session_id=session_id,
            spool=BoundedSpool(paths.spool, session_id),
        )

    if settings.session_runtime_backend == "process":
        app.state.session_factory = ProcessSessionFactory(
            database_url=settings.database_url,
            artifact_root=paths.root,
            queue_size=settings.session_queue_size,
            command_timeout_s=settings.session_command_timeout_s,
        )
    else:
        app.state.session_factory = SessionFactory(recorder_factory=_recorder)
    app.state.track_paths = app.state.session_factory.paths
    app.state.publisher = OutboxPublisher(app.state.database.factory, app.state.hub)
    app.state.publisher.start()

    report = run_doctor(paths)
    app.state.capabilities = report.capability_map()
    unavailable = [c.name for c in report.unavailable]
    if unavailable:
        logger.warning("starting with unavailable capabilities: %s", ", ".join(unavailable))

    try:
        yield
    finally:
        await app.state.publisher.stop_running()
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
    async def _request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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
    app.include_router(experiments.router, prefix=API_PREFIX, tags=["experiments"])
    app.include_router(exports.router, prefix=API_PREFIX, tags=["exports"])
    app.include_router(catalog.router, prefix=API_PREFIX, tags=["catalogue"])

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
