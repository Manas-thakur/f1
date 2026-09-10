"""Database connectivity probe for the core doctor report.

``afterlap_core.diagnostics`` describes what a healthy backend looks like but
owns no driver to ask one. This module is the adapter that does: it opens a
real connection to the configured URL so ``cli doctor`` and ``/health/ready``
report a measured result rather than an assumption.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text


def probe_database(url: str) -> None:
    """Connect to ``url`` and run ``select 1``.

    Returns ``None`` when the backend answered. Raises whatever SQLAlchemy
    raises when it did not, and never annotates the failure with the URL, which
    carries the credential; the caller reports the exception type alone.
    """
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    finally:
        engine.dispose()


__all__ = ["probe_database"]
