"""Migrations must produce exactly the schema the ORM models declare.

A drift here means a deployment would run against a different shape than the
code expects, so this is a build failure rather than a warning.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from afterlap_api.db.engine import create_all, create_db_engine
from afterlap_api.db.models import Base

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"


def _alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "afterlap_api" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migrated_url(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'migrated.sqlite3').as_posix()}"
    monkeypatch.setenv("AFTERLAP_DATABASE_URL", url)
    command.upgrade(_alembic_config(url), "head")
    return url


def test_there_is_exactly_one_migration_head():
    script = ScriptDirectory(str(API_ROOT / "afterlap_api" / "migrations"))
    heads = script.get_heads()
    assert len(heads) == 1, f"parallel migration heads would make an upgrade ambiguous: {heads}"


def test_migrated_schema_matches_the_orm_models(migrated_url, tmp_path):
    migrated = create_db_engine(migrated_url)
    declared = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'declared.sqlite3').as_posix()}")
    create_all(declared)

    migrated_tables = set(inspect(migrated).get_table_names()) - {"alembic_version"}
    declared_tables = set(inspect(declared).get_table_names())
    assert migrated_tables == declared_tables

    for table in sorted(declared_tables):
        migrated_columns = {c["name"]: c for c in inspect(migrated).get_columns(table)}
        declared_columns = {c["name"]: c for c in inspect(declared).get_columns(table)}
        assert set(migrated_columns) == set(declared_columns), f"column drift in {table}"
        for name, declared_column in declared_columns.items():
            assert migrated_columns[name]["nullable"] == declared_column["nullable"], (
                f"{table}.{name} nullability differs between the migration and the model"
            )
            assert str(migrated_columns[name]["type"]) == str(declared_column["type"]), (
                f"{table}.{name} type differs between the migration and the model"
            )


def test_migration_downgrades_cleanly(migrated_url):
    config = _alembic_config(migrated_url)
    command.downgrade(config, "base")

    engine = create_db_engine(migrated_url)
    remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"

    command.upgrade(config, "head")
    assert set(inspect(create_db_engine(migrated_url)).get_table_names()) - {"alembic_version"} == set(
        Base.metadata.tables
    )


def test_every_declared_table_is_migrated(migrated_url):
    engine = create_db_engine(migrated_url)
    migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert set(Base.metadata.tables) == migrated


def test_foreign_keys_are_enforced(tmp_path):
    """SQLite disables foreign keys by default; the schema relies on them."""
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'fk.sqlite3').as_posix()}")
    create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
