"""Relational schema. Coordinator-owned; workers do not add or alter tables.

PostgreSQL is the target engine. The same declarative models run on SQLite for
local development and tests, which is why JSON columns use the portable
``JSON`` type with a PostgreSQL ``JSONB`` variant.

Design rules taken from ``08_backend/PERSISTENCE_AND_WORKERS.md``:

- IDs are immutable strings; revisions are integers checked optimistically.
- A decision keeps the estimate it was made from. Later knowledge never
  overwrites it.
- Bulk telemetry lives in Parquet; this database stores chunk indexes and
  evidence references, not every 100 Hz physical state.
- Committed events and lifecycle revision changes happen in one transaction,
  together with a transactional outbox row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")
"""Portable JSON column that becomes JSONB on PostgreSQL."""


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Session(Base):
    """One operational or laboratory session."""

    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    session_time_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenario_id: Mapped[str | None] = mapped_column(String(120))
    ruleset_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    model_hash: Mapped[str | None] = mapped_column(String(80))
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    label: Mapped[str | None] = mapped_column(String(200))

    # A16 real-circuit identity. All nullable: a synthetic-sketch session has
    # no package, no event overlay and no conditions tape, and a null here
    # means "there is none", never "unknown". Every value is a copy of the
    # session manifest's, so a stored row can be checked against the manifest
    # and against the stream event that announced the session.
    track_id: Mapped[str | None] = mapped_column(String(64))
    track_package_hash: Mapped[str | None] = mapped_column(String(80))
    event_id: Mapped[str | None] = mapped_column(String(64))
    event_package_hash: Mapped[str | None] = mapped_column(String(80))
    conditions_id: Mapped[str | None] = mapped_column(String(64))
    conditions_hash: Mapped[str | None] = mapped_column(String(80))
    track_readiness: Mapped[str | None] = mapped_column(String(32))
    geometry_provenance: Mapped[str | None] = mapped_column(String(48))

    events: Mapped[list[SessionEvent]] = relationship(back_populates="session", cascade="all, delete-orphan")
    decisions: Mapped[list[Decision]] = relationship(back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_session_revision_nonnegative"),
        CheckConstraint("last_sequence >= 0", name="ck_session_sequence_nonnegative"),
        CheckConstraint("mode in ('simulation','replay','live_team')", name="ck_session_mode_is_known"),
        Index("ix_session_status_created", "status", "created_at"),
    )


class Manifest(Base):
    """Content-addressed immutable manifest of any kind."""

    __tablename__ = "manifest"

    hash: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_manifest_kind", "kind"),)


class SourceCapabilityRow(Base):
    """Declared capability of one source, recorded at session start."""

    __tablename__ = "source_capability"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint("session_id", "source_id", name="uq_source_capability_per_session"),)


class SessionEvent(Base):
    """Ordered, immutable session event log. ``sequence`` is unique per session."""

    __tablename__ = "session_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    session_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    session: Mapped[Session] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
        CheckConstraint("sequence >= 0", name="ck_session_event_sequence_nonnegative"),
        Index("ix_session_event_type", "session_id", "event_type"),
    )


class OperatorCommand(Base):
    """Idempotency record for one human command.

    ``(session_id, idempotency_key)`` is unique. A repeat with the same
    ``body_hash`` returns the stored result; a repeat with a different body is
    a conflict, which is what makes a retry safe but a changed decision visible.
    """

    __tablename__ = "operator_command"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_id: Mapped[str] = mapped_column(String(80), nullable=False)
    resulting_event_id: Mapped[str | None] = mapped_column(String(64))
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_operator_command_idempotency"),
    )


class ControlLease(Base):
    """Single-operator control lease. One row per session."""

    __tablename__ = "control_lease"

    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), primary_key=True
    )
    operator_id: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    granted_at_s: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at_s: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("expires_at_s > granted_at_s", name="ck_control_lease_window_positive"),
    )


class Decision(Base):
    """A published recommendation with the estimate it was actually made from."""

    __tablename__ = "decision"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    model_hash: Mapped[str | None] = mapped_column(String(80))
    objective_version: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_cutoff_s: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at_s: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    estimate_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, doc="Frozen copy of the estimate at publication; never updated."
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    session: Mapped[Session] = relationship(back_populates="decisions")
    lifecycle: Mapped[list[LifecycleEvent]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_decision_session_created", "session_id", "created_at"),
        CheckConstraint("revision >= 0", name="ck_decision_revision_nonnegative"),
    )


class PlanCandidate(Base):
    """Every candidate the planner produced, accepted or rejected.

    Rejected alternatives are retained so the inspector and counterfactual
    experiments have something to compare against.
    """

    __tablename__ = "plan_candidate"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("decision.id", ondelete="CASCADE"))
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    intention: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_plan_candidate_decision", "decision_id"),)


class LifecycleEvent(Base):
    """One audited recommendation status change."""

    __tablename__ = "lifecycle_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("decision.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    session_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_event_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    decision: Mapped[Decision] = relationship(back_populates="lifecycle")

    __table_args__ = (CheckConstraint("from_state <> to_state", name="ck_lifecycle_event_changes_state"),)


class ExecutionEventRow(Base):
    """Observed driver action. ``decision_id`` is nullable for an unsolicited action."""

    __tablename__ = "execution_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("decision.id", ondelete="SET NULL")
    )
    observed_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    start_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_execution_event_session", "session_id", "start_time_s"),)


class OutcomeRecordRow(Base):
    """Realised state at an evaluation checkpoint."""

    __tablename__ = "outcome_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("decision.id", ondelete="SET NULL")
    )
    checkpoint_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_outcome_record_session", "session_id", "checkpoint_id"),)


class TelemetryChunk(Base):
    """Index into a completed Parquet chunk. The bytes are not stored here."""

    __tablename__ = "telemetry_chunk"

    hash: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    car_id: Mapped[str | None] = mapped_column(String(40))
    channel_family: Mapped[str] = mapped_column(String(40), nullable=False)
    start_session_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_session_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_revision: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_telemetry_chunk_window", "session_id", "start_session_time_s"),
        CheckConstraint("end_session_time_s >= start_session_time_s", name="ck_telemetry_chunk_window"),
    )


class SnapshotRow(Base):
    """Reference to a complete simulator state capture."""

    __tablename__ = "simulation_snapshot"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    session_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # A replay is only reproducible against the geometry it was captured on, so
    # the replay handle carries the circuit identity of the session that made
    # it. Copied from the session row; nullable for a synthetic sketch.
    track_id: Mapped[str | None] = mapped_column(String(64))
    track_package_hash: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (Index("ix_snapshot_session", "session_id", "session_time_s"),)


class ExperimentJob(Base):
    """Batch job claimed through a database lease.

    Two workers must not publish separate successful reports for one job id,
    which is why the lease and its expiry live on the row itself.
    """

    __tablename__ = "experiment_job"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    worker_lease: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    report_hash: Mapped[str | None] = mapped_column(String(80))
    failure: Mapped[str | None] = mapped_column(Text)
    partial_results: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_experiment_job_scheduling", "status", "created_at"),
        CheckConstraint("progress >= 0 and progress <= 1", name="ck_experiment_job_progress_fraction"),
    )


class ModelBundle(Base):
    """Approval state of a frozen model bundle. Never defaults to approved."""

    __tablename__ = "model_bundle"

    hash: Mapped[str] = mapped_column(String(80), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unevaluated")
    approval_event_id: Mapped[str | None] = mapped_column(String(64))
    benchmark_report_hash: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("bundle_id", name="uq_model_bundle_id"),
        CheckConstraint(
            "approval_status in ('unevaluated','candidate','rejected','approved')",
            name="ck_model_bundle_approval_is_known",
        ),
    )


class RuleManifestRow(Base):
    """Immutable rule pack as loaded, keyed by its content hash."""

    __tablename__ = "rule_manifest"

    hash: Mapped[str] = mapped_column(String(80), primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(String(120), nullable=False)
    season_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ExportJob(Base):
    """Local export request. Paths are validated against the storage root."""

    __tablename__ = "export_job"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    path: Mapped[str | None] = mapped_column(Text)
    hashes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failure: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OutboxRecord(Base):
    """Transactional outbox.

    A row is written in the same transaction as the event it announces, so a
    crash between commit and WebSocket publish loses the notification but not
    the record. Delivery is at least once; consumers deduplicate on
    ``(session_id, sequence)``.
    """

    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_outbox_session_sequence"),
        Index("ix_outbox_unpublished", "published_at", "created_at"),
    )


ALL_TABLES = (
    Session,
    Manifest,
    SourceCapabilityRow,
    SessionEvent,
    OperatorCommand,
    ControlLease,
    Decision,
    PlanCandidate,
    LifecycleEvent,
    ExecutionEventRow,
    OutcomeRecordRow,
    TelemetryChunk,
    SnapshotRow,
    ExperimentJob,
    ModelBundle,
    RuleManifestRow,
    ExportJob,
    OutboxRecord,
)


__all__ = [
    "ALL_TABLES",
    "JSONB",
    "Base",
    "ControlLease",
    "Decision",
    "ExecutionEventRow",
    "ExperimentJob",
    "ExportJob",
    "LifecycleEvent",
    "Manifest",
    "ModelBundle",
    "OperatorCommand",
    "OutboxRecord",
    "OutcomeRecordRow",
    "PlanCandidate",
    "RuleManifestRow",
    "Session",
    "SessionEvent",
    "SnapshotRow",
    "SourceCapabilityRow",
    "TelemetryChunk",
    "utcnow",
]
