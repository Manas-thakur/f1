"""Fixtures for the backend suite.

Imported relatively (``from .conftest import ...``) per coordinator decision
D-03. Everything here is synthetic: the scenario, the rule pack and the car are
the repository's own invented fixtures, and nothing in this suite is measured
telemetry or a validated model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from afterlap_api.db import acquire_lease, apply_operator_action, body_hash_of, create_all
from afterlap_api.db.engine import command_transaction, create_db_engine, create_session_factory
from afterlap_api.db.models import Manifest, Session
from afterlap_api.session import (
    BaselinePlanner,
    BoundedSpool,
    InProcessSessionRuntime,
    Planner,
    RuntimeConfig,
    SessionFactory,
    SessionRecorder,
)
from afterlap_api.stream import StreamHub
from afterlap_contracts import (
    OperatorAction,
    Recommendation,
    RecommendationStatus,
    SessionManifest,
    SessionMode,
)
from afterlap_contracts.requests import CreateSessionRequest

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session as OrmSession, sessionmaker

SCENARIO_ID = "two-straight-counterattack"
NO_ENERGY_SCENARIO_ID = "loop-no-energy-channel"
RULE_PACK_ID = "synthetic-pack-v1"
STRICT_RULE_PACK_ID = "synthetic-pack-v2-strict"
UNKNOWN_RULE_PACK_ID = "synthetic-pack-unknown"
OPERATOR = "engineer-test"
SEED = 42

DECISION_HORIZON_S = 40.0


@pytest.fixture
def db_factory(tmp_path: Path) -> sessionmaker[OrmSession]:
    engine = create_db_engine(f"sqlite+pysqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def hub() -> StreamHub:
    return StreamHub(buffer_size=64, client_queue=8)


@dataclass(slots=True)
class SessionUnderTest:
    """A started session plus the plumbing a test needs to drive it."""

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
        """Mirror the runtime's clock and revision onto the session row.

        ``routes/sessions.py`` does exactly this after a ``step`` command; the
        lifecycle guards read ``session_time_s`` from the row, so a test that
        drives the runtime directly has to keep the two in step.
        """
        with command_transaction(self.factory) as db:
            row = db.get(Session, self.session_id)
            assert row is not None
            row.session_time_s = self.runtime.session_time_s
            row.revision = self.runtime.revision

    def advance(self, duration_s: float = 1.0):  # type: ignore[no-untyped-def]
        tick = self.runtime.advance(duration_s)
        self.ticks.append(tick)
        self.sync()
        return tick

    def advance_until(self, predicate, *, limit_s: float = DECISION_HORIZON_S, step_s: float = 1.0):  # type: ignore[no-untyped-def]
        """Advance one decision interval at a time until ``predicate(tick)``."""
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
        expected_revision: int | None = None,
        reason: str | None = None,
    ):  # type: ignore[no-untyped-def]
        """Run one operator action through the coordinator's atomic sequence."""
        body = {
            "action": action.value,
            "expected_revision": (
                recommendation.revision if expected_revision is None else expected_revision
            ),
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
                expected_revision=int(body["expected_revision"]),
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


def start_session(
    factory: sessionmaker[OrmSession],
    *,
    scenario_id: str = SCENARIO_ID,
    ruleset_id: str = RULE_PACK_ID,
    seed: int = SEED,
    spool_root: Path | None = None,
    spool_capacity: int = 32,
    planner: Planner | None = None,
    config: RuntimeConfig | None = None,
    with_recorder: bool = True,
) -> SessionUnderTest:
    """Create a session, persist its row, and return everything a test needs."""
    spool: BoundedSpool | None = None
    recorder_holder: dict[str, SessionRecorder] = {}

    def make_recorder(session_id: str) -> SessionRecorder:
        nonlocal spool
        if spool_root is not None:
            spool = BoundedSpool(spool_root, session_id, capacity=spool_capacity)
        recorder = SessionRecorder(factory, session_id=session_id, spool=spool)
        recorder_holder["recorder"] = recorder
        return recorder

    session_factory = SessionFactory(
        planner=planner or BaselinePlanner(),
        recorder_factory=make_recorder if with_recorder else None,
        config=config,
    )
    manifest, runtime = session_factory.create(
        CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id=scenario_id,
            ruleset_id=ruleset_id,
            seed=seed,
            label="backend suite",
        )
    )
    _persist_session_row(factory, manifest)
    return SessionUnderTest(
        manifest=manifest,
        runtime=runtime,
        recorder=recorder_holder.get("recorder"),
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


__all__ = [
    "DECISION_HORIZON_S",
    "NO_ENERGY_SCENARIO_ID",
    "OPERATOR",
    "RULE_PACK_ID",
    "SCENARIO_ID",
    "SEED",
    "STRICT_RULE_PACK_ID",
    "UNKNOWN_RULE_PACK_ID",
    "SessionUnderTest",
    "actionable",
    "start_session",
]
