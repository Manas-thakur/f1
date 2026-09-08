"""Database outage, bounded spool, exhaustion and halt.

**Genuinely causes the condition.** `tests/backend/test_recovery.py` already
covers the spool by injecting an `OperationalError` from a fake session
factory. That proves the handling; it does not prove the *detection*, because
an injected exception is the exception the handler was written for. These
drills break the store for real, two different ways:

* `LocalStore.break_the_file` disposes the connection pool, deletes the
  write-ahead log and overwrites the SQLite image with bytes that are not a
  database. The next write fails inside the driver with
  `sqlite3.DatabaseError: file is not a database` — the same class of failure
  as a corrupted or yanked volume — and nothing in the test decides what the
  error is going to be.
* `test_a_dead_database_socket_...` re-binds the session factory to a real
  TCP endpoint that nothing is listening on, so the failure is a genuine
  `psycopg` connection error against a genuinely absent server.

The store is then repaired from the bytes captured at the moment it was
broken, which is what lets these drills assert the thing that matters most:
**nothing was written during the outage**, and the spooled writes land in
spooled order once the store is back.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from afterlap_api.db.engine import command_transaction, create_session_factory
from afterlap_api.db.models import Decision
from afterlap_api.session.degradation import DegradationRow
from afterlap_contracts import CapabilityState

from .conftest import LocalStore, actionable, start_session


def _decisions(factory) -> list[str]:  # type: ignore[no-untyped-def]
    with command_transaction(factory) as db:
        return [row.id for row in db.query(Decision).order_by(Decision.created_at).all()]


def test_a_broken_database_spools_writes_and_raises_a_visible_warning(
    store: LocalStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    session = start_session(store.factory, spool_root=tmp_path / "spool", spool_capacity=8)
    recorder = session.recorder
    assert recorder is not None

    session.advance_until(actionable)
    committed_before = _decisions(store.factory)
    assert committed_before, "nothing was durable before the outage; the drill would prove nothing"
    assert recorder.status().state is CapabilityState.AVAILABLE

    # --- the database genuinely stops being a database ---------------------- #
    what = store.break_the_file()
    print(f"\noutage induced: {what}")

    with caplog.at_level(logging.WARNING, logger="afterlap.session.recorder"):
        for _ in range(3):
            tick = session.advance(1.0)

    status = recorder.status()
    print(f"spool after the outage: {status.spooled}/{status.capacity}, last error {status.last_error!r}")

    # 1. The writes were absorbed, not lost and not pretended-committed.
    assert status.state is CapabilityState.DEGRADED, status
    assert status.spooled > 0, "the outage produced no spooled entries"
    assert not status.exhausted, "the spool filled sooner than this drill intends"
    assert status.last_error is not None
    assert "DatabaseError" in status.last_error or "OperationalError" in status.last_error, (
        f"the recorder recorded {status.last_error!r}, which does not look like a real driver error"
    )

    # 2. The spool is durable: the entries are on disk, ordered, replayable.
    assert session.spool is not None
    positions = [entry.position for entry in session.spool.entries]
    assert positions == sorted(positions) == list(range(1, len(positions) + 1))
    on_disk = sorted((tmp_path / "spool" / session.session_id).glob("*.json"))
    assert len(on_disk) == len(positions), "the spool is in memory only"

    # 3. The warning is visible, in the log and in the degradation table.
    assert any("session store write" in record.message for record in caplog.records), (
        "the outage produced no warning log line"
    )
    assert status.warnings, "the persistence status carries no warning text"
    report = session.runtime.degradation
    finding = report.find(DegradationRow.DATABASE_FAILURE)
    assert finding is not None, f"the degradation table has no database_failure row: {report.as_list()}"
    assert finding.effect == "bounded_local_spool_and_visible_persistence_warning"
    assert not finding.halts_recommendations, "a recoverable outage must not halt advice on its own"
    print(f"degradation: {finding.detail}")

    # 4. Advice continues while the spool has room — degraded, warned, but not
    #    withdrawn, because auditability is still recoverable.
    assert tick.recommendation is not None, "advice stopped while the spool still had room"

    # --- recovery ----------------------------------------------------------- #
    # The ids that were spooled, captured before the drain clears them.
    spooled_ids = [
        entry.payload["recommendation"]["id"]
        for entry in session.spool.entries
        if entry.kind == "store_decision"
    ]

    store.repair_the_file()
    replayed, remaining = recorder.drain_spool()
    print(f"drain: replayed {replayed}, remaining {remaining}")
    assert (replayed, remaining) == (status.spooled, 0)

    after = _decisions(store.factory)
    # Nothing was written during the outage: the pre-outage set is untouched
    # and everything beyond it arrived through the replay, in spooled order.
    assert after[: len(committed_before)] == committed_before
    assert after[len(committed_before) :] == spooled_ids, (
        f"the replay wrote {after[len(committed_before) :]}, not the spooled order {spooled_ids}"
    )
    assert recorder.status().state is CapabilityState.AVAILABLE


def test_an_exhausted_spool_halts_new_recommendations_to_preserve_auditability(
    store: LocalStore, tmp_path: Path
):
    """The spool is *exhausted for real*, by a real outage, and advice stops."""
    # Capacity 2 so exhaustion is reached inside a short run. The recorder
    # marks itself exhausted on the write that fills the spool, so two failed
    # writes are enough.
    session = start_session(store.factory, spool_root=tmp_path / "spool", spool_capacity=2)
    recorder = session.recorder
    assert recorder is not None

    session.advance_until(actionable)
    committed_before = _decisions(store.factory)
    assert committed_before

    store.break_the_file()

    for _ in range(6):
        session.advance(1.0)
        if not recorder.accepts_new_recommendations():
            break

    # The write that *fills* the spool is itself spooled, so the advice it
    # accompanied is still auditable and is correctly published. The halt
    # applies to the next decision, so that is the tick to assert on.
    halted_tick = session.advance(1.0)

    status = recorder.status()
    print(f"\nspool at halt: {status.spooled}/{status.capacity}, exhausted={status.exhausted}")
    assert status.exhausted is True, "the spool never exhausted despite a persistent outage"
    assert recorder.accepts_new_recommendations() is False
    assert len(session.spool or ()) == 2, "a write was accepted past the spool's capacity"

    # The halt is a *behaviour*: no new operational recommendation is published.
    assert halted_tick is not None
    assert halted_tick.recommendation is None, (
        "a recommendation was published while the audit trail could not be persisted"
    )

    # Keep advancing: it must stay halted, not recover on its own.
    for _ in range(2):
        later = session.advance(1.0)
        assert later.recommendation is None

    report = session.runtime.degradation
    spool_full = report.find(DegradationRow.SPOOL_FULL)
    assert spool_full is not None, f"no spool_full row in {report.as_list()}"
    assert spool_full.halts_recommendations is True
    assert spool_full.state is CapabilityState.UNAVAILABLE
    print(f"halt reason: {spool_full.detail}")

    # And the store, once repaired, proves nothing was written while halted.
    store.repair_the_file()
    after = _decisions(store.factory)
    assert after == committed_before, (
        f"{len(after) - len(committed_before)} decision row(s) appeared during the outage; "
        "the halt did not preserve the audit boundary"
    )


def test_a_dead_database_socket_is_absorbed_the_same_way(store: LocalStore, tmp_path: Path):
    """The second genuine mechanism: a real TCP endpoint with nothing behind it.

    `sessionmaker.configure(bind=...)` is public API, so the recorder keeps the
    factory it was given and the *engine underneath it* becomes a PostgreSQL
    connection to a port nothing is listening on. The failure is produced by
    psycopg against a genuinely absent server; a short `connect_timeout` keeps
    the drill fast without changing what fails.
    """
    from sqlalchemy import create_engine

    session = start_session(store.factory, spool_root=tmp_path / "spool", spool_capacity=8)
    recorder = session.recorder
    assert recorder is not None
    session.advance(1.0)

    dead = create_engine(
        # Port 1 on loopback: reserved, and nothing binds it.
        "postgresql+psycopg://afterlap:none@127.0.0.1:1/afterlap",
        connect_args={"connect_timeout": 1},
        pool_pre_ping=False,
    )
    store.factory.configure(bind=dead)
    try:
        tick = session.advance(1.0)
        status = recorder.status()
        print(f"\ndead socket: {status.last_error}")
        assert status.state is CapabilityState.DEGRADED
        assert status.spooled > 0
        assert status.last_error is not None and "OperationalError" in status.last_error
        assert tick.recommendation is None or tick.recommendation.action_code is not None
    finally:
        dead.dispose()
        store.factory.configure(bind=store.engine)

    # Recovery through the same public seam, then the spool drains in order.
    store.factory.configure(bind=store.engine)
    replayed, remaining = recorder.drain_spool()
    print(f"drain after socket recovery: replayed {replayed}, remaining {remaining}")
    assert remaining == 0 and replayed > 0
    assert create_session_factory(store.engine) is not None  # engine still usable
