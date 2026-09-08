"""Alembic environment.

The database URL comes from ``AFTERLAP_DATABASE_URL`` (or the local SQLite
default) rather than from alembic.ini, so a deployment never has a credential
written into a version-controlled file.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from afterlap_api.db.engine import default_database_url
from afterlap_api.db.models import Base

config = context.config

# Only fall back to the environment's default when the caller has not already
# named a database. Overriding unconditionally made `ensure_schema` migrate the
# default store while reporting success for whichever engine it was handed --
# it created zero tables in a test database and said "schema at migration
# head". The server appeared to work only because its URL happened to be the
# default one.
if not config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", default_database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode makes the
            # same migration script work on both engines.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
