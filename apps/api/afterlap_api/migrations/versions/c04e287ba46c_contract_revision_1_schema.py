"""contract revision 1 schema

Revision ID: c04e287ba46c
Revises:
Create Date: 2026-09-08 04:26:30.856722
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c04e287ba46c"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_job",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("worker_lease", sa.String(length=80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("report_hash", sa.String(length=80), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("partial_results", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("progress >= 0 and progress <= 1", name="ck_experiment_job_progress_fraction"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("experiment_job", schema=None) as batch_op:
        batch_op.create_index("ix_experiment_job_scheduling", ["status", "created_at"], unique=False)

    op.create_table(
        "manifest",
        sa.Column("hash", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("hash"),
    )
    with op.batch_alter_table("manifest", schema=None) as batch_op:
        batch_op.create_index("ix_manifest_kind", ["kind"], unique=False)

    op.create_table(
        "model_bundle",
        sa.Column("hash", sa.String(length=80), nullable=False),
        sa.Column("bundle_id", sa.String(length=120), nullable=False),
        sa.Column(
            "manifest",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("approval_status", sa.String(length=24), nullable=False),
        sa.Column("approval_event_id", sa.String(length=64), nullable=True),
        sa.Column("benchmark_report_hash", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "approval_status in ('unevaluated','candidate','rejected','approved')",
            name="ck_model_bundle_approval_is_known",
        ),
        sa.PrimaryKeyConstraint("hash"),
        sa.UniqueConstraint("bundle_id", name="uq_model_bundle_id"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column(
            "envelope",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_outbox_session_sequence"),
    )
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.create_index("ix_outbox_unpublished", ["published_at", "created_at"], unique=False)

    op.create_table(
        "rule_manifest",
        sa.Column("hash", sa.String(length=80), nullable=False),
        sa.Column("ruleset_id", sa.String(length=120), nullable=False),
        sa.Column("season_revision", sa.String(length=64), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("hash"),
    )
    op.create_table(
        "session",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("session_time_s", sa.Float(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.String(length=120), nullable=True),
        sa.Column("ruleset_hash", sa.String(length=80), nullable=False),
        sa.Column("model_hash", sa.String(length=80), nullable=True),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.CheckConstraint("mode in ('simulation','replay','live_team')", name="ck_session_mode_is_known"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_session_sequence_nonnegative"),
        sa.CheckConstraint("revision >= 0", name="ck_session_revision_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.create_index("ix_session_status_created", ["status", "created_at"], unique=False)

    op.create_table(
        "control_lease",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("operator_id", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("granted_at_s", sa.Float(), nullable=False),
        sa.Column("expires_at_s", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at_s > granted_at_s", name="ck_control_lease_window_positive"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "decision",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("ruleset_hash", sa.String(length=80), nullable=False),
        sa.Column("model_hash", sa.String(length=80), nullable=True),
        sa.Column("objective_version", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("observation_cutoff_s", sa.Float(), nullable=False),
        sa.Column("expires_at_s", sa.Float(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "estimate_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_decision_revision_nonnegative"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("decision", schema=None) as batch_op:
        batch_op.create_index("ix_decision_session_created", ["session_id", "created_at"], unique=False)

    op.create_table(
        "export_job",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column(
            "hashes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "operator_command",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("body_hash", sa.String(length=80), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.String(length=80), nullable=False),
        sa.Column("resulting_event_id", sa.String(length=64), nullable=True),
        sa.Column(
            "response_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_operator_command_idempotency"),
    )
    op.create_table(
        "session_event",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("session_time_s", sa.Float(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_session_event_sequence_nonnegative"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
    )
    with op.batch_alter_table("session_event", schema=None) as batch_op:
        batch_op.create_index("ix_session_event_type", ["session_id", "event_type"], unique=False)

    op.create_table(
        "simulation_snapshot",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=80), nullable=False),
        sa.Column("session_time_s", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("simulation_snapshot", schema=None) as batch_op:
        batch_op.create_index("ix_snapshot_session", ["session_id", "session_time_s"], unique=False)

    op.create_table(
        "source_capability",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "source_id", name="uq_source_capability_per_session"),
    )
    op.create_table(
        "telemetry_chunk",
        sa.Column("hash", sa.String(length=80), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("car_id", sa.String(length=40), nullable=True),
        sa.Column("channel_family", sa.String(length=40), nullable=False),
        sa.Column("start_session_time_s", sa.Float(), nullable=False),
        sa.Column("end_session_time_s", sa.Float(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mapping_revision", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_session_time_s >= start_session_time_s", name="ck_telemetry_chunk_window"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hash"),
    )
    with op.batch_alter_table("telemetry_chunk", schema=None) as batch_op:
        batch_op.create_index(
            "ix_telemetry_chunk_window", ["session_id", "start_session_time_s"], unique=False
        )

    op.create_table(
        "execution_event",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=True),
        sa.Column("observed_profile_id", sa.String(length=32), nullable=False),
        sa.Column("match_status", sa.String(length=32), nullable=False),
        sa.Column("start_time_s", sa.Float(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decision.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("execution_event", schema=None) as batch_op:
        batch_op.create_index("ix_execution_event_session", ["session_id", "start_time_s"], unique=False)

    op.create_table(
        "lifecycle_event",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=False),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("session_time_s", sa.Float(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evidence_event_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("from_state <> to_state", name="ck_lifecycle_event_changes_state"),
        sa.ForeignKeyConstraint(["decision_id"], ["decision.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outcome_record",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=80), nullable=False),
        sa.Column("event_observed", sa.Boolean(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decision.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("outcome_record", schema=None) as batch_op:
        batch_op.create_index("ix_outcome_record_session", ["session_id", "checkpoint_id"], unique=False)

    op.create_table(
        "plan_candidate",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=True),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("intention", sa.String(length=32), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decision.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plan_candidate", schema=None) as batch_op:
        batch_op.create_index("ix_plan_candidate_decision", ["decision_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("plan_candidate", schema=None) as batch_op:
        batch_op.drop_index("ix_plan_candidate_decision")

    op.drop_table("plan_candidate")
    with op.batch_alter_table("outcome_record", schema=None) as batch_op:
        batch_op.drop_index("ix_outcome_record_session")

    op.drop_table("outcome_record")
    op.drop_table("lifecycle_event")
    with op.batch_alter_table("execution_event", schema=None) as batch_op:
        batch_op.drop_index("ix_execution_event_session")

    op.drop_table("execution_event")
    with op.batch_alter_table("telemetry_chunk", schema=None) as batch_op:
        batch_op.drop_index("ix_telemetry_chunk_window")

    op.drop_table("telemetry_chunk")
    op.drop_table("source_capability")
    with op.batch_alter_table("simulation_snapshot", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshot_session")

    op.drop_table("simulation_snapshot")
    with op.batch_alter_table("session_event", schema=None) as batch_op:
        batch_op.drop_index("ix_session_event_type")

    op.drop_table("session_event")
    op.drop_table("operator_command")
    op.drop_table("export_job")
    with op.batch_alter_table("decision", schema=None) as batch_op:
        batch_op.drop_index("ix_decision_session_created")

    op.drop_table("decision")
    op.drop_table("control_lease")
    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.drop_index("ix_session_status_created")

    op.drop_table("session")
    op.drop_table("rule_manifest")
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.drop_index("ix_outbox_unpublished")

    op.drop_table("outbox")
    op.drop_table("model_bundle")
    with op.batch_alter_table("manifest", schema=None) as batch_op:
        batch_op.drop_index("ix_manifest_kind")

    op.drop_table("manifest")
    with op.batch_alter_table("experiment_job", schema=None) as batch_op:
        batch_op.drop_index("ix_experiment_job_scheduling")

    op.drop_table("experiment_job")
