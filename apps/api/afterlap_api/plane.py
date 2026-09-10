from __future__ import annotations

import asyncio
import contextlib
import logging
import queue as thread_queue
import threading
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anyio.to_thread
from sqlalchemy.exc import SQLAlchemyError

from afterlap_contracts import StreamEnvelope
from afterlap_core.diagnostics import run_doctor
from afterlap_core.paths import ArtifactStore, Paths

from .call import Incoming, Outgoing
from .composition import ProcessSessionFactory
from .db import ensure_schema
from .db.models import Session
from .deps import Database, Settings
from .observability import RequestMetrics, configure_logging
from .router import invoke, load_routes
from .runtime import RuntimeRegistry
from .session import OutboxPublisher, SessionFactory, SessionRecorder
from .session.spool import BoundedSpool
from .stream import StreamHub

logger = logging.getLogger("afterlap.api")

API_PREFIX = "/api/v1"
HEARTBEAT_INTERVAL_S = 10.0


class ControlPlane:
    def __init__(self, settings: Settings | None = None) -> None:
        self.state = SimpleNamespace()
        self.state.settings = settings or Settings.from_environment()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failed: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="afterlap-plane", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("control plane did not start")
        if self._failed is not None:
            raise self._failed

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=30)
        self._loop = None
        self._thread = None
        self._ready.clear()

    def handle(self, incoming: Incoming) -> Outgoing:
        self.start()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(invoke(self, incoming), self._loop)
        return future.result(timeout=120)

    def iter_stream(self, session_id: str, after_sequence: int = 0) -> Any:
        self.start()
        assert self._loop is not None
        frames: thread_queue.Queue[str | None] = thread_queue.Queue()

        async def pump() -> None:
            try:
                async for frame in self._stream(session_id, after_sequence):
                    frames.put(frame)
            finally:
                frames.put(None)

        asyncio.run_coroutine_threadsafe(pump(), self._loop)

        def iterator() -> Any:
            while True:
                item = frames.get(timeout=120)
                if item is None:
                    return
                yield item

        return iterator()

    async def _stream(self, session_id: str, after_sequence: int) -> AsyncIterator[str]:
        hub: StreamHub = self.state.hub
        known = await anyio.to_thread.run_sync(_durable_sequence, self, session_id)
        subscriber, _ = await hub.subscribe(session_id, after_sequence, known_sequence=known)
        started = time.monotonic()
        try:
            while True:
                getter = asyncio.create_task(subscriber.queue.get())
                beat = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL_S))
                done, pending = await asyncio.wait({getter, beat}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                if getter in done:
                    envelope: StreamEnvelope = getter.result()
                    yield envelope.model_dump_json()
                else:
                    yield hub.heartbeat(session_id, time.monotonic() - started).model_dump_json()
        finally:
            await hub.unsubscribe(subscriber)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._startup())
            self._ready.set()
            loop.run_forever()
        except BaseException as exc:
            self._failed = exc
            self._ready.set()
            raise
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(self._shutdown())
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(Exception):
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _startup(self) -> None:
        settings: Settings = self.state.settings
        paths = Paths.default(settings.artifact_root).ensure()
        self.state.database = Database(settings.database_url)
        logger.info("database schema: %s", ensure_schema(self.state.database.engine))
        self.state.hub = StreamHub(buffer_size=settings.stream_buffer)
        self.state.runtimes = RuntimeRegistry()
        self.state.artifact_store = ArtifactStore(paths.artifacts / "objects")
        self.state.latest_state = {}
        self.state.started_at = time.monotonic()
        self.state.metrics = RequestMetrics()
        self.state.reports_root = paths.reports

        def _recorder(session_id: str) -> SessionRecorder:
            return SessionRecorder(
                self.state.database.factory,
                session_id=session_id,
                spool=BoundedSpool(paths.spool, session_id),
            )

        if settings.session_runtime_backend == "process":
            self.state.session_factory = ProcessSessionFactory(
                database_url=settings.database_url,
                artifact_root=paths.root,
                queue_size=settings.session_queue_size,
                command_timeout_s=settings.session_command_timeout_s,
            )
        else:
            self.state.session_factory = SessionFactory(recorder_factory=_recorder)
        self.state.track_paths = self.state.session_factory.paths
        self.state.publisher = OutboxPublisher(self.state.database.factory, self.state.hub)
        self.state.publisher.start()
        report = run_doctor(paths)
        self.state.capabilities = report.capability_map()
        unavailable = [capability.name for capability in report.unavailable]
        if unavailable:
            logger.warning("starting with unavailable capabilities: %s", ", ".join(unavailable))

    async def _shutdown(self) -> None:
        publisher = getattr(self.state, "publisher", None)
        if publisher is not None:
            await publisher.stop_running()
        runtimes = getattr(self.state, "runtimes", None)
        if runtimes is not None:
            runtimes.stop_all()
        database = getattr(self.state, "database", None)
        if database is not None:
            database.dispose()


def _durable_sequence(plane: ControlPlane, session_id: str) -> int | None:
    database = getattr(plane.state, "database", None)
    factory = getattr(database, "factory", None)
    if factory is None:
        return None
    try:
        with factory() as db:
            row = db.get(Session, session_id)
            return None if row is None else int(row.last_sequence)
    except SQLAlchemyError:
        return None


def create_app(settings: Settings | None = None) -> ControlPlane:
    configure_logging()
    load_routes()
    return ControlPlane(settings)


app = None

__all__ = ["API_PREFIX", "ControlPlane", "app", "create_app"]
