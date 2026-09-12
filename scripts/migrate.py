#!/usr/bin/env python
"""The compose migration job.

Runs the Alembic upgrade to head against ``AFTERLAP_DATABASE_URL`` and prints
the revision that landed. It exists as a separate one-shot service, rather than
as a shell step inside the API entrypoint, so that a failed upgrade stops the
stack: `docker-compose.yml` gates the API on
`migrate: condition: service_completed_successfully`.

The API *also* calls `ensure_schema` during startup. That duplication is
deliberate — coordinator decision D-07 defect 1 was a clean install with no
schema at all, and `alembic upgrade head` is idempotent — so a developer
running `python -m afterlap_api.cli serve` directly gets a working database without remembering a
second command, while the packaged stack still fails loudly if the migration
cannot be applied.

    python scripts/migrate.py [--wait-for-database SECONDS] [--url URL]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _ensure_workspace_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    for candidate in (
        root / "apps" / "api",
        root / "packages" / "core",
        root / "packages" / "contracts",
        root / "packages" / "infrastructure",
        root / "packages" / "application",
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _wait_for_database(url: str, timeout_s: float) -> float:
    """Poll until a connection succeeds. A container start order is not a fact."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from afterlap_core.diagnostics import redact
    from afterlap_infrastructure.persistence.engine import create_db_engine

    started = time.monotonic()
    deadline = started + timeout_s
    attempt = 0
    last = "no attempt was made"
    while time.monotonic() < deadline:
        attempt += 1
        engine = create_db_engine(url)
        try:
            with engine.connect() as connection:
                connection.execute(text("select 1"))
            engine.dispose()
            waited = time.monotonic() - started
            print(f"database reachable at {redact(url)} after {waited:.2f} s ({attempt} attempt(s))")
            return waited
        except SQLAlchemyError as exc:
            last = f"{type(exc).__name__}"
            engine.dispose()
            time.sleep(1.0)
    raise SystemExit(
        f"database at {redact(url)} was not reachable within {timeout_s:.0f} s; last error {last}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bring the AFTERLAP schema to the migration head.")
    parser.add_argument(
        "--url",
        default=None,
        help="Database URL. Defaults to AFTERLAP_DATABASE_URL, then the local SQLite store.",
    )
    parser.add_argument(
        "--wait-for-database",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="Poll for a reachable database before migrating (compose passes 60).",
    )
    args = parser.parse_args(argv)

    try:
        from afterlap_infrastructure.persistence.engine import create_db_engine, default_database_url
    except ModuleNotFoundError:
        _ensure_workspace_on_path()
        from afterlap_infrastructure.persistence.engine import create_db_engine, default_database_url

    from sqlalchemy import inspect, text

    from afterlap_core.diagnostics import redact
    from afterlap_infrastructure.persistence.engine import ensure_schema

    url = args.url or default_database_url()
    if args.wait_for_database > 0.0:
        _wait_for_database(url, args.wait_for_database)

    engine = create_db_engine(url)
    try:
        print(f"migrating {redact(url)} ({engine.dialect.name})")
        started = time.monotonic()
        detail = ensure_schema(engine)
        elapsed = time.monotonic() - started

        inspector = inspect(engine)
        tables = sorted(inspector.get_table_names())
        if "alembic_version" not in tables:
            print("FAILED: no alembic_version table exists after the upgrade", file=sys.stderr)
            return 1
        with engine.connect() as connection:
            revisions = [
                row[0] for row in connection.execute(text("select version_num from alembic_version"))
            ]
        if not revisions:
            print("FAILED: alembic_version is empty; no migration was applied", file=sys.stderr)
            return 1
        print(f"{detail} in {elapsed:.2f} s")
        print(f"alembic head: {', '.join(revisions)}")
        print(f"{len(tables)} table(s): {', '.join(tables)}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
