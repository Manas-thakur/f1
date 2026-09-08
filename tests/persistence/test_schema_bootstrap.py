"""``ensure_schema`` must migrate the database it was handed.

Regression test for a defect in the startup bootstrap itself. The Alembic
environment overrode ``sqlalchemy.url`` with the process default
unconditionally, so ``ensure_schema(engine)`` migrated the *default* store while
reporting success for whichever engine it was given. It created zero tables in
a test database and returned "schema at migration head".

That is the failure mode this whole codebase is built to avoid: a success
report with nothing behind it. The server appeared to work only because its URL
happened to be the default one, so the two coincided by luck.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from afterlap_api.db import create_db_engine, ensure_schema
from afterlap_api.db.models import Base


def _url(tmp_path, name: str) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"


def test_ensure_schema_migrates_the_engine_it_was_given(tmp_path):
    engine = create_db_engine(_url(tmp_path, "given.sqlite3"))

    detail = ensure_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert tables, (
        f"ensure_schema returned {detail!r} but created no tables in the engine it was "
        "handed; a success report with nothing behind it is worse than a failure"
    )
    assert "alembic_version" in tables, "the migration must record that it ran"
    assert set(Base.metadata.tables) <= tables, (
        f"missing tables after bootstrap: {sorted(set(Base.metadata.tables) - tables)}"
    )


def test_ensure_schema_does_not_touch_an_unrelated_database(tmp_path):
    """Migrating one store must leave another alone."""
    target = create_db_engine(_url(tmp_path, "target.sqlite3"))
    bystander = create_db_engine(_url(tmp_path, "bystander.sqlite3"))

    ensure_schema(target)

    assert inspect(target).get_table_names(), "the named database was not migrated"
    assert inspect(bystander).get_table_names() == [], (
        "migrating one database created tables in another; the environment is ignoring the URL it was given"
    )


def test_ensure_schema_is_idempotent(tmp_path):
    engine = create_db_engine(_url(tmp_path, "twice.sqlite3"))
    ensure_schema(engine)
    first = set(inspect(engine).get_table_names())
    ensure_schema(engine)
    assert set(inspect(engine).get_table_names()) == first


@pytest.mark.parametrize("name", ["outbox", "session", "decision", "execution_event", "control_lease"])
def test_the_tables_the_runtime_depends_on_exist(tmp_path, name):
    """Named individually, because a partial schema fails far from its cause.

    A missing `outbox` surfaced as an ORM error inside the publisher, several
    layers away from the bootstrap that should have created it.
    """
    engine = create_db_engine(_url(tmp_path, f"{name}.sqlite3"))
    ensure_schema(engine)
    assert name in set(inspect(engine).get_table_names())
