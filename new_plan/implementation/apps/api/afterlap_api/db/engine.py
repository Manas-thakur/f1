"""Engine and session factory.

Defaults to a local SQLite file so a clean install runs without a database
server. Setting ``AFTERLAP_DATABASE_URL`` switches to PostgreSQL; nothing else
in the application changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from afterlap_core.paths import Paths

from .models import Base

DEFAULT_SQLITE_NAME = "afterlap.sqlite3"


def default_database_url(paths: Paths | None = None) -> str:
    configured = os.environ.get("AFTERLAP_DATABASE_URL")
    if configured:
        return configured
    resolved = (paths or Paths.default()).ensure()
    return f"sqlite+pysqlite:///{(resolved.artifacts / DEFAULT_SQLITE_NAME).as_posix()}"


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an engine with the pragmas the lifecycle guarantees depend on."""
    resolved = url or default_database_url()
    connect_args: dict[str, object] = {}
    if resolved.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(resolved, echo=echo, future=True, connect_args=connect_args, pool_pre_ping=True)

    if resolved.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            # Foreign keys are off by default on SQLite; the schema relies on them.
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL keeps a reader from blocking the session writer.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[OrmSession]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Create the schema directly.

    Used by tests and by the SQLite development path. The PostgreSQL deployment
    path runs Alembic migrations instead so upgrades are reviewable.
    """
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


@contextmanager
def transaction(factory: sessionmaker[OrmSession]) -> Iterator[OrmSession]:
    """One unit of work. Commits on success, rolls back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def command_transaction(factory: sessionmaker[OrmSession]) -> Iterator[OrmSession]:
    """Unit of work for an operator command.

    Commits on success. On a :class:`LifecycleError` marked ``persist`` it
    commits the state the guard discovered — an expiry or an invalidation is a
    fact about the session, not a side effect of the refused request — and then
    re-raises. Every other exception rolls back.
    """
    from .repository import LifecycleError

    session = factory()
    try:
        yield session
        session.commit()
    except LifecycleError as error:
        if error.persist:
            session.commit()
        else:
            session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    _, _, location = url.partition(":///")
    return Path(location) if location else None


__all__ = [
    "DEFAULT_SQLITE_NAME",
    "command_transaction",
    "create_all",
    "create_db_engine",
    "create_session_factory",
    "default_database_url",
    "drop_all",
    "sqlite_path",
    "transaction",
]
