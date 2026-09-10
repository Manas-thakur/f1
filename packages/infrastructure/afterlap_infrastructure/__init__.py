"""Infrastructure adapters for persistence and operational transport.

Importing this package installs the adapters the domain core declares but
cannot implement, so any process that has the infrastructure layer available
measures the real thing.
"""

from __future__ import annotations

from afterlap_core.diagnostics import register_database_probe

from .diagnostics import probe_database
from .persistence import (
    Base,
    LifecycleError,
    command_transaction,
    create_db_engine,
    create_session_factory,
    default_database_url,
    transaction,
)

register_database_probe(probe_database)

__all__ = [
    "Base",
    "LifecycleError",
    "command_transaction",
    "create_db_engine",
    "create_session_factory",
    "default_database_url",
    "probe_database",
    "register_database_probe",
    "transaction",
]
