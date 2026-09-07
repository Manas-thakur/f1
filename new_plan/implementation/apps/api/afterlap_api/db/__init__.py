"""Persistence layer. Schema and migrations are coordinator-owned."""

from __future__ import annotations

from .engine import (
    command_transaction,
    create_all,
    create_db_engine,
    create_session_factory,
    default_database_url,
    transaction,
)
from .models import Base
from .repository import (
    LifecycleError,
    acquire_lease,
    append_event,
    apply_operator_action,
    body_hash_of,
    expire_due,
    invalidate_outstanding,
    record_execution,
    require_lease,
    store_decision,
)

__all__ = [
    "Base",
    "LifecycleError",
    "acquire_lease",
    "append_event",
    "apply_operator_action",
    "body_hash_of",
    "command_transaction",
    "create_all",
    "create_db_engine",
    "create_session_factory",
    "default_database_url",
    "expire_due",
    "invalidate_outstanding",
    "record_execution",
    "require_lease",
    "store_decision",
    "transaction",
]
