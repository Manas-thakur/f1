"""Every outbox row must validate as a StreamEnvelope.

Found by A08 while writing the publisher. Two problems, both in the coordinator's
own persistence layer:

1. ``apply_operator_action`` wrote an outbox row with ``event_type`` of
   ``"operator_action"``, which is not a member of ``StreamEventType``. No
   client could validate it, so the publisher had to quarantine those rows and
   they accumulated forever.
2. ``store_decision`` and ``record_execution`` wrote payloads without the
   discriminator field the tagged union needs, so the publisher had to repair
   each payload before sending it.

Both were repaired downstream by the publisher, which is the wrong place: a row
that cannot be delivered should not be written. An undeliverable row is worse
than a missing one, because it looks durable while never reaching anybody.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from afterlap_api.db import (
    acquire_lease,
    apply_operator_action,
    body_hash_of,
    command_transaction,
    create_all,
    create_db_engine,
    create_session_factory,
    record_execution,
    store_decision,
    transaction,
)
from afterlap_api.db.models import OutboxRecord, Session, SessionEvent
from afterlap_contracts import ExecutionMatch, OperatorAction, StreamEventType
from afterlap_contracts import fixtures as fx
from afterlap_contracts.events import StreamEnvelope

SESSION_ID = fx.FIXTURE_SESSION_ID
OPERATOR = "engineer-1"


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'outbox.sqlite3').as_posix()}")
    create_all(engine)
    made = create_session_factory(engine)

    manifest = fx.session_manifest()
    with transaction(made) as db:
        db.add(
            Session(
                id=SESSION_ID,
                mode=manifest.mode.value,
                revision=0,
                manifest_hash=manifest.content_hash(),
                status="running",
                session_time_s=12.3,
                last_sequence=100,
                ruleset_hash=fx.FIXTURE_RULESET_HASH,
                synthetic=True,
            )
        )
    with transaction(made) as db:
        acquire_lease(db, session_id=SESSION_ID, operator_id=OPERATOR, session_time_s=10.0, ttl_s=120.0)
        store_decision(db, recommendation=fx.recommendation(), estimate=fx.state_estimate())
    return made


def _all_outbox(factory) -> list[OutboxRecord]:
    with transaction(factory) as db:
        return list(db.execute(select(OutboxRecord).order_by(OutboxRecord.sequence)).scalars())


def test_every_stored_outbox_row_validates_as_a_stream_envelope(factory):
    """The publisher must not have to repair anything."""
    body = {"action": "select", "expected_revision": 1, "operator_id": OPERATOR, "reason": None}
    with command_transaction(factory) as db:
        apply_operator_action(
            db,
            session_id=SESSION_ID,
            recommendation_id="rec-001",
            action=OperatorAction.SELECT,
            operator_id=OPERATOR,
            expected_revision=1,
            idempotency_key="k1",
            body_hash=body_hash_of(body),
            session_time_s=12.6,
            current_ruleset_hash=fx.FIXTURE_RULESET_HASH,
        )
    with transaction(factory) as db:
        record_execution(db, execution=fx.execution_event(), session_time_s=13.1)

    rows = _all_outbox(factory)
    assert rows, "the fixture should have produced publishable rows"

    for row in rows:
        # This is exactly what the publisher does. It must not raise.
        envelope = StreamEnvelope.model_validate(row.envelope)
        assert envelope.session_id == SESSION_ID
        assert envelope.sequence == row.sequence
        assert envelope.event_type.value == row.event_type


def test_no_outbox_row_carries_an_unknown_event_type(factory):
    body = {"action": "select", "expected_revision": 1, "operator_id": OPERATOR, "reason": None}
    with command_transaction(factory) as db:
        apply_operator_action(
            db,
            session_id=SESSION_ID,
            recommendation_id="rec-001",
            action=OperatorAction.SELECT,
            operator_id=OPERATOR,
            expected_revision=1,
            idempotency_key="k2",
            body_hash=body_hash_of(body),
            session_time_s=12.6,
            current_ruleset_hash=fx.FIXTURE_RULESET_HASH,
        )

    known = {member.value for member in StreamEventType}
    for row in _all_outbox(factory):
        assert row.event_type in known, (
            f"outbox row {row.id} carries event_type {row.event_type!r}, which no client "
            "can validate; it would be written, look durable, and never be delivered"
        )


def test_an_operator_action_is_still_recorded_in_the_durable_event_log(factory):
    """Not publishing it must not mean losing it.

    The action is audit evidence. It stays in ``session_event``; only the
    stream row is omitted, because the lifecycle change it caused is published
    as ``recommendation_updated``.
    """
    body = {"action": "select", "expected_revision": 1, "operator_id": OPERATOR, "reason": None}
    with command_transaction(factory) as db:
        apply_operator_action(
            db,
            session_id=SESSION_ID,
            recommendation_id="rec-001",
            action=OperatorAction.SELECT,
            operator_id=OPERATOR,
            expected_revision=1,
            idempotency_key="k3",
            body_hash=body_hash_of(body),
            session_time_s=12.6,
            current_ruleset_hash=fx.FIXTURE_RULESET_HASH,
        )

    with transaction(factory) as db:
        actions = list(
            db.execute(select(SessionEvent).where(SessionEvent.event_type == "operator_action")).scalars()
        )
    assert len(actions) == 1
    assert actions[0].payload["action"] == "select"
    assert actions[0].payload["operator_id"] == OPERATOR

    # And the lifecycle change that action caused *is* on the stream.
    published_types = {row.event_type for row in _all_outbox(factory)}
    assert StreamEventType.RECOMMENDATION_UPDATED.value in published_types


def test_execution_payload_round_trips_through_the_union(factory):
    with transaction(factory) as db:
        record_execution(
            db,
            execution=fx.execution_event(match=ExecutionMatch.MATCHED),
            session_time_s=13.1,
        )

    rows = [r for r in _all_outbox(factory) if r.event_type == StreamEventType.EXECUTION_OBSERVED.value]
    assert len(rows) == 1
    envelope = StreamEnvelope.model_validate(rows[0].envelope)
    assert envelope.payload.event_type is StreamEventType.EXECUTION_OBSERVED
    assert envelope.payload.execution.id == "exec-001"
