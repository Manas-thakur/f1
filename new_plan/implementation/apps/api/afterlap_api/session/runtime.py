"""The session runtime: one process, one session, one serialised state machine.

    simulator step -> observation -> ingestion -> estimate (at a cutoff)
      -> rule context -> plan -> independent check -> published recommendation
      -> engineer selection -> queued deliberate driver input
      -> ExecutionEvent, later -> observed telemetry -> next decision

Everything that mutates the session goes through one lock. The runtime owns a
monotonic ``revision``; every plan request is stamped with the revision it was
issued against and a completed result whose revision no longer matches is
**discarded**, never applied. That is the rule that stops a slow solve for a
superseded state from overwriting a newer invalidation.

Time discipline
---------------
``cutoff_s`` is the newest observation session time that actually reached the
estimator. Nothing later than it contributes: ingestion is finalised at the
cutoff when a decision is published (A02), and estimation rejects post-cutoff
observations itself. ``created_at_s`` is the session time the estimate was
published at, and is always at or after the cutoff.

Driver execution
----------------
Selection is not execution and communication is not execution. A deliberate
simulator driver input is *queued* with the scenario's configured driver
reaction delay and only becomes an :class:`ExecutionEvent` when that delay has
elapsed in session time — a separate, later event with its own sequence. The
simulator then applies its own physical actuation lag on top; the runtime models
the human leg, the simulator models the mechanical one.

Truth isolation
---------------
The runtime holds the simulator, so it can see truth. Nothing it publishes is
built from truth: the only path into the controller is
``Simulator.observe`` -> :class:`SimulatorObservationSource` -> A02's
``SimulatorAdapter`` -> ingestion -> estimation. ``WorldState`` is never
serialised into a contract object.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CandidatePlan,
    CheckpointDefinition,
    CheckStatus,
    ConstraintResult,
    DeploymentProfile,
    EligibilityState,
    ExecutionEvent,
    ExecutionMatch,
    ModelManifest,
    OutcomeRecord,
    PlanningResult,
    PlanningStatus,
    Provenance,
    ReasonCode,
    Recommendation,
    RecommendationStatus,
    RuleContext,
    SessionManifest,
    SessionMode,
    StateEstimate,
    TelemetryEvent,
    Trigger,
)
from afterlap_core.data import (
    IngestionPipeline,
    MemorySink,
    NormalisedRecord,
    SimulatorAdapter,
    SourcePipelineConfig,
    simulator_mapping,
)
from afterlap_core.estimation import EstimationContext, EstimatorState, create_state, update
from afterlap_core.rules import (
    CarState,
    EligibilityMachine,
    RulePack,
    check_plan,
    resolve_pack_context,
)
from afterlap_core.simulation import DriverAction, ScenarioBundle, Simulator, capture_complete_state
from afterlap_core.simulation.branching import snapshot_hash
from afterlap_core.timebase import ClockMapping

from ..runtime.port import RuntimeTick
from .baseline_planner import (
    BASELINE_IDENTITY,
    BaselinePlanner,
    Planner,
    PlanRequest,
    checker_state_for,
)
from .degradation import (
    DegradationInputs,
    DegradationReport,
    ModelDecision,
    PersistenceStatus,
    assess,
    check_model_compatibility,
    conservative_energy_floor_j,
    solver_timeout_outcome,
)
from .observation_source import (
    SimulatorObservationSource,
    relational_channels_for,
    simulator_session_capability,
)
from .recorder import SessionRecorder, new_outcome_id

logger = logging.getLogger("afterlap.session.runtime")

SNAPSHOT_SCHEMA = "afterlap.session.runtime.snapshot/1"


class SessionRuntimeError(RuntimeError):
    """The runtime was asked for something its current state cannot provide."""


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    """The sporting gap condition evaluated at the detection line.

    ``gap_threshold_s`` is **not** transcribed from any regulation. The shipped
    packs declare detection and activation line positions but no gap threshold,
    so a session must state which threshold it is using and where it came from.
    ``None`` means unresolved, and the eligibility machine then reports
    ``UNKNOWN`` rather than assuming a permission — which is the correct
    behaviour, and it does suppress advice.
    """

    gap_threshold_s: float | None
    provenance: str
    note: str


SYNTHETIC_GAP_THRESHOLD = EligibilityPolicy(
    gap_threshold_s=1.0,
    provenance="synthetic_assumption",
    note=(
        "Invented operational threshold for the synthetic packs: a rival ahead within 1.0 s at the "
        "detection line satisfies the gap condition. No FIA document was resolved for this value."
    ),
)

UNRESOLVED_GAP_THRESHOLD = EligibilityPolicy(
    gap_threshold_s=None,
    provenance="unresolved",
    note="The applicable gap threshold could not be resolved, so no overtake permission is asserted.",
)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Cadences, windows and horizons for one session."""

    dt_s: float = 0.02
    observation_rate_hz: float = 20.0
    decision_interval_s: float = 1.0
    planner_deadline_s: float = 0.2
    recommendation_validity_s: float = 4.0
    driver_reaction_delay_s: float = 0.35
    reorder_window_s: float = 0.0
    segment_length_m: float = 600.0
    lead_time_s: float = 1.2
    execution_window_s: float = 1.5
    eligibility: EligibilityPolicy = SYNTHETIC_GAP_THRESHOLD
    checkpoint_horizon_s: float = 30.0

    def __post_init__(self) -> None:
        if self.dt_s <= 0.0 or self.decision_interval_s <= 0.0:
            raise ValueError("dt and the decision interval must be positive")
        if self.observation_rate_hz <= 0.0:
            raise ValueError("the observation rate must be positive")


@dataclass(frozen=True, slots=True)
class QueuedDriverInput:
    """A deliberate simulator driver input waiting out the reaction delay."""

    id: str
    profile_id: DeploymentProfile
    recommendation_id: str | None
    issued_at_s: float
    apply_at_s: float
    communicated_at_s: float | None = None

    @property
    def delay_s(self) -> float:
        return self.apply_at_s - self.issued_at_s


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """What reached the estimator for one decision, and when it was observed."""

    cutoff_s: float
    events: tuple[TelemetryEvent, ...] = ()
    event_times_s: dict[str, float] = field(default_factory=dict)
    excluded_from_finalised: int = 0
    skipped_missing_observations: int = 0

    @property
    def newest_event_time_s(self) -> float | None:
        return max(self.event_times_s.values(), default=None)


@dataclass(frozen=True, slots=True)
class PlanApplication:
    """Outcome of offering a planning result back to the runtime."""

    applied: bool
    reason: str
    issued_revision: int
    current_revision: int

    @property
    def discarded(self) -> bool:
        return not self.applied


