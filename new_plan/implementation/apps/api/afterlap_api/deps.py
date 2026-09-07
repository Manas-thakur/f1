"""Request-scoped dependencies: identity, idempotency, database and settings.

Local development binds loopback and uses a development operator identity. A
team deployment supplies real authentication; the shape of the dependency does
not change, so no route needs a second code path.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session as OrmSession

from afterlap_contracts import SessionMode

from .db import LifecycleError, create_db_engine, create_session_factory, default_database_url
from .db.engine import command_transaction, transaction
from .errors import CapabilityUnavailable, ModeNotPermitted

DEV_OPERATOR = "engineer-dev"


@dataclass(slots=True)
class Settings:
    """Runtime configuration. No default production secret exists."""

    database_url: str = field(default_factory=default_database_url)
    host: str = "127.0.0.1"
    port: int = 8000
    development_mode: bool = True
    artifact_root: Path | None = None
    lease_ttl_s: float = 120.0
    stream_buffer: int = 512

    @classmethod
    def from_environment(cls) -> Settings:
        development = os.environ.get("AFTERLAP_ENV", "development") == "development"
        return cls(
            database_url=default_database_url(),
            host=os.environ.get("AFTERLAP_HOST", "127.0.0.1"),
            port=int(os.environ.get("AFTERLAP_PORT", "8000")),
            development_mode=development,
        )

    def bootstrap_operator(self) -> str:
        """A development-only operator identity.

        Refuses outside development mode: a deployment must supply real
        authentication rather than inheriting a convenience default.
        """
        if not self.development_mode:
            raise CapabilityUnavailable(
                "authentication",
                "no operator authentication is configured; development bootstrap is disabled",
            )
        return DEV_OPERATOR


class Database:
    """Engine and session factory held for the process lifetime."""

    def __init__(self, url: str | None = None) -> None:
        self.engine = create_db_engine(url or default_database_url())
        self.factory = create_session_factory(self.engine)

    def session(self) -> Iterator[OrmSession]:
        with transaction(self.factory) as db:
            yield db

    def command_session(self) -> Iterator[OrmSession]:
        """Unit of work for an operator command.

        Uses the transaction that persists a guard's finding — an expiry or an
        invalidation — even when the command itself is refused.
        """
        with command_transaction(self.factory) as db:
            yield db

    def dispose(self) -> None:
        self.engine.dispose()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.database


def db_session(database: Annotated[Database, Depends(get_database)]) -> Iterator[OrmSession]:
    yield from database.session()


def command_db_session(database: Annotated[Database, Depends(get_database)]) -> Iterator[OrmSession]:
    yield from database.command_session()


def request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if existing is None:
        existing = f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = existing
    return existing


def operator_identity(
    settings: Annotated[Settings, Depends(get_settings)],
    x_operator_id: Annotated[str | None, Header(alias="X-Operator-Id")] = None,
) -> str:
    """Resolve the acting operator.

    Human and automated changes are audited distinctly, so this identity is
    recorded on every command rather than inferred later.
    """
    if x_operator_id:
        return x_operator_id
    return settings.bootstrap_operator()


def idempotency_key(
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """Every mutable route requires a key, so a retry is never a second decision."""
    if not idempotency_key_header:
        raise LifecycleError(
            __import__("afterlap_contracts", fromlist=["ErrorCode"]).ErrorCode.VALIDATION_FAILED,
            "this route requires an Idempotency-Key header",
        )
    return idempotency_key_header


def require_simulation_mode(mode: SessionMode, operation: str) -> None:
    """Server-side mode enforcement.

    Applies even if someone opens the driver URL directly or crafts the request
    by hand: the frontend's controls are not the authority here.
    """
    if mode is not SessionMode.SIMULATION:
        raise ModeNotPermitted(mode.value, operation)


OperatorId = Annotated[str, Depends(operator_identity)]
IdempotencyKey = Annotated[str, Depends(idempotency_key)]
DbSession = Annotated[OrmSession, Depends(db_session)]
CommandDbSession = Annotated[OrmSession, Depends(command_db_session)]
RequestId = Annotated[str, Depends(request_id)]
AppSettings = Annotated[Settings, Depends(get_settings)]


__all__ = [
    "DEV_OPERATOR",
    "AppSettings",
    "CommandDbSession",
    "Database",
    "DbSession",
    "IdempotencyKey",
    "OperatorId",
    "RequestId",
    "Settings",
    "get_database",
    "get_settings",
    "require_simulation_mode",
]
