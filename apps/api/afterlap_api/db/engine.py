"""Engine and session factory.

Defaults to a local SQLite file so a clean install runs without a database
server. Setting ``AFTERLAP_DATABASE_URL`` switches to PostgreSQL; nothing else
in the application changes.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from afterlap_core.paths import Paths

from .models import Base

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[OrmSession]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_schema(engine: Engine) -> str:
    """Bring the database up to the current migration head.

    The application must not assume someone ran a migration job first. A clean
    install that answers 503 for every session because a table is missing is a
    broken install, not a configuration reminder -- and the failure surfaces as
    an opaque 500 from deep inside the ORM rather than as anything actionable.

    Alembic is used for both engines so development and deployment share one
    code path; ``tests/persistence/test_migrations.py`` already asserts the
    migrated schema matches the ORM metadata column for column.

    Returns a short description of what it did, for the startup log.
    """
    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "afterlap_api" / "migrations"))
    config.set_main_option("sqlalchemy.url", str(engine.url.render_as_string(hide_password=False)))
    config.attributes["connection"] = None

    command.upgrade(config, "head")
    return f"schema at migration head for {engine.dialect.name}"


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
