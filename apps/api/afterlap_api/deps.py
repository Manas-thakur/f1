from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import ErrorCode, SessionMode

from .db import LifecycleError, create_db_engine, create_session_factory, default_database_url
from .db.engine import command_transaction, transaction
from .errors import CapabilityUnavailable, ModeNotPermitted

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .call import Headers

DEV_OPERATOR = "engineer-dev"


@dataclass(frozen=True, slots=True)
class QueryBound:
    ge: float | None = None
    le: float | None = None


@dataclass(slots=True)
class Settings:
    database_url: str = field(default_factory=default_database_url)
    host: str = "127.0.0.1"
    port: int = 8000
    development_mode: bool = True
    artifact_root: Path | None = None
    lease_ttl_s: float = 120.0
    stream_buffer: int = 512
    session_runtime_backend: Literal["process", "in_process"] = "process"
    session_queue_size: int = 32
    session_command_timeout_s: float = 30.0

    @classmethod
    def from_environment(cls) -> Settings:
        development = os.environ.get("AFTERLAP_ENV", "development") == "development"
        artifact_root = os.environ.get("AFTERLAP_ARTIFACT_ROOT")
        backend = os.environ.get("AFTERLAP_SESSION_RUNTIME", "process")
        if backend not in ("process", "in_process"):
            raise ValueError("AFTERLAP_SESSION_RUNTIME must be 'process' or 'in_process'")
        return cls(
            database_url=default_database_url(),
            host=os.environ.get("AFTERLAP_HOST", "127.0.0.1"),
            port=int(os.environ.get("AFTERLAP_PORT", "8000")),
            development_mode=development,
            artifact_root=None if artifact_root is None else Path(artifact_root),
            session_runtime_backend="process" if backend == "process" else "in_process",
            session_queue_size=int(os.environ.get("AFTERLAP_SESSION_QUEUE_SIZE", "32")),
            session_command_timeout_s=float(os.environ.get("AFTERLAP_SESSION_COMMAND_TIMEOUT_S", "30")),
        )

    def bootstrap_operator(self) -> str:
        if not self.development_mode:
            raise CapabilityUnavailable(
                "authentication",
                "no operator authentication is configured; development bootstrap is disabled",
            )
        return DEV_OPERATOR


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.engine = create_db_engine(url or default_database_url())
        self.factory = create_session_factory(self.engine)

    def session(self) -> Iterator[OrmSession]:
        with transaction(self.factory) as db:
            yield db

    def command_session(self) -> Iterator[OrmSession]:
        with command_transaction(self.factory) as db:
            yield db

    def dispose(self) -> None:
        self.engine.dispose()


def operator_from_headers(settings: Settings, headers: Headers) -> str:
    if not settings.development_mode:
        return settings.bootstrap_operator()
    supplied = headers.get("x-operator-id")
    if supplied:
        return supplied
    return settings.bootstrap_operator()


def require_idempotency(headers: Headers) -> str:
    key = headers.get("idempotency-key")
    if not key or len(key) > 128 or not key.isascii() or not all(32 < ord(char) < 127 for char in key):
        raise LifecycleError(
            ErrorCode.VALIDATION_FAILED, "Idempotency-Key must contain 1 to 128 visible ASCII characters"
        )
    return key


def require_simulation_mode(mode: SessionMode, operation: str) -> None:
    if mode is not SessionMode.SIMULATION:
        raise ModeNotPermitted(mode.value, operation)


OperatorId = Annotated[str, "operator"]
IdempotencyKey = Annotated[str, "idempotency"]
DbSession = Annotated[OrmSession, "db"]
CommandDbSession = Annotated[OrmSession, "command"]

__all__ = [
    "DEV_OPERATOR",
    "CommandDbSession",
    "Database",
    "DbSession",
    "IdempotencyKey",
    "OperatorId",
    "QueryBound",
    "Settings",
    "operator_from_headers",
    "require_idempotency",
    "require_simulation_mode",
]
