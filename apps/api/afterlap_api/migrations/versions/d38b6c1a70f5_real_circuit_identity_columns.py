"""real circuit identity columns on session and simulation_snapshot

Adds the A16 circuit identity a session's provenance depends on: which
compiled track package drove it, which event overlay was applied, which
conditions tape was bound, the readiness rung the independent validator
derived and the geometry provenance.

Every column is nullable, because a synthetic-sketch session genuinely has
none of them; a null means "there is none", never "unknown". Nothing is
backfilled: sessions created before this revision ran on a synthetic sketch or
on a package whose identity was never recorded, and inventing a hash for them
would be a fabricated measurement.

``simulation_snapshot`` carries the track identity too: a replay is only
reproducible against the geometry it was captured on.

Revision ID: d38b6c1a70f5
Revises: c04e287ba46c
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d38b6c1a70f5"
down_revision: str | None = "c04e287ba46c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SESSION_COLUMNS: tuple[tuple[str, int], ...] = (
    ("track_id", 64),
    ("track_package_hash", 80),
    ("event_id", 64),
    ("event_package_hash", 80),
    ("conditions_id", 64),
    ("conditions_hash", 80),
    ("track_readiness", 32),
    ("geometry_provenance", 48),
)

SNAPSHOT_COLUMNS: tuple[tuple[str, int], ...] = (
    ("track_id", 64),
    ("track_package_hash", 80),
)


def upgrade() -> None:
    with op.batch_alter_table("session", schema=None) as batch_op:
        for name, length in SESSION_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=length), nullable=True))
    with op.batch_alter_table("simulation_snapshot", schema=None) as batch_op:
        for name, length in SNAPSHOT_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("simulation_snapshot", schema=None) as batch_op:
        for name, _ in reversed(SNAPSHOT_COLUMNS):
            batch_op.drop_column(name)
    with op.batch_alter_table("session", schema=None) as batch_op:
        for name, _ in reversed(SESSION_COLUMNS):
            batch_op.drop_column(name)
