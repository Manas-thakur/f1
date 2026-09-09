"""Session runtime: the piece that closes the loop.

    simulator -> observation -> ingestion -> estimate -> rule context -> plan
      -> checked recommendation -> engineer selection -> simulated driver
      execution -> observed telemetry -> next decision

* :mod:`.observation_source` — the truth-isolation seam into A02's ingestion.
* :mod:`.runtime` — :class:`~.runtime.InProcessSessionRuntime`, a complete
  ``SessionRuntimePort`` with serialised mutations, a monotonic revision, a
  decision cutoff, simulated driver execution and expiry between ticks.
* :mod:`.baseline_planner` — the ``Planner`` protocol and a legal fixed-schedule
  baseline so the loop closes without A06.
* :mod:`.degradation` — every row of the ARCHITECTURE.md degradation table.
* :mod:`.recorder` / :mod:`.spool` — durable lifecycle writes, bounded spool.
* :mod:`.publisher` — transactional-outbox drain onto the stream hub.
* :mod:`.factory` — :class:`~.factory.SessionFactory`, what
  ``routes/sessions.py`` expects on ``app.state.session_factory``.
* :mod:`.circuit` — real-circuit identity: track package, event overlay and
  conditions tape resolved and hashed, with a named refusal for each.
"""

from __future__ import annotations

from .baseline_planner import (
    BASELINE_IDENTITY,
    BaselinePlanner,
    Planner,
    PlanRequest,
    checker_state_for,
)
from .circuit import (
    MINIMUM_READINESS,
    REAL_CIRCUIT_LABEL,
    CircuitIdentity,
    CircuitRefusal,
    describe_track,
    overlay_content_hash,
    resolve_conditions,
    resolve_event,
    resolve_track_package,
)
from .degradation import (
    RIVAL_ENERGY_QUANTILE_NOTE,
    DegradationFinding,
    DegradationInputs,
    DegradationReport,
    DegradationRow,
    ModelDecision,
    PersistenceStatus,
    TimeoutOutcome,
    assess,
    check_model_compatibility,
    solver_timeout_outcome,
)
from .factory import (
    ResolvedArtefacts,
    SessionFactory,
    SessionValidationError,
    build_manifest,
    resolve_artefacts,
    validate_combination,
)
from .observation_source import (
    SIMULATOR_SOURCE_ID,
    SimulatorObservationSource,
    TruthIsolationError,
    simulator_session_capability,
)
from .publisher import DeduplicatingConsumer, OutboxPublisher, PublisherFault, PublishReport
from .recorder import RecordOutcome, SessionRecorder
from .runtime import (
    MAX_DECISION_OBSERVATION_AGE_S,
    SYNTHETIC_GAP_THRESHOLD,
    UNRESOLVED_GAP_THRESHOLD,
    DecisionHealth,
    EligibilityPolicy,
    IngestionReport,
    InProcessSessionRuntime,
    PlanApplication,
    QueuedDriverInput,
    RuntimeConfig,
    SessionRuntimeError,
    default_planner,
    default_runtime_config,
)
from .spool import BoundedSpool, SpoolEntry, SpoolFull

__all__ = [
    "BASELINE_IDENTITY",
    "MAX_DECISION_OBSERVATION_AGE_S",
    "MINIMUM_READINESS",
    "REAL_CIRCUIT_LABEL",
    "RIVAL_ENERGY_QUANTILE_NOTE",
    "SIMULATOR_SOURCE_ID",
    "SYNTHETIC_GAP_THRESHOLD",
    "UNRESOLVED_GAP_THRESHOLD",
    "BaselinePlanner",
    "BoundedSpool",
    "CircuitIdentity",
    "CircuitRefusal",
    "DecisionHealth",
    "DeduplicatingConsumer",
    "DegradationFinding",
    "DegradationInputs",
    "DegradationReport",
    "DegradationRow",
    "EligibilityPolicy",
    "InProcessSessionRuntime",
    "IngestionReport",
    "ModelDecision",
    "OutboxPublisher",
    "PersistenceStatus",
    "PlanApplication",
    "PlanRequest",
    "Planner",
    "PublishReport",
    "PublisherFault",
    "QueuedDriverInput",
    "RecordOutcome",
    "ResolvedArtefacts",
    "RuntimeConfig",
    "SessionFactory",
    "SessionRecorder",
    "SessionRuntimeError",
    "SessionValidationError",
    "SimulatorObservationSource",
    "SpoolEntry",
    "SpoolFull",
    "TimeoutOutcome",
    "TruthIsolationError",
    "assess",
    "build_manifest",
    "check_model_compatibility",
    "checker_state_for",
    "default_planner",
    "default_runtime_config",
    "describe_track",
    "overlay_content_hash",
    "resolve_artefacts",
    "resolve_conditions",
    "resolve_event",
    "resolve_track_package",
    "simulator_session_capability",
    "solver_timeout_outcome",
    "validate_combination",
]
