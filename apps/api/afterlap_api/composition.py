"""Runtime composition shared by the API parent and the spawned session child.

This module is the only place that names both halves of an out-of-process
session. The application layer describes *that* a session owner runs in its
own process; here the HTTP app says *which* adapter builds it, and the child
imports the same reference back through ``WorkerConfig.runtime_builder``.

Session identity is resolved, validated and hashed in the parent **before** the
child exists, then frozen into the config. The child rebuilds the manifest from
the same inputs and refuses to serve if the content hash differs, so a session's
durable records can never be written under an identity the control plane did
not authorise.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from afterlap_application import ProcessSessionRuntime, SessionRuntimePort, WorkerConfig
from afterlap_contracts import SessionManifest, SessionMode
from afterlap_contracts.requests import CreateSessionRequest
from afterlap_core.paths import Paths

from .db import create_db_engine, create_session_factory
from .session.factory import SessionFactory, SessionValidationError
from .session.recorder import SessionRecorder
from .session.spool import BoundedSpool

if TYPE_CHECKING:
    from collections.abc import Callable

RUNTIME_BUILDER = "afterlap_api.composition:build_session_runtime"


class ProcessSessionFactory:
    """Prepare session identity in the API and construct its owner by spawn.

    Exposes the same ``(manifest, runtime)`` contract as :class:`SessionFactory`
    so ``routes/sessions.py`` needs no second code path, and the same ``paths``
    accessor so the read-only catalogue routes still report the artefact tree a
    session actually resolved from.
    """

    def __init__(
        self,
        *,
        database_url: str,
        artifact_root: Path | None,
        queue_size: int = 32,
        command_timeout_s: float = 30.0,
        validator: SessionFactory | None = None,
    ) -> None:
        self._database_url = database_url
        self._artifact_root = artifact_root
        self._queue_size = queue_size
        self._command_timeout_s = command_timeout_s
        self._validator = validator or SessionFactory()

    @property
    def paths(self) -> Paths | None:
        return self._validator.paths

    def create(
        self, payload: CreateSessionRequest, *, session_id: str | None = None
    ) -> tuple[SessionManifest, SessionRuntimePort]:
        manifest = self._validator.prepare(payload, session_id=session_id)
        config = WorkerConfig(
            session_id=manifest.id,
            scenario_id=payload.scenario_id,
            ruleset_id=payload.ruleset_id,
            seed=payload.seed,
            runtime_builder=RUNTIME_BUILDER,
            label=payload.label,
            database_url=self._database_url,
            artifact_root=None if self._artifact_root is None else str(self._artifact_root),
            request_payload=payload.model_dump(mode="json"),
            manifest_payload=manifest.model_dump(mode="json"),
            manifest_hash=manifest.content_hash(),
        )
        runtime = ProcessSessionRuntime(
            config,
            queue_size=self._queue_size,
            command_timeout_s=self._command_timeout_s,
        )
        try:
            runtime.initialise(manifest, payload.scenario_id, payload.seed)
        except BaseException:
            runtime.stop()
            raise
        return manifest, runtime


def build_session_runtime(config: WorkerConfig) -> SessionRuntimePort:
    """Build the runtime inside the spawned child from frozen serializable inputs."""
    request = (
        CreateSessionRequest.model_validate(config.request_payload)
        if config.request_payload is not None
        else CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id=config.scenario_id,
            ruleset_id=config.ruleset_id,
            seed=config.seed,
            label=config.label,
        )
    )
    recorder_factory = _recorder_factory(config)
    factory = SessionFactory(recorder_factory=recorder_factory)
    manifest = (
        SessionManifest.model_validate(config.manifest_payload)
        if config.manifest_payload is not None
        else factory.prepare(request, session_id=config.session_id)
    )
    if config.manifest_hash is not None and manifest.content_hash() != config.manifest_hash:
        raise SessionValidationError("spawned runtime received a different session manifest")
    return factory.create_from_manifest(request, manifest)


def _recorder_factory(config: WorkerConfig) -> Callable[[str], SessionRecorder] | None:
    """One durable recorder per session, owned by the child that decides.

    The child opens its own engine: a connection pool cannot be inherited
    across ``spawn``, and the audit trail has to be written by the process that
    produced the decision rather than relayed through the control plane.
    """
    if config.database_url is None:
        return None
    engine = create_db_engine(config.database_url)
    session_factory = create_session_factory(engine)
    spool_root = (
        None if config.artifact_root is None else Paths.default(Path(config.artifact_root)).ensure().spool
    )

    def build(session_id: str) -> SessionRecorder:
        spool = None if spool_root is None else BoundedSpool(spool_root, session_id)
        return SessionRecorder(session_factory, session_id=session_id, spool=spool)

    return build


__all__ = ["RUNTIME_BUILDER", "ProcessSessionFactory", "build_session_runtime"]
