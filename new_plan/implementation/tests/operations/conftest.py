"""Fixtures for the operations drills.

Imported relatively (`from .conftest import ...`) per coordinator decision
D-03. Self-contained on purpose: `tests/` is not a Python package, so
`tests.backend.conftest` cannot be imported from here, and duplicating a small
session helper is better than a fragile path hack into another worker's suite.

Everything is synthetic: the scenario, the rule pack, the car and the track are
the repository's own invented fixtures, and no test in this package touches the
network, a measured dataset or a trained model.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

# `scripts/` is not a workspace member and is not installed, so the operations
# support package is imported by putting that directory on the path. Done once,
# here, rather than in every test module.
IMPLEMENTATION_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = IMPLEMENTATION_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from afterlap_api.db import acquire_lease, apply_operator_action, body_hash_of, create_all  # noqa: E402
from afterlap_api.db.engine import (  # noqa: E402
    command_transaction,
    create_db_engine,
    create_session_factory,
)
from afterlap_api.db.models import Manifest, Session  # noqa: E402
from afterlap_api.session import (  # noqa: E402
    BaselinePlanner,
    BoundedSpool,
    InProcessSessionRuntime,
    RuntimeConfig,
    SessionFactory,
    SessionRecorder,
)
from afterlap_contracts import (  # noqa: E402
    OperatorAction,
    Recommendation,
    RecommendationStatus,
    SessionManifest,
    SessionMode,
)
from afterlap_contracts.requests import CreateSessionRequest  # noqa: E402

SCENARIO_ID = "two-straight-counterattack"
RULE_PACK_ID = "synthetic-pack-v1"
OPERATOR = "console-operator"
SEED = 42

#: Advice only becomes legal once the detection line at 1600 m is crossed, a
#: little after t = 21 s from a standing start. The demo runbook observes the
#: first actionable instruction at t = 26 s.
DECISION_HORIZON_S = 45.0


# --------------------------------------------------------------------------- #
# database
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class LocalStore:
    """A real SQLite store on disk, so it can be genuinely broken."""

    path: Path
    engine: Engine
    factory: sessionmaker[OrmSession]
    backup: bytes | None = None

    @property
    def url(self) -> str:
        return f"sqlite+pysqlite:///{self.path.as_posix()}"

    def break_the_file(self) -> str:
        """Make the database genuinely unusable, and return what was done.

        Not an injected exception: the pool is disposed so the handles are
        released, the write-ahead log and shared-memory files are removed, and
        the main database file is overwritten with bytes that are not a SQLite
        image. The next connection therefore fails inside the driver with a
        real `sqlite3.DatabaseError: file is not a database`, which is what a
        corrupted or yanked volume looks like from the application's side.

        Disposing the pool closes the last connection, which checkpoints the
        write-ahead log into the main file; the backup taken at that moment is
        therefore complete, and :meth:`repair_the_file` puts the store back so
        a drill can prove what did and did not land during the outage.
        """
        self.engine.dispose()
        self.backup = self.path.read_bytes()
        removed = []
        for suffix in ("-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
                removed.append(sidecar.name)
        self.path.write_bytes(b"AFTERLAP operations drill: this is not a database.\n" * 64)
        return (
            f"disposed the pool, removed {removed or 'no sidecar files'}, and overwrote "
            f"{self.path.name} ({self.path.stat().st_size} B) with non-SQLite bytes"
        )

    def repair_the_file(self) -> None:
        """Put back the bytes captured when the file was broken."""
        if self.backup is None:
            raise AssertionError("repair_the_file called before break_the_file")
        self.engine.dispose()
        for suffix in ("-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        self.path.write_bytes(self.backup)


def open_store(root: Path, name: str = "session.sqlite3", *, migrate: bool = True) -> LocalStore:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    engine = create_db_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    if migrate:
        create_all(engine)
    return LocalStore(path=path, engine=engine, factory=create_session_factory(engine))


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    return open_store(tmp_path / "db")


@pytest.fixture
def db_factory(store: LocalStore) -> sessionmaker[OrmSession]:
    return store.factory


# --------------------------------------------------------------------------- #
# a driveable session
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class OperationalSession:
    """A started session plus the plumbing a drill needs to operate it."""

    manifest: SessionManifest
    runtime: InProcessSessionRuntime
    recorder: SessionRecorder | None
    factory: sessionmaker[OrmSession]
    spool: BoundedSpool | None = None
    ticks: list[Any] = field(default_factory=list)

    @property
    def session_id(self) -> str:
        return self.manifest.id

    def sync(self) -> None:
        """Mirror the runtime clock and revision onto the session row.

        `routes/sessions.py` does this after every `step` command and the
        lifecycle guards read `session_time_s` from the row, so a drill that
        drives the runtime directly has to keep the two in step. A failure here
        is swallowed on purpose: several drills break the database deliberately
        and still need to keep advancing the runtime.
        """
        try:
            with command_transaction(self.factory) as db:
                row = db.get(Session, self.session_id)
                if row is None:
                    return
                row.session_time_s = self.runtime.session_time_s
                row.revision = self.runtime.revision
        except Exception:
            return

    def advance(self, duration_s: float = 1.0):  # type: ignore[no-untyped-def]
        tick = self.runtime.advance(duration_s)
        self.ticks.append(tick)
        self.sync()
        return tick

    def advance_until(self, predicate, *, limit_s: float = DECISION_HORIZON_S, step_s: float = 1.0):  # type: ignore[no-untyped-def]
        elapsed = 0.0
        while elapsed < limit_s:
            tick = self.advance(step_s)
            elapsed += step_s
            if predicate(tick):
                return tick
        raise AssertionError(f"the runtime did not satisfy the predicate within {limit_s} s of session time")

    def take_lease(self, operator_id: str = OPERATOR) -> None:
        with command_transaction(self.factory) as db:
            acquire_lease(
                db,
                session_id=self.session_id,
                operator_id=operator_id,
                session_time_s=self.runtime.session_time_s,
                ttl_s=3600.0,
            )

    def act(
        self,
        recommendation: Recommendation,
        action: OperatorAction,
        *,
        idempotency_key: str,
        operator_id: str = OPERATOR,
        reason: str | None = None,
    ):  # type: ignore[no-untyped-def]
        body = {
            "action": action.value,
            "expected_revision": recommendation.revision,
            "operator_id": operator_id,
            "reason": reason,
        }
        with command_transaction(self.factory) as db:
            row = db.get(Session, self.session_id)
            assert row is not None
            return apply_operator_action(
                db,
                session_id=self.session_id,
                recommendation_id=recommendation.id,
                action=action,
                operator_id=operator_id,
                expected_revision=recommendation.revision,
                idempotency_key=idempotency_key,
                body_hash=body_hash_of(body),
                session_time_s=row.session_time_s,
                current_ruleset_hash=row.ruleset_hash,
                reason=reason,
            )

    def status_of(self, recommendation_id: str) -> RecommendationStatus:
        from afterlap_api.db.models import Decision

        with command_transaction(self.factory) as db:
            row = db.get(Decision, recommendation_id)
            assert row is not None, f"decision {recommendation_id} was never persisted"
            return RecommendationStatus(row.status)

    def decision_ids(self) -> list[str]:
        from afterlap_api.db.models import Decision

        with command_transaction(self.factory) as db:
            rows = (
                db.query(Decision).filter_by(session_id=self.session_id).order_by(Decision.created_at).all()
            )
            return [row.id for row in rows]


def start_session(
    factory: sessionmaker[OrmSession],
    *,
    scenario_id: str = SCENARIO_ID,
    ruleset_id: str = RULE_PACK_ID,
    seed: int = SEED,
    spool_root: Path | None = None,
    spool_capacity: int = 32,
    config: RuntimeConfig | None = None,
    with_recorder: bool = True,
) -> OperationalSession:
    """Create a session, persist its row, and return everything a drill needs."""
    spool: BoundedSpool | None = None
    holder: dict[str, SessionRecorder] = {}

    def make_recorder(session_id: str) -> SessionRecorder:
        nonlocal spool
        if spool_root is not None:
            spool = BoundedSpool(spool_root, session_id, capacity=spool_capacity)
        recorder = SessionRecorder(factory, session_id=session_id, spool=spool)
        holder["recorder"] = recorder
        return recorder

    session_factory = SessionFactory(
        planner=BaselinePlanner(),
        recorder_factory=make_recorder if with_recorder else None,
        config=config,
    )
    manifest, runtime = session_factory.create(
        CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id=scenario_id,
            ruleset_id=ruleset_id,
            seed=seed,
            label="operations drill",
        )
    )
    _persist_session_row(factory, manifest)
    return OperationalSession(
        manifest=manifest,
        runtime=runtime,
        recorder=holder.get("recorder"),
        factory=factory,
        spool=spool,
    )


def _persist_session_row(factory: sessionmaker[OrmSession], manifest: SessionManifest) -> None:
    with command_transaction(factory) as db:
        db.add(
            Manifest(
                hash=manifest.content_hash(),
                kind="session",
                schema_version=manifest.schema_version,
                payload=manifest.model_dump(mode="json"),
            )
        )
        db.add(
            Session(
                id=manifest.id,
                mode=manifest.mode.value,
                revision=0,
                manifest_hash=manifest.content_hash(),
                status="running",
                session_time_s=0.0,
                last_sequence=0,
                scenario_id=manifest.scenario_id,
                ruleset_hash=manifest.ruleset_hash,
                model_hash=manifest.model_hash,
                synthetic=manifest.synthetic,
                label=manifest.label,
            )
        )


def actionable(tick) -> bool:  # type: ignore[no-untyped-def]
    """True once the runtime has published a checked, actionable recommendation."""
    from afterlap_contracts import ActionCode, CheckStatus

    recommendation = tick.recommendation
    return (
        recommendation is not None
        and recommendation.action_code is not ActionCode.WITHDRAW_ADVICE
        and recommendation.constraint_result.status is CheckStatus.PASS
    )


# --------------------------------------------------------------------------- #
# filesystem
# --------------------------------------------------------------------------- #


def write_filler(path: Path, total_bytes: int, *, chunk: int = 256 * 1024) -> int:
    """Write `total_bytes` of real bytes to `path`. Returns the size on disk.

    Real bytes, not a sparse file: `os.walk` + `stat` is what the quota guard
    measures, and a sparse file would report a size the filesystem has not
    actually committed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    block = b"\xa5" * chunk
    written = 0
    with path.open("wb") as handle:
        while written < total_bytes:
            take = min(chunk, total_bytes - written)
            handle.write(block[:take])
            written += take
        handle.flush()
        os.fsync(handle.fileno())
    return path.stat().st_size


def tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


__all__ = [
    "DECISION_HORIZON_S",
    "IMPLEMENTATION_ROOT",
    "OPERATOR",
    "RULE_PACK_ID",
    "SCENARIO_ID",
    "SCRIPTS_DIR",
    "SEED",
    "LocalStore",
    "OperationalSession",
    "actionable",
    "open_store",
    "start_session",
    "tree_bytes",
    "write_filler",
]