class InProcessSessionRuntime:
    """A complete :class:`~afterlap_api.runtime.port.SessionRuntimePort`."""

    def __init__(
        self,
        *,
        bundle: ScenarioBundle,
        pack: RulePack,
        planner: Planner | None = None,
        config: RuntimeConfig | None = None,
        recorder: SessionRecorder | None = None,
        model_bundle: ModelManifest | None = None,
        objective_version: str = "objective-v1",
        expected_feature_hash: str | None = None,
    ) -> None:
        self._bundle = bundle
        self._pack = pack
        self._planner: Planner = planner or BaselinePlanner()
        self._config = config or default_runtime_config(bundle)
        self._recorder = recorder
        self._model_bundle = model_bundle
        self._objective_version = objective_version
        self._expected_feature_hash = expected_feature_hash

        self._lock = threading.RLock()
        self._manifest: SessionManifest | None = None
        self._simulator: Simulator | None = None
        self._source: SimulatorObservationSource | None = None
        self._adapter: SimulatorAdapter | None = None
        self._pipeline: IngestionPipeline | None = None
        self._sink: MemorySink | None = None
        self._estimator: EstimatorState | None = None
        self._eligibility: EligibilityMachine | None = None

        self._revision = 0
        self._stopped = False
        self._paused = False
        self._next_decision_s = 0.0
        self._next_observation_s = 0.0
        self._pending_events: list[TelemetryEvent] = []
        self._event_times: dict[str, float] = {}
        self._queued_inputs: list[QueuedDriverInput] = []
        self._executions: list[ExecutionEvent] = []
        self._communicated_at_s: dict[str, float] = {}
        self._recommendations: dict[str, Recommendation] = {}
        self._acknowledged_inputs: set[str] = set()
        self._checkpoints_seen: set[tuple[str, int]] = set()
        self._outcomes: list[OutcomeRecord] = []
        self._sequence = 0
        self._eligibility_clamps = 0
        self._last_progress_m = 0.0
        self._last_eligibility_time_s = 0.0

        self._last_tick: RuntimeTick | None = None
        self._last_estimate: StateEstimate | None = None
        self._last_rule_context: RuleContext | None = None
        self._last_planning: PlanningResult | None = None
        self._last_recommendation: Recommendation | None = None
        self._last_accepted_plan: CandidatePlan | None = None
        self._last_ingestion: IngestionReport | None = None
        self._last_degradation = DegradationReport()
        self._model_decision: ModelDecision | None = None
        self._plan_durations_ms: list[float] = []
        self._decision_durations_ms: list[float] = []

    # ------------------------------------------------------------------ #
    # SessionRuntimePort
    # ------------------------------------------------------------------ #

    def initialise(self, manifest: SessionManifest, scenario_id: str, seed: int) -> RuntimeTick:
        with self._lock:
            if manifest.mode is not SessionMode.SIMULATION:
                raise SessionRuntimeError(
                    f"the in-process runtime drives a simulator; session mode is {manifest.mode.value}"
                )
            if scenario_id != self._bundle.scenario.id:
                raise SessionRuntimeError(
                    f"runtime was built for scenario {self._bundle.scenario.id!r}, "
                    f"asked to initialise {scenario_id!r}"
                )
            self._manifest = manifest
            simulator = Simulator()
            simulator.reset(self._bundle, seed=seed)
            self._simulator = simulator

            observation = self._bundle.scenario.observation
            capability = simulator_session_capability(
                energy_channel_available=observation.energy_channel_available,
                rate_hz=self._config.observation_rate_hz,
                relational_channels=relational_channels_for(self._bundle),
                observation_delay_s=float(observation.delay_s.value),
            )
            self._source = SimulatorObservationSource(
                ego_car_id=self._bundle.scenario.ego_car_id,
                rival_car_ids=self._bundle.scenario.rival_ids,
                capability=capability,
            )
            self._adapter = SimulatorAdapter(self._source, capability=capability)
            self._adapter.open(manifest)
            self._sink = MemorySink()
            self._pipeline = IngestionPipeline(
                SourcePipelineConfig(
                    session_id=manifest.id,
                    source_id=self._source.source_id,
                    mapping=simulator_mapping(self._source.source_id),
                    capability=capability,
                    provenance=Provenance.SIMULATED,
                    clock=ClockMapping(source_id=self._source.source_id, offset_s=0.0),
                    reorder_window_s=self._config.reorder_window_s,
                ),
                sink=self._sink,
            )
            self._estimator = create_state(
                session_id=manifest.id,
                car_id=self._bundle.scenario.ego_car_id,
                seed=seed,
            )
            self._eligibility = _eligibility_machine(self._pack, self._bundle.track.length)
            self._model_decision = check_model_compatibility(
                requested_model_hash=manifest.model_hash,
                bundle=self._model_bundle,
                expected_feature_hash=self._expected_feature_hash,
                expected_rule_family=self._pack.manifest.ruleset_id,
                expected_reward_revision=self._objective_version,
                baseline_identity=BASELINE_IDENTITY,
                scenario_family=self._bundle.scenario.id,
            )

            self._revision = 1
            self._stopped = False
            self._paused = False
            self._next_decision_s = 0.0
            self._next_observation_s = 0.0
            self._last_progress_m = 0.0
            self._last_eligibility_time_s = 0.0
            self._last_tick = self._tick(executions=())
            return self._last_tick

    def advance(self, duration_s: float) -> RuntimeTick:
        with self._lock:
            self._require_running()
            if duration_s <= 0.0:
                raise ValueError("advance needs a positive duration")
            if self._paused:
                # A paused session does not integrate. The caller gets the state
                # it already had rather than a fabricated forward step.
                return self._last_tick or self._tick(executions=())

            simulator = self._require_simulator()
            target_s = simulator.session_time_s + duration_s
            produced: list[ExecutionEvent] = []

            while simulator.session_time_s < target_s - 1e-12:
                step_s = min(self._config.dt_s, target_s - simulator.session_time_s)
                actions = self._release_driver_inputs(simulator.session_time_s + step_s, produced)
                simulator.step(actions, step_s)
                self._collect_observations()

            self._revision += 1
            self._ingest_pending()
            if simulator.session_time_s + 1e-9 >= self._next_decision_s:
                self._next_decision_s += self._config.decision_interval_s
                self._decide()

            self._record_checkpoint_outcomes()
            self._last_tick = self._tick(executions=tuple(produced))
            return self._last_tick

    def pause(self) -> None:
        with self._lock:
            self._require_running()
            self._paused = True
            self._revision += 1

    def resume(self) -> None:
        with self._lock:
            self._require_running()
            self._paused = False
            self._revision += 1

    def apply_driver_action(
        self,
        profile_id: DeploymentProfile,
        observed_at_s: float,
        recommendation_id: str | None,
    ) -> ExecutionEvent:
        """Queue a deliberate driver input and advance until it lands.

        The port needs a synchronous ``ExecutionEvent``, so this convenience
        advances the session by exactly the configured reaction delay. The event
        it returns is still a *later* event than the command: its
        ``start_time_s`` is the moment the driver acted, never the moment the
        engineer pressed the button. Callers driving the loop themselves should
        use :meth:`queue_driver_input` and read the execution off the next tick.
        """
        with self._lock:
            queued = self.queue_driver_input(
                profile_id, recommendation_id=recommendation_id, issued_at_s=observed_at_s
            )
            simulator = self._require_simulator()
            remaining = queued.apply_at_s - simulator.session_time_s
            tick = self.advance(max(remaining, self._config.dt_s))
            for execution in tick.executions:
                if execution.id == _execution_id(queued.id):
                    return execution
            raise SessionRuntimeError(
                f"the queued driver input {queued.id} did not land within its reaction delay"
            )

    def snapshot(self, label: str | None = None) -> tuple[str, dict[str, Any]]:
        with self._lock:
            simulator = self._require_simulator()
            simulation = capture_complete_state(simulator)
            payload: dict[str, Any] = {
                "schema": SNAPSHOT_SCHEMA,
                "label": label,
                "session_id": self._require_manifest().id,
                "revision": self._revision,
                "session_time_s": simulator.session_time_s,
                "simulation": simulation,
                "estimator": self._require_estimator().snapshot(),
                "eligibility": _eligibility_snapshot(self._eligibility),
                "event_offset": {
                    # Restart point for the observation stream. Anything at or
                    # before this has already been delivered to the estimator.
                    "newest_event_time_s": max(self._event_times.values(), default=None),
                    "delivered_event_ids": sorted(self._event_times),
                    "sequence": self._sequence,
                },
                "queued_driver_inputs": [_queued_as_dict(q) for q in self._queued_inputs],
                "acknowledged_driver_inputs": sorted(self._acknowledged_inputs),
                "communicated_at_s": dict(self._communicated_at_s),
                "recommendations": {
                    rid: rec.model_dump(mode="json") for rid, rec in self._recommendations.items()
                },
                "checkpoints_seen": [[cid, lap] for cid, lap in sorted(self._checkpoints_seen)],
                "next_decision_s": self._next_decision_s,
                "next_observation_s": self._next_observation_s,
                "last_progress_m": self._last_progress_m,
            }
            return snapshot_hash(simulation), payload

    def restore(self, payload: dict[str, Any]) -> RuntimeTick:
        with self._lock:
            if payload.get("schema") != SNAPSHOT_SCHEMA:
                raise SessionRuntimeError("unrecognised session runtime snapshot schema")
            manifest = self._require_manifest()
            if self._simulator is None:
                simulator = Simulator()
                simulator.reset(self._bundle, seed=int(payload["simulation"]["seed"]))
                self._simulator = simulator
            self._simulator.restore(payload["simulation"])
            self._require_estimator().restore(payload["estimator"])
            self._eligibility = _eligibility_restore(
                self._pack, self._bundle.track.length, payload.get("eligibility")
            )

            self._revision = int(payload["revision"]) + 1
            self._sequence = int(payload["event_offset"]["sequence"])
            newest = payload["event_offset"].get("newest_event_time_s")
            self._event_times = dict.fromkeys(
                payload["event_offset"].get("delivered_event_ids", ()), float(newest or 0.0)
            )
            self._pending_events.clear()
            self._queued_inputs = [_queued_from_dict(item) for item in payload["queued_driver_inputs"]]
            # A previously acknowledged deliberate command is never replayed.
            self._acknowledged_inputs = set(payload.get("acknowledged_driver_inputs", ()))
            self._queued_inputs = [
                queued for queued in self._queued_inputs if queued.id not in self._acknowledged_inputs
            ]
            self._communicated_at_s = dict(payload.get("communicated_at_s", {}))
            self._recommendations = {
                rid: Recommendation.model_validate(body)
                for rid, body in payload.get("recommendations", {}).items()
            }
            self._checkpoints_seen = {
                (str(cid), int(lap)) for cid, lap in payload.get("checkpoints_seen", ())
            }
            self._next_decision_s = float(payload["next_decision_s"])
            self._next_observation_s = float(payload["next_observation_s"])
            self._last_progress_m = float(payload["last_progress_m"])
            self._last_eligibility_time_s = float(payload["session_time_s"])
            self._paused = True
            self._stopped = False

            # The restored session is not ready until its state has been
            # re-estimated and its outstanding advice revalidated. Both happen
            # in `resume_after_restore`; until then, nothing is published.
            self._last_estimate = None
            self._last_planning = None
            self._last_recommendation = None
            self._last_tick = self._tick(executions=())
            del manifest
            return self._last_tick

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            if self._adapter is not None:
                self._adapter.close()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def session_time_s(self) -> float:
        return 0.0 if self._simulator is None else self._simulator.session_time_s

    # ------------------------------------------------------------------ #
    # driver execution
    # ------------------------------------------------------------------ #

    def mark_communicated(self, recommendation_id: str, at_s: float | None = None) -> float:
        """Record when the engineer told the driver. Not an execution."""
        with self._lock:
            moment = self.session_time_s if at_s is None else at_s
            self._communicated_at_s[recommendation_id] = moment
            self._revision += 1
            return moment

    def queue_driver_input(
        self,
        profile_id: DeploymentProfile,
        *,
        recommendation_id: str | None = None,
        issued_at_s: float | None = None,
    ) -> QueuedDriverInput:
        """Queue a deliberate driver input behind the configured reaction delay."""
        with self._lock:
            self._require_running()
            now = self.session_time_s
            issued = now if issued_at_s is None else max(0.0, issued_at_s)
            queued = QueuedDriverInput(
                id=f"drv-{uuid.uuid4().hex[:16]}",
                profile_id=profile_id,
                recommendation_id=recommendation_id,
                issued_at_s=issued,
                apply_at_s=now + self._config.driver_reaction_delay_s,
                communicated_at_s=(
                    self._communicated_at_s.get(recommendation_id) if recommendation_id is not None else None
                ),
            )
            self._queued_inputs.append(queued)
            self._revision += 1
            return queued

    @property
    def pending_driver_inputs(self) -> tuple[QueuedDriverInput, ...]:
        return tuple(self._queued_inputs)

    @property
    def executions(self) -> tuple[ExecutionEvent, ...]:
        return tuple(self._executions)

    def _release_driver_inputs(
        self, up_to_s: float, produced: list[ExecutionEvent]
    ) -> dict[str, DriverAction] | None:
        """Fire any queued input whose reaction delay has elapsed."""
        due = [q for q in self._queued_inputs if q.apply_at_s <= up_to_s + 1e-12]
        if not due:
            return None
        actions: dict[str, DriverAction] = {}
        for queued in due:
            self._queued_inputs.remove(queued)
            if queued.id in self._acknowledged_inputs:
                # Already applied once. A restart must not replay it.
                continue
            self._acknowledged_inputs.add(queued.id)
            actions[self._bundle.scenario.ego_car_id] = DriverAction(profile=queued.profile_id)
            execution = self._execution_for(queued)
            self._executions.append(execution)
            produced.append(execution)
            if self._recorder is not None:
                self._recorder.record_driver_execution(execution=execution, session_time_s=queued.apply_at_s)
            self._revision += 1
        return actions or None

    def _execution_for(self, queued: QueuedDriverInput) -> ExecutionEvent:
        self._sequence += 1
        recommendation = (
            self._recommendations.get(queued.recommendation_id)
            if queued.recommendation_id is not None
            else None
        )
        communicated = queued.communicated_at_s or (
            self._communicated_at_s.get(queued.recommendation_id or "") if queued.recommendation_id else None
        )
        match = self._match_status(queued, recommendation)
        return ExecutionEvent(
            schema_version=SCHEMA_VERSION,
            id=_execution_id(queued.id),
            session_id=self._require_manifest().id,
            recommendation_id=None if match is ExecutionMatch.UNSOLICITED else queued.recommendation_id,
            source=Provenance.SIMULATED,
            observed_profile_id=queued.profile_id,
            start_time_s=queued.apply_at_s,
            end_time_s=None,
            evidence_event_ids=(queued.id,),
            match_status=match,
            sequence=self._sequence,
            delay_from_communication_s=(
                max(0.0, queued.apply_at_s - communicated) if communicated is not None else None
            ),
        )

    def _match_status(
        self, queued: QueuedDriverInput, recommendation: Recommendation | None
    ) -> ExecutionMatch:
        if queued.recommendation_id is None or recommendation is None:
            return ExecutionMatch.UNSOLICITED
        plan = self._last_accepted_plan
        expected = (
            plan.profile_segments[0].profile_id
            if plan is not None and plan.id == recommendation.plan_id
            else None
        )
        if expected is not None and expected is not queued.profile_id:
            return ExecutionMatch.DIFFERENT_PROFILE
        if queued.apply_at_s >= recommendation.expires_at_s:
            return ExecutionMatch.LATE
        return ExecutionMatch.MATCHED

    # ------------------------------------------------------------------ #
    # observation and ingestion
    # ------------------------------------------------------------------ #

    def _collect_observations(self) -> None:
        simulator = self._require_simulator()
        source = self._require_source()
        now = simulator.session_time_s
        if now + 1e-12 < self._next_observation_s:
            return
        period = 1.0 / self._config.observation_rate_hz
        while self._next_observation_s <= now + 1e-12:
            self._next_observation_s += period
        ego = self._bundle.scenario.ego_car_id
        source.offer(simulator.observe(car_id=ego)[ego])

    def _ingest_pending(self) -> None:
        adapter = self._require_adapter()
        pipeline = self._require_pipeline()
        now = self.session_time_s
        output = None
        for record in adapter.events():
            result = pipeline.ingest(record, now_s=now)
            output = result if output is None else output + result
        flushed = pipeline.flush(now)
        output = flushed if output is None else output + flushed
        for normalised in output.decision_visible():
            self._pending_events.append(normalised.event)
            self._event_times[normalised.event.event_id] = normalised.session_time_s

    # ------------------------------------------------------------------ #
    # decision
    # ------------------------------------------------------------------ #

    def decide_now(self) -> RuntimeTick:
        """Run one decision cycle at the current session time without integrating.

        The worker's ``Plan`` command needs to re-decide against the state it
        already has — for instance after a rule change — without moving physics
        forward, which would change the state the decision is about.
        """
        with self._lock:
            self._require_running()
            self._revision += 1
            self._ingest_pending()
            self._decide()
            self._last_tick = self._tick(executions=())
            return self._last_tick

    def _decide(self) -> None:
        started = time.perf_counter()
        simulator = self._require_simulator()
        now = simulator.session_time_s
        batch = tuple(self._pending_events)
        self._pending_events.clear()

        cutoff = max((self._event_times[e.event_id] for e in batch), default=None)
        if cutoff is None:
            cutoff = self._last_estimate.cutoff_s if self._last_estimate is not None else 0.0
        cutoff = min(cutoff, now)

        if self._recorder is not None:
            self._recorder.expire(session_time_s=now)

        estimate = self._estimate(batch, cutoff_s=cutoff, now_s=now)
        self._last_estimate = estimate
        self._last_ingestion = IngestionReport(
            cutoff_s=cutoff,
            events=batch,
            event_times_s={e.event_id: self._event_times[e.event_id] for e in batch},
            skipped_missing_observations=self._require_source().skipped_missing,
        )

        context = self._rule_context(estimate, now_s=now)
        self._last_rule_context = context

        persistence = self._recorder.status() if self._recorder is not None else PersistenceStatus()
        report = assess(
            DegradationInputs(
                estimate=estimate,
                rule_context=context,
                persistence=persistence,
                model=self._model_decision,
            )
        )
        self._last_degradation = report

        planning = self._plan(estimate, context, report, now_s=now)
        self._last_planning = planning
        if planning is not None and planning.duration_ms:
            self._plan_durations_ms.append(planning.duration_ms)

        self._publish(estimate, context, planning, report, now_s=now, cutoff_s=cutoff)

        # A02: publish the decision cutoff so a later arrival at or before it is
        # archived but excluded from the state this decision observed.
        self._require_pipeline().finalise(cutoff)
        self._decision_durations_ms.append((time.perf_counter() - started) * 1000.0)

    def _estimate(self, batch: Sequence[TelemetryEvent], *, cutoff_s: float, now_s: float) -> StateEstimate:
        pipeline = self._require_pipeline()
        assessment = pipeline.assess_quality(now_s)
        context = EstimationContext(
            session_id=self._require_manifest().id,
            car_id=self._bundle.scenario.ego_car_id,
            cutoff_s=cutoff_s,
            track_length_m=self._bundle.track.length,
            created_at_s=now_s,
            clock=ClockMapping(source_id=self._require_source().source_id, offset_s=0.0),
            clock_uncertainty_s=self._require_source().observation_capability().clock_error_s,
            lap=self._current_lap(),
            rival_car_ids=self._bundle.scenario.rival_ids,
            capability=self._require_source().observation_capability(),
            channel_quality=assessment.channels,
            integration_gap_s={gap.channel: gap.cumulative_gap_s for gap in assessment.integration_gaps},
            lateral_geometry_known=False,
            notes=(
                "simulated observations; the source declares no electrical-power channel, so the "
                "energy state is corrected only by battery-energy samples",
            ),
        )
        return update(batch, self._require_estimator(), context)

    def _rule_context(self, estimate: StateEstimate, *, now_s: float) -> RuleContext:
        own = estimate.own_car
        progress = float(own.progress_m.value or self._last_progress_m)
        # The eligibility machine needs monotone progress. The estimate can
        # jitter backwards by centimetres; clamping is recorded rather than
        # hidden so a real regression is still visible in the counter.
        if progress < self._last_progress_m:
            self._eligibility_clamps += 1
            progress = self._last_progress_m
        machine = self._require_eligibility()
        machine.advance(
            self._last_eligibility_time_s,
            max(now_s, self._last_eligibility_time_s),
            self._last_progress_m,
            progress,
            gap_condition_met=self._gap_condition_met(estimate),
        )
        self._last_progress_m = progress
        self._last_eligibility_time_s = max(now_s, self._last_eligibility_time_s)

        energy = own.battery_energy_j.value
        if energy is None:
            energy = conservative_energy_floor_j(
                estimate, manifest_floor_j=self._pack.manifest.battery_energy_min_j
            )
        car_state = CarState(
            speed_mps=max(0.0, float(own.speed_mps.value or 0.0)),
            battery_energy_j=max(0.0, float(energy)),
            current_power_w=float(own.electrical_power_w.value or 0.0),
            temperature_k=own.battery_temperature_k.value,
            recharge_used_this_lap_j=float(own.recharge_spent_this_lap_j.value or 0.0),
            eligibility=machine.state,
            eligibility_observed_at_s=machine.observed_at_s,
            sector_id=None,
            lap_index=self._current_lap(),
        )
        return resolve_pack_context(
            self._pack,
            progress,
            now_s,
            car_state,
            session_id=self._require_manifest().id,
        )

    def _gap_condition_met(self, estimate: StateEstimate) -> bool | None:
        """Evaluate the declared sporting gap condition, or leave it unresolved."""
        threshold = self._config.eligibility.gap_threshold_s
        if threshold is None:
            return None
        ahead = estimate.nearest_ahead
        if ahead is None or ahead.gap_s.value is None:
            return False
        return abs(float(ahead.gap_s.value)) <= threshold

    def _plan(
        self,
        estimate: StateEstimate,
        context: RuleContext,
        report: DegradationReport,
        *,
        now_s: float,
    ) -> PlanningResult | None:
        if report.halted:
            return None
        if report.analysis_only:
            return _refused(
                self._require_manifest().id,
                self._revision,
                now_s,
                self._config.planner_deadline_s,
                PlanningStatus.INPUT_UNAVAILABLE,
                (ReasonCode.OWN_ENERGY_UNAVAILABLE,),
                "analysis-only: no measured battery-energy channel, so no energy directive is issued",
                self._identity(),
            )
        request = self.open_plan_request(estimate, context, now_s=now_s)
        if request is None:
            return _refused(
                self._require_manifest().id,
                self._revision,
                now_s,
                self._config.planner_deadline_s,
                PlanningStatus.INPUT_UNAVAILABLE,
                (ReasonCode.STALE_OBSERVATIONS,),
                "the estimate does not yet support a checker state",
                self._identity(),
            )
        started = time.perf_counter()
        result = self._planner.plan(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result.status is PlanningStatus.DEADLINE_EXCEEDED:
            return self._handle_timeout(result, request, elapsed_ms=elapsed_ms)
        application = self.accept_plan_result(request, result)
        if not application.applied:
            logger.info("discarding planning result: %s", application.reason)
            return None
        return result

    def open_plan_request(
        self, estimate: StateEstimate, context: RuleContext, *, now_s: float | None = None
    ) -> PlanRequest | None:
        """Build a plan request stamped with the current revision.

        Hold the returned request across a slow solve; :meth:`accept_plan_result`
        compares its ``revision`` against the runtime's before applying anything.
        """
        with self._lock:
            moment = self.session_time_s if now_s is None else now_s
            energy = estimate.own_car.battery_energy_j.value
            if energy is None:
                return None
            try:
                checker_state = checker_state_for(
                    estimate=estimate,
                    session_time_s=moment,
                    track_length_m=self._bundle.track.length,
                    battery_energy_j=float(energy),
                    driver_reaction_time_s=self._config.driver_reaction_delay_s,
                    charge_bus_efficiency=self._ego_car().eta_charge.value,
                    discharge_efficiency=self._ego_car().eta_discharge.value,
                )
            except ValueError:
                return None
            decision = self._model_decision
            return PlanRequest(
                session_id=self._require_manifest().id,
                revision=self._revision,
                now_s=moment,
                deadline_s=self._config.planner_deadline_s,
                estimate=estimate,
                rule_context=context,
                manifest=self._pack.manifest,
                checker_state=checker_state,
                objective_version=self._objective_version,
                admissible=context.admissible_profiles,
                model_hash=self._require_manifest().model_hash,
                learned_contribution_enabled=bool(decision and decision.enabled),
                baseline_identity=(decision.baseline_identity if decision else BASELINE_IDENTITY),
                segment_length_m=self._config.segment_length_m,
                lead_time_s=self._config.lead_time_s,
                execution_window_s=self._config.execution_window_s,
            )

    def accept_plan_result(self, request: PlanRequest, result: PlanningResult) -> PlanApplication:
        """Apply a planning result, or discard it if its revision is superseded."""
        with self._lock:
            if request.revision != self._revision:
                return PlanApplication(
                    applied=False,
                    reason=(
                        f"planning result was computed against revision {request.revision}; the "
                        f"session is now at {self._revision}, so it is discarded rather than applied"
                    ),
                    issued_revision=request.revision,
                    current_revision=self._revision,
                )
            if result.state_revision != request.revision:
                return PlanApplication(
                    applied=False,
                    reason=(
                        f"planning result carries state revision {result.state_revision}, "
                        f"which is not the revision {request.revision} it was requested for"
                    ),
                    issued_revision=request.revision,
                    current_revision=self._revision,
                )
            return PlanApplication(
                applied=True,
                reason="revision matches",
                issued_revision=request.revision,
                current_revision=self._revision,
            )

    def _handle_timeout(
        self, result: PlanningResult, request: PlanRequest, *, elapsed_ms: float
    ) -> PlanningResult:
        """Solver timeout: revalidate the prior plan, or withdraw the advice."""
        prior = self._last_accepted_plan
        revalidation: ConstraintResult | None = None
        if prior is not None:
            revalidation = check_plan(
                prior,
                request.checker_state,
                request.rule_context,
                manifest=self._pack.manifest,
            )
        outcome = solver_timeout_outcome(
            elapsed_ms=elapsed_ms,
            deadline_ms=request.deadline_s * 1000.0,
            prior_plan_id=None if prior is None else prior.id,
            revalidation=revalidation,
        )
        self._last_degradation = self._last_degradation.merged_with(outcome.finding)
        if not outcome.revalidated_prior_plan or prior is None:
            return result.revise(
                reason_codes=tuple(dict.fromkeys((*result.reason_codes, ReasonCode.SOLVER_TIMEOUT))),
                detail=outcome.finding.detail,
            )
        revalidated = prior.revise(
            constraint_result=revalidation,
            state_revision=request.revision,
            reason_codes=tuple(dict.fromkeys((*prior.reason_codes, ReasonCode.SOLVER_TIMEOUT))),
        )
        return PlanningResult(
            schema_version=SCHEMA_VERSION,
            session_id=request.session_id,
            state_revision=request.revision,
            status=PlanningStatus.OK,
            created_at_s=request.now_s,
            deadline_s=request.deadline_s,
            duration_ms=elapsed_ms,
            accepted=(revalidated,),
            selected_plan_id=revalidated.id,
            reason_codes=(ReasonCode.SOLVER_TIMEOUT,),
            candidate_count=1,
            learned_contribution_enabled=request.learned_contribution_enabled,
            baseline_identity=request.baseline_identity,
            detail=outcome.finding.detail,
        )

    # ------------------------------------------------------------------ #
    # publishing
    # ------------------------------------------------------------------ #

    def _publish(
        self,
        estimate: StateEstimate,
        context: RuleContext,
        planning: PlanningResult | None,
        report: DegradationReport,
        *,
        now_s: float,
        cutoff_s: float,
    ) -> None:
        if report.halted:
            # Halt new operational recommendations to preserve auditability.
            self._last_recommendation = None
            return
        if self._recorder is not None and not self._recorder.accepts_new_recommendations():
            self._last_recommendation = None
            return

        if planning is None or planning.status is not PlanningStatus.OK or not planning.accepted:
            self._last_recommendation = self._withdraw(
                estimate, context, report, now_s=now_s, cutoff_s=cutoff_s, planning=planning
            )
            return

        candidate = planning.accepted[0]
        # The independent checker, not the planner, decides legality.
        checked = check_plan(
            candidate,
            checker_state_for(
                estimate=estimate,
                session_time_s=now_s,
                track_length_m=self._bundle.track.length,
                battery_energy_j=float(estimate.own_car.battery_energy_j.value or 0.0),
                driver_reaction_time_s=self._config.driver_reaction_delay_s,
                charge_bus_efficiency=self._ego_car().eta_charge.value,
                discharge_efficiency=self._ego_car().eta_discharge.value,
            ),
            context,
            manifest=self._pack.manifest,
        )
        plan = candidate.revise(constraint_result=checked)
        self._last_planning = planning.revise(
            accepted=(plan, *planning.accepted[1:]), selected_plan_id=plan.id
        )
        if checked.status is not CheckStatus.PASS:
            self._last_recommendation = self._withdraw(
                estimate,
                context,
                report,
                now_s=now_s,
                cutoff_s=cutoff_s,
                planning=self._last_planning,
                constraint_result=checked,
            )
            return

        self._last_accepted_plan = plan
        recommendation = Recommendation(
            schema_version=SCHEMA_VERSION,
            id=f"rec-{uuid.uuid4().hex[:16]}",
            revision=0,
            session_id=self._require_manifest().id,
            state_revision=estimate.revision,
            plan_id=plan.id,
            status=RecommendationStatus.PROPOSED,
            action_code=plan.intention,
            display_text=_display_text(plan),
            trigger=Trigger(
                kind="immediate",
                progress_m=plan.profile_segments[0].start_progress_m,
                description=(
                    f"begin at {plan.profile_segments[0].start_progress_m:.0f} m, "
                    f"within {plan.profile_segments[0].execution_window_s:.1f} s"
                ),
            ),
            end_condition=(f"hold to {plan.profile_segments[-1].end_progress_m:.0f} m or until withdrawn"),
            created_at_s=now_s,
            valid_from_s=now_s,
            expires_at_s=now_s + self._config.recommendation_validity_s,
            observation_cutoff_s=cutoff_s,
            ruleset_hash=context.ruleset_hash,
            model_hash=self._require_manifest().model_hash,
            objective_version=self._objective_version,
            reason_codes=tuple(dict.fromkeys((*plan.reason_codes, *report.reason_codes))),
            outcomes=(),
            probabilities=(),
            constraint_result=checked,
            learned_contribution_enabled=bool(self._model_decision and self._model_decision.enabled),
            baseline_identity=self._identity(),
        )
        self._register(recommendation, estimate, plan, now_s=now_s)

    def _withdraw(
        self,
        estimate: StateEstimate,
        context: RuleContext,
        report: DegradationReport,
        *,
        now_s: float,
        cutoff_s: float,
        planning: PlanningResult | None,
        constraint_result: ConstraintResult | None = None,
    ) -> Recommendation:
        result = constraint_result or ConstraintResult(
            schema_version=SCHEMA_VERSION,
            status=CheckStatus.UNKNOWN,
            checks=(),
            ruleset_hash=context.ruleset_hash,
            checked_at_s=max(now_s, 0.0),
            checker_version="afterlap-session-runtime-withdrawal",
            unresolved_conditions=tuple(
                dict.fromkeys(
                    (
                        *context.unknown_conditions,
                        *(f.effect for f in report.findings if f.withdraw_advice),
                    )
                )
            )
            or ("no_legal_checked_candidate",),
        )
        reasons = tuple(
            dict.fromkeys((*report.reason_codes, *(planning.reason_codes if planning is not None else ())))
        )
        recommendation = Recommendation(
            schema_version=SCHEMA_VERSION,
            id=f"rec-{uuid.uuid4().hex[:16]}",
            revision=0,
            session_id=self._require_manifest().id,
            state_revision=estimate.revision,
            plan_id=None,
            status=RecommendationStatus.PROPOSED,
            action_code=ActionCode.WITHDRAW_ADVICE,
            display_text="No advice: " + _withdrawal_reason(report, planning, result),
            trigger=Trigger(kind="immediate", description="no action is being recommended"),
            end_condition="advice resumes when the missing input or permission is resolved",
            created_at_s=now_s,
            valid_from_s=now_s,
            expires_at_s=now_s + self._config.recommendation_validity_s,
            observation_cutoff_s=cutoff_s,
            ruleset_hash=context.ruleset_hash,
            model_hash=self._require_manifest().model_hash,
            objective_version=self._objective_version,
            reason_codes=reasons,
            constraint_result=result,
            learned_contribution_enabled=False,
            baseline_identity=self._identity(),
        )
        self._register(recommendation, estimate, None, now_s=now_s)
        return recommendation

    def _register(
        self,
        recommendation: Recommendation,
        estimate: StateEstimate,
        plan: CandidatePlan | None,
        *,
        now_s: float,
    ) -> None:
        self._recommendations[recommendation.id] = recommendation
        self._last_recommendation = recommendation
        if self._recorder is not None:
            self._recorder.publish_recommendation(
                recommendation=recommendation,
                estimate=estimate,
                accepted=() if plan is None else (plan,),
                rejected=(),
                session_time_s=now_s,
            )

    # ------------------------------------------------------------------ #
    # rule changes, invalidation and recovery
    # ------------------------------------------------------------------ #

    def set_rule_pack(self, pack: RulePack, *, reason: str = "ruleset changed") -> int:
        """Swap the rule pack. Outstanding advice is invalidated immediately."""
        with self._lock:
            self._pack = pack
            self._eligibility = _eligibility_machine(pack, self._bundle.track.length)
            return self.invalidate(reason)

    def invalidate(self, reason: str) -> int:
        """Withdraw outstanding advice and bump the revision."""
        with self._lock:
            self._revision += 1
            self._last_accepted_plan = None
            self._last_recommendation = None
            if self._recorder is not None:
                self._recorder.invalidate_all(reason=reason, session_time_s=self.session_time_s)
            return self._revision

    def resume_after_restore(self) -> RuntimeTick:
        """Re-estimate, revalidate and only then declare the session ready again.

        A restored runtime is paused and publishes nothing. This advances one
        decision interval so a fresh estimate exists, the rule context is
        resolved again and any surviving plan is independently re-checked before
        the session is usable.
        """
        with self._lock:
            self._paused = False
            self._next_decision_s = self.session_time_s
            tick = self.advance(self._config.decision_interval_s)
            return tick

    @property
    def ready(self) -> bool:
        """A restored or paused session is not ready until it has re-estimated."""
        return (
            not self._stopped
            and not self._paused
            and self._last_estimate is not None
            and self._last_rule_context is not None
        )

    # ------------------------------------------------------------------ #
    # outcomes and export
    # ------------------------------------------------------------------ #

    def _record_checkpoint_outcomes(self) -> None:
        simulator = self._require_simulator()
        ego = self._bundle.scenario.ego_car_id
        wanted = set(self._bundle.scenario.evaluation_checkpoints)
        for record in simulator.world.checkpoint_records:
            if record.car_id != ego or record.checkpoint_id not in wanted:
                continue
            key = (record.checkpoint_id, record.lap)
            if key in self._checkpoints_seen:
                continue
            self._checkpoints_seen.add(key)
            outcome = OutcomeRecord(
                schema_version=SCHEMA_VERSION,
                id=new_outcome_id(),
                session_id=self._require_manifest().id,
                decision_id=(self._last_recommendation.id if self._last_recommendation is not None else None),
                checkpoint=CheckpointDefinition(
                    checkpoint_id=record.checkpoint_id,
                    progress_m=record.progress_m,
                    description=f"named evaluation checkpoint on lap {record.lap}",
                ),
                evaluation_horizon_s=self._config.checkpoint_horizon_s,
                event_observed=True,
                elapsed_time_s=record.session_time_s,
                energy_j=record.battery_energy_j,
                position=self._position(),
                gap_to_reference_s=None,
                provenance=Provenance.SIMULATED,
            )
            self._outcomes.append(outcome)
            if self._recorder is not None:
                self._recorder.record_outcome(outcome=outcome, session_time_s=record.session_time_s)

    @property
    def outcomes(self) -> tuple[OutcomeRecord, ...]:
        return tuple(self._outcomes)

    def export_record(self) -> dict[str, Any]:
        """The complete session record, in wire form and free of simulator truth."""
        with self._lock:
            manifest = self._require_manifest()
            return {
                "schema": "afterlap.session.export/1",
                "synthetic": manifest.synthetic,
                "notice": (
                    "Synthetic scenario produced by the AFTERLAP simulator. Not measured telemetry "
                    "and not a calibrated car."
                ),
                "manifest": manifest.model_dump(mode="json"),
                "session_time_s": self.session_time_s,
                "revision": self._revision,
                "ruleset_hash": self._pack.ruleset_hash,
                "objective_version": self._objective_version,
                "baseline_identity": self._identity(),
                "source_capability": self._require_source().observation_capability().model_dump(mode="json"),
                "estimate": (
                    None if self._last_estimate is None else self._last_estimate.model_dump(mode="json")
                ),
                "rule_context": (
                    None
                    if self._last_rule_context is None
                    else self._last_rule_context.model_dump(mode="json")
                ),
                "planning": (
                    None if self._last_planning is None else self._last_planning.model_dump(mode="json")
                ),
                "recommendations": [rec.model_dump(mode="json") for rec in self._recommendations.values()],
                "executions": [event.model_dump(mode="json") for event in self._executions],
                "outcomes": [outcome.model_dump(mode="json") for outcome in self._outcomes],
                "degradation": self._last_degradation.as_list(),
                "eligibility": {
                    "state": self._require_eligibility().state.value,
                    "policy": {
                        "gap_threshold_s": self._config.eligibility.gap_threshold_s,
                        "provenance": self._config.eligibility.provenance,
                        "note": self._config.eligibility.note,
                    },
                    "progress_clamps": self._eligibility_clamps,
                },
            }

    # ------------------------------------------------------------------ #
    # observable state
    # ------------------------------------------------------------------ #

    @property
    def last_estimate(self) -> StateEstimate | None:
        return self._last_estimate

    @property
    def last_rule_context(self) -> RuleContext | None:
        return self._last_rule_context

    @property
    def last_planning(self) -> PlanningResult | None:
        return self._last_planning

    @property
    def last_recommendation(self) -> Recommendation | None:
        return self._last_recommendation

    @property
    def last_ingestion(self) -> IngestionReport | None:
        return self._last_ingestion

    @property
    def degradation(self) -> DegradationReport:
        return self._last_degradation

    @property
    def model_decision(self) -> ModelDecision | None:
        return self._model_decision

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def rule_pack(self) -> RulePack:
        return self._pack

    @property
    def planner(self) -> Planner:
        return self._planner

    def debug_truth(self) -> dict[str, Any]:
        """Complete hidden truth, for diagnostics and tests only.

        ``08_backend/TECHNICAL_SPEC.md`` keeps debug truth on a separately
        authorised path that is unavailable in replay and live-team modes. This
        is that path's runtime side: it is refused outside a simulation session,
        it is called by nothing on the publishing path, and no value it returns
        ever reaches a ``StateEstimate``, a ``Recommendation`` or an export.
        """
        from afterlap_core.simulation.observation import debug_truth as _truth

        if self._require_manifest().mode is not SessionMode.SIMULATION:
            raise SessionRuntimeError("debug truth is unavailable outside a simulation session")
        return _truth(self._require_simulator().world)

    @property
    def observation_source(self) -> SimulatorObservationSource:
        return self._require_source()

    @property
    def normalised_records(self) -> tuple[NormalisedRecord, ...]:
        return tuple(self._require_sink().normalised)

    @property
    def decision_durations_ms(self) -> tuple[float, ...]:
        return tuple(self._decision_durations_ms)

    @property
    def plan_durations_ms(self) -> tuple[float, ...]:
        return tuple(self._plan_durations_ms)

    def _tick(self, *, executions: tuple[ExecutionEvent, ...]) -> RuntimeTick:
        return RuntimeTick(
            session_time_s=self.session_time_s,
            revision=self._revision,
            estimate=self._last_estimate,
            rule_context=self._last_rule_context,
            planning=self._last_planning,
            recommendation=self._last_recommendation,
            executions=executions,
            finished=self._stopped,
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _identity(self) -> str:
        decision = self._model_decision
        return decision.baseline_identity if decision is not None else BASELINE_IDENTITY

    def _current_lap(self) -> int:
        if self._simulator is None:
            return 0
        return int(self._last_progress_m // self._bundle.track.length)

    def _position(self) -> int:
        simulator = self._require_simulator()
        ego = self._bundle.scenario.ego_car_id
        own = simulator.world.cars[ego].progress_m
        return 1 + sum(
            1 for car_id, state in simulator.world.cars.items() if car_id != ego and state.progress_m > own
        )

    def _ego_car(self):  # type: ignore[no-untyped-def]
        return self._bundle.car_configs[self._bundle.scenario.ego_car_id]

    def _require_running(self) -> None:
        if self._stopped:
            raise SessionRuntimeError("this session runtime has been stopped")
        if self._simulator is None:
            raise SessionRuntimeError("initialise() must be called before the session can be driven")

    def _require_manifest(self) -> SessionManifest:
        if self._manifest is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._manifest

    def _require_simulator(self) -> Simulator:
        if self._simulator is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._simulator

    def _require_source(self) -> SimulatorObservationSource:
        if self._source is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._source

    def _require_adapter(self) -> SimulatorAdapter:
        if self._adapter is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._adapter

    def _require_pipeline(self) -> IngestionPipeline:
        if self._pipeline is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._pipeline

    def _require_sink(self) -> MemorySink:
        if self._sink is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._sink

    def _require_estimator(self) -> EstimatorState:
        if self._estimator is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._estimator

    def _require_eligibility(self) -> EligibilityMachine:
        if self._eligibility is None:
            raise SessionRuntimeError("the session has not been initialised")
        return self._eligibility


# ---------------------------------------------------------------------- #
# module helpers
# ---------------------------------------------------------------------- #


def default_planner() -> tuple[Planner, str]:
    """Prefer A06's planner when it is importable; otherwise the baseline.

    Returns the planner and a note recording which path was taken, so a decision
    record can name the planner that actually produced it rather than the one
    that was hoped for.
    """
    try:
        from afterlap_core.planning import plan as _external_plan
    except ImportError as exc:  # pragma: no cover - depends on another agent's merge state
        return BaselinePlanner(), f"A06 planner unavailable ({exc}); using the baseline"
    return _ExternalPlannerAdapter(_external_plan), "A06 planner (afterlap_core.planning.plan)"


class _ExternalPlannerAdapter:
    """Adapts A06's ``plan(estimate, rule_context, ...)`` to the runtime protocol."""

    identity = "afterlap-core-planning"

    def __init__(self, plan_fn: Any) -> None:
        self._plan = plan_fn

    def plan(self, request: PlanRequest) -> PlanningResult:
        return self._plan(
            request.estimate,
            request.rule_context,
            None,
            request.deadline_s,
            manifest=request.manifest,
            now_s=request.now_s,
        )


def default_runtime_config(bundle: ScenarioBundle) -> RuntimeConfig:
    """Read the driver reaction delay from the scenario rather than inventing one."""
    driver = bundle.scenario.drivers[bundle.scenario.ego_car_id]
    return RuntimeConfig(driver_reaction_delay_s=float(driver.reaction_delay_mean_s.value))


def _eligibility_machine(pack: RulePack, track_length_m: float) -> EligibilityMachine:
    try:
        return EligibilityMachine.from_lines(pack.manifest.detection_lines, track_length_m)
    except ValueError:
        # The pack declares no detection/activation pair. Eligibility therefore
        # stays UNKNOWN, which suppresses advice; guessing a line location would
        # be exactly the invented default the plan forbids.
        return EligibilityMachine(
            detection_s_m=0.0,
            activation_s_m=0.0,
            track_length_m=track_length_m,
            detection_line_id="__none__",
            activation_line_id="__none__",
        )


def _eligibility_snapshot(machine: EligibilityMachine | None) -> dict[str, Any]:
    if machine is None:
        return {}
    return {
        "state": machine.state.value,
        "observed_at_s": machine.observed_at_s,
        "activated_at_s": machine.activated_at_s,
        "detections_this_lap": machine.detections_this_lap,
        "activations_this_lap": machine.activations_this_lap,
        "total_detections": machine.total_detections,
        "total_activations": machine.total_activations,
    }


def _eligibility_restore(
    pack: RulePack, track_length_m: float, payload: dict[str, Any] | None
) -> EligibilityMachine:
    machine = _eligibility_machine(pack, track_length_m)
    if not payload:
        return machine
    machine.state = EligibilityState(payload["state"])
    machine.observed_at_s = payload.get("observed_at_s")
    machine.activated_at_s = payload.get("activated_at_s")
    machine.detections_this_lap = int(payload.get("detections_this_lap", 0))
    machine.activations_this_lap = int(payload.get("activations_this_lap", 0))
    machine.total_detections = int(payload.get("total_detections", 0))
    machine.total_activations = int(payload.get("total_activations", 0))
    return machine


def _queued_as_dict(queued: QueuedDriverInput) -> dict[str, Any]:
    return {
        "id": queued.id,
        "profile_id": queued.profile_id.value,
        "recommendation_id": queued.recommendation_id,
        "issued_at_s": queued.issued_at_s,
        "apply_at_s": queued.apply_at_s,
        "communicated_at_s": queued.communicated_at_s,
    }


def _queued_from_dict(payload: dict[str, Any]) -> QueuedDriverInput:
    return QueuedDriverInput(
        id=str(payload["id"]),
        profile_id=DeploymentProfile(payload["profile_id"]),
        recommendation_id=payload.get("recommendation_id"),
        issued_at_s=float(payload["issued_at_s"]),
        apply_at_s=float(payload["apply_at_s"]),
        communicated_at_s=payload.get("communicated_at_s"),
    )


def _execution_id(queued_id: str) -> str:
    return f"exe-{queued_id}"


def _display_text(plan: CandidatePlan) -> str:
    first = plan.profile_segments[0]
    verb = first.profile_id.value.upper()
    if first.requested_budget_j > 0.0:
        return f"{verb} {first.requested_budget_j / 1e6:.2f} MJ to {first.end_progress_m:.0f} m"
    return f"{verb} recover {first.harvest_target_j / 1e6:.2f} MJ to {first.end_progress_m:.0f} m"


def _withdrawal_reason(
    report: DegradationReport, planning: PlanningResult | None, result: ConstraintResult
) -> str:
    for finding in report.findings:
        if finding.withdraw_advice:
            return finding.effect.replace("_", " ")
    if planning is not None and planning.status is not PlanningStatus.OK:
        return planning.status.value.replace("_", " ")
    return f"independent check returned {result.status.value}"


def _refused(
    session_id: str,
    revision: int,
    now_s: float,
    deadline_s: float,
    status: PlanningStatus,
    reasons: tuple[ReasonCode, ...],
    detail: str,
    baseline_identity: str,
) -> PlanningResult:
    return PlanningResult(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        state_revision=revision,
        status=status,
        created_at_s=now_s,
        deadline_s=deadline_s,
        duration_ms=0.0,
        accepted=(),
        rejected=(),
        selected_plan_id=None,
        reason_codes=reasons,
        learned_contribution_enabled=False,
        baseline_identity=baseline_identity,
        detail=detail,
    )


__all__ = [
    "SNAPSHOT_SCHEMA",
    "SYNTHETIC_GAP_THRESHOLD",
    "UNRESOLVED_GAP_THRESHOLD",
    "EligibilityPolicy",
    "InProcessSessionRuntime",
    "IngestionReport",
    "PlanApplication",
    "QueuedDriverInput",
    "RuntimeConfig",
    "SessionRuntimeError",
    "default_planner",
    "default_runtime_config",
]
