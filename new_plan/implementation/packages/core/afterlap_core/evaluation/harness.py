"""The benchmark harness: frozen manifests in, raw paired results out.

Design rules taken directly from the specifications and enforced here:

* **Paired scenarios and seeds.** Every controller is run from the same frozen
  scenario, the same seed and the same starting snapshot. Results are keyed by
  ``(scenario, seed)`` so a downstream bootstrap can preserve the pairing.
* **Rivals react independently in each branch.** Each run is its own
  ``Simulator``; the opponents re-decide from *their own* observations. Their
  actions are recorded for inspection but are never replayed into another
  branch as immutable truth.
* **Withdrawals and timeouts stay in the denominator.** A controller that
  declines a decision, or that misses its compute allowance, has that recorded
  against it. It cannot look better by refusing the hard cases.
* **Unmerged rows are missing, not zero.** A controller that returns
  ``SOLVER_UNAVAILABLE`` on every tick is recorded as an unavailable run and its
  outcome carries no metric values at all.

Nothing in this module imports ``afterlap_core.planning`` or
``afterlap_core.estimation``; a controller reaches the harness through the
:class:`~afterlap_core.evaluation.controllers.Controller` protocol.
"""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import (
    SCHEMA_VERSION,
    DeploymentProfile,
    EligibilityState,
    ExperimentManifest,
    FailureCategory,
    PlanningStatus,
    RuleContext,
)
from afterlap_core.config import load_yaml
from afterlap_core.paths import Paths, sha256_json
from afterlap_core.rules import CarState as RuleCarState
from afterlap_core.rules import RulePack, load_rule_pack, resolve_pack_context
from afterlap_core.simulation import Simulator, load_bundle
from afterlap_core.simulation.branching import snapshot_hash
from afterlap_core.simulation.config import ScenarioBundle
from afterlap_core.simulation.observation import Observation

from .controllers import ControlDecision, Controller, ControlRequest, build_request

__all__ = [
    "BenchmarkManifest",
    "BenchmarkRun",
    "CheckpointOutcome",
    "EnvironmentRecord",
    "RunOutcome",
    "environment_record",
    "list_benchmark_manifests",
    "load_benchmark_manifest",
    "load_objective",
    "objective_utility",
    "run_benchmark",
]

MANIFEST_KIND = "benchmarks/manifests"
EVALUATOR_VERSION = "afterlap-evaluator-1"
METRICS_VERSION = "afterlap-metrics-1"


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


class BenchmarkManifest(BaseModel):
    """A frozen definition of one benchmark population.

    ``TRAINING_AND_PROMOTION.md`` requires the train/tuning/calibration/test
    manifests to be frozen before training, and the test manifest to be opened
    only for candidate promotion. The split is recorded here so that opening the
    wrong one is a visible act.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    split: Literal["train", "tuning", "calibration", "test"]
    synthetic: bool = True
    description: str = Field(min_length=1)
    scenario_ids: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)
    families: dict[str, str] = Field(default_factory=dict)
    horizon_s: float = Field(gt=0.0)
    dt_s: float = Field(gt=0.0)
    decision_interval_s: float = Field(gt=0.0)
    compute_budget_ms: float = Field(gt=0.0)
    rule_pack_id: str = Field(min_length=1)
    checkpoint_ids: tuple[str, ...] = ()
    evaluator_version: str = EVALUATOR_VERSION
    metrics_version: str = METRICS_VERSION
    frozen_at: datetime | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> BenchmarkManifest:
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario ids must be unique inside one manifest")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique inside one manifest")
        if self.dt_s > self.decision_interval_s:
            raise ValueError("the integration step must not exceed the decision interval")
        unknown = set(self.families) - set(self.scenario_ids)
        if unknown:
            raise ValueError(f"families names scenarios not in this manifest: {sorted(unknown)}")
        return self

    @property
    def manifest_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))

    def family_of(self, scenario_id: str) -> str:
        return self.families.get(scenario_id, "unassigned")

    @property
    def unit_count(self) -> int:
        return len(self.scenario_ids) * len(self.seeds)

    def experiment_manifest(
        self, *, snapshot_digest: str, treatment_ids: Sequence[str]
    ) -> ExperimentManifest:
        """The frozen contract record describing this experiment."""
        return ExperimentManifest(
            schema_version=SCHEMA_VERSION,
            id=f"{self.id}:{snapshot_digest[:16]}",
            snapshot_hash=snapshot_digest,
            treatment_ids=tuple(treatment_ids),
            disturbance_seed_ids=self.seeds,
            evaluator_version=self.evaluator_version,
            metrics_version=self.metrics_version,
            evaluation_horizon_s=self.horizon_s,
            checkpoint_ids=self.checkpoint_ids,
            created_at=datetime.now(UTC),
        )


def _manifest_dir(paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).configs / "benchmarks" / "manifests"


def list_benchmark_manifests(paths: Paths | None = None) -> tuple[str, ...]:
    directory = _manifest_dir(paths)
    if not directory.is_dir():
        return ()
    return tuple(sorted(p.stem for p in directory.glob("*.yaml")))


def load_benchmark_manifest(manifest_id: str, paths: Paths | None = None) -> BenchmarkManifest:
    """Load ``configs/benchmarks/manifests/<manifest_id>.yaml``."""
    return BenchmarkManifest.model_validate(load_yaml(_manifest_dir(paths) / f"{manifest_id}.yaml"))


# --------------------------------------------------------------------------- #
# Objective
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Objective:
    """The frozen ranking trade-off. Dimensionless, never seconds."""

    revision: str
    elapsed_second_penalty: float
    instruction_change_penalty: float
    finish_position_penalty: float
    terminal_failure_penalty: float


def load_objective(objective_id: str = "objective-v1", paths: Paths | None = None) -> Objective:
    """Read the coordinator-owned objective. This module never writes it."""
    payload = load_yaml((paths or Paths.default()).configs / "objectives" / f"{objective_id}.yaml")
    utility = payload["utility"]
    return Objective(
        revision=str(payload["id"]),
        elapsed_second_penalty=float(utility["elapsed_second_penalty"]["value"]),
        instruction_change_penalty=float(utility["instruction_change_penalty"]["value"]),
        finish_position_penalty=float(utility["finish_position_penalty"]["value"]),
        terminal_failure_penalty=float(utility["terminal_failure_penalty"]["value"]),
    )


def objective_utility(outcome: RunOutcome, objective: Objective) -> float:
    """The declared dimensionless utility of one run. Higher is better.

    Physical outcomes stay reported separately; this number never replaces them.
    """
    if outcome.elapsed_time_s is None or outcome.final_position is None:
        raise ValueError(f"run {outcome.key} has no measured outcome to score")
    penalty = (
        objective.elapsed_second_penalty * outcome.elapsed_time_s
        + objective.instruction_change_penalty * outcome.instruction_changes
        + objective.finish_position_penalty * (outcome.final_position - 1)
    )
    if outcome.terminal_failure:
        penalty += objective.terminal_failure_penalty
    return -penalty


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CheckpointOutcome:
    """What happened at one named checkpoint. A checkpoint never reached is
    recorded as unreached; it is never quietly replaced by an earlier one."""

    checkpoint_id: str
    reached: bool
    elapsed_time_s: float | None
    energy_j: float | None
    incomplete_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "reached": self.reached,
            "elapsed_time_s": self.elapsed_time_s,
            "energy_j": self.energy_j,
            "incomplete_reason": self.incomplete_reason,
        }


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """One controller on one ``(scenario, seed)`` unit."""

    scenario_id: str
    seed: int
    family: str
    controller: str
    status: Literal["completed", "unavailable", "failed"]
    snapshot_hash: str
    horizon_s: float
    dt_s: float

    elapsed_time_s: float | None = None
    final_progress_m: float | None = None
    final_position: int | None = None
    final_energy_j: float | None = None
    checkpoints: tuple[CheckpointOutcome, ...] = ()
    retained_pass: bool | None = None
    retention_checkpoint_id: str | None = None

    decisions: int = 0
    withdrawn_decisions: int = 0
    timeouts: int = 0
    instruction_changes: int = 0
    modelled_violations: int = 0
    saturation_events: int = 0
    envelope_exceedances: int = 0
    terminal_failure: bool = False

    latency_ms: tuple[float, ...] = ()
    rival_final_progress_m: dict[str, float] = field(default_factory=dict)
    """Where each rival actually ended up in *this* branch.

    Recorded because it is the physical evidence that the opponents re-decided
    rather than being replayed: two branches that differ in the ego's behaviour
    must show different rival trajectories whenever the ego's behaviour changed
    anything the opponent policy reacts to."""

    reason_counts: dict[str, int] = field(default_factory=dict)
    rival_action_log: tuple[dict[str, Any], ...] = ()
    failure_category: FailureCategory | None = None
    detail: str | None = None

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.scenario_id, self.seed, self.controller)

    @property
    def measured(self) -> bool:
        return self.status == "completed"

    @property
    def withdrawal_rate(self) -> float | None:
        if self.decisions == 0:
            return None
        return self.withdrawn_decisions / self.decisions

    def checkpoint(self, checkpoint_id: str) -> CheckpointOutcome | None:
        for item in self.checkpoints:
            if item.checkpoint_id == checkpoint_id:
                return item
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "family": self.family,
            "controller": self.controller,
            "status": self.status,
            "snapshot_hash": self.snapshot_hash,
            "elapsed_time_s": self.elapsed_time_s,
            "final_progress_m": self.final_progress_m,
            "final_position": self.final_position,
            "final_energy_j": self.final_energy_j,
            "checkpoints": [c.as_dict() for c in self.checkpoints],
            "retained_pass": self.retained_pass,
            "retention_checkpoint_id": self.retention_checkpoint_id,
            "decisions": self.decisions,
            "withdrawn_decisions": self.withdrawn_decisions,
            "timeouts": self.timeouts,
            "instruction_changes": self.instruction_changes,
            "modelled_violations": self.modelled_violations,
            "saturation_events": self.saturation_events,
            "envelope_exceedances": self.envelope_exceedances,
            "terminal_failure": self.terminal_failure,
            "latency_p50_ms": percentile(self.latency_ms, 50.0),
            "latency_p95_ms": percentile(self.latency_ms, 95.0),
            "latency_p99_ms": percentile(self.latency_ms, 99.0),
            "rival_final_progress_m": dict(self.rival_final_progress_m),
            "reason_counts": dict(self.reason_counts),
            "failure_category": None if self.failure_category is None else self.failure_category.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    """Environment and hardware, recorded with every result."""

    python_version: str
    platform: str
    processor: str
    numpy_version: str
    scipy_version: str | None
    pydantic_version: str
    evaluator_version: str
    metrics_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "python_version": self.python_version,
            "platform": self.platform,
            "processor": self.processor,
            "numpy_version": self.numpy_version,
            "scipy_version": self.scipy_version,
            "pydantic_version": self.pydantic_version,
            "evaluator_version": self.evaluator_version,
            "metrics_version": self.metrics_version,
        }

    @property
    def hardware(self) -> str:
        return f"{self.platform} / {self.processor or 'unknown processor'}"


def environment_record() -> EnvironmentRecord:
    import pydantic

    try:
        import scipy

        scipy_version: str | None = scipy.__version__
    except Exception:  # pragma: no cover - scipy is a declared dependency
        scipy_version = None
    return EnvironmentRecord(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        processor=platform.processor(),
        numpy_version=np.__version__,
        scipy_version=scipy_version,
        pydantic_version=pydantic.VERSION,
        evaluator_version=EVALUATOR_VERSION,
        metrics_version=METRICS_VERSION,
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """A percentile, or ``None`` when there is nothing to compute it from."""
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """Raw paired results for one manifest, before any aggregation."""

    manifest: BenchmarkManifest
    manifest_hash: str
    environment: EnvironmentRecord
    started_at: datetime
    finished_at: datetime
    outcomes: tuple[RunOutcome, ...]
    controller_names: tuple[str, ...]
    unavailable_controllers: tuple[str, ...]
    failed_runs: tuple[dict[str, Any], ...] = ()
    rerun_command: str | None = None

    def for_controller(self, controller: str) -> tuple[RunOutcome, ...]:
        return tuple(o for o in self.outcomes if o.controller == controller)

    def measured_units(self, controller: str) -> int:
        return sum(1 for o in self.for_controller(controller) if o.measured)

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest.id,
            "manifest_hash": self.manifest_hash,
            "split": self.manifest.split,
            "environment": self.environment.as_dict(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "controller_names": list(self.controller_names),
            "unavailable_controllers": list(self.unavailable_controllers),
            "outcomes": [o.as_dict() for o in self.outcomes],
            "failed_runs": [dict(f) for f in self.failed_runs],
            "rerun_command": self.rerun_command,
        }


# --------------------------------------------------------------------------- #
# Rule context for a controller tick
# --------------------------------------------------------------------------- #

OWN_ENERGY_UNAVAILABLE = "own_energy_unavailable"


def controller_rule_context(
    observation: Observation,
    pack: RulePack,
    *,
    session_id: str,
    eligibility: EligibilityState = EligibilityState.UNKNOWN,
    temperature_available: bool = True,
) -> tuple[RuleContext | None, tuple[str, ...]]:
    """Resolve the rule context a controller sees, from its observation alone.

    When the own-energy channel is unavailable the context is resolved at the
    regulated energy floor. That is a *fail-closed* substitution, not a
    measurement: it removes every profile that requires usable energy, and the
    gap is returned in ``capability_gaps`` so the caller and the report can both
    see that the answer rests on an absent channel rather than on a reading of
    zero.
    """
    if "progress_m" not in observation.channels:
        return None, ("observation_unavailable",)
    gaps: list[str] = []
    manifest = pack.manifest
    if observation.has("battery_energy_j"):
        energy_j = observation.get("battery_energy_j")
    else:
        gaps.append(OWN_ENERGY_UNAVAILABLE)
        energy_j = float(manifest.battery_energy_min_j or 0.0)
    if not temperature_available:
        gaps.append("battery_temperature_unavailable")
    car_state = RuleCarState(
        speed_mps=max(0.0, observation.get("speed_mps")),
        battery_energy_j=max(0.0, energy_j),
        temperature_k=observation.get("battery_temperature_k") if temperature_available else None,
        recharge_used_this_lap_j=max(0.0, observation.get("recharge_this_lap_j")),
        eligibility=eligibility,
        lap_index=int(observation.get("lap")),
    )
    context = resolve_pack_context(
        pack,
        # Progress carries measurement noise, so a sample taken just after the
        # timing line can read slightly negative. The rule context is resolved at
        # a non-negative progress; the raw observation is not modified.
        max(0.0, observation.get("progress_m")),
        observation.delivered_at_s,
        car_state,
        session_id=session_id,
    )
    return context, tuple(gaps)


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _position_of(simulator: Simulator, ego: str) -> int:
    ego_progress = simulator.world.cars[ego].progress_m
    return 1 + sum(
        1
        for car_id, state in simulator.world.cars.items()
        if car_id != ego and state.progress_m > ego_progress
    )


def _run_one(
    *,
    bundle: ScenarioBundle,
    manifest: BenchmarkManifest,
    pack: RulePack,
    controller: Controller,
    seed: int,
    expected_model_bundle_hash: str | None,
    offered_model_bundle_hash: str | None,
) -> RunOutcome:
    """One controller, one scenario, one seed, in its own simulator."""
    scenario = bundle.scenario
    ego = scenario.ego_car_id
    family = manifest.family_of(scenario.id)

    simulator = Simulator()
    simulator.reset(bundle, seed=seed)
    start_snapshot = simulator.snapshot()
    digest = snapshot_hash(start_snapshot)
    start_time = simulator.session_time_s

    wanted = manifest.checkpoint_ids or scenario.evaluation_checkpoints
    checkpoint_targets = tuple(cp for cp in wanted if cp in bundle.track.checkpoint_ids)

    decisions = 0
    withdrawn = 0
    timeouts = 0
    changes = 0
    violations = 0
    latency: list[float] = []
    reasons: dict[str, int] = {}
    rival_log: list[dict[str, Any]] = []
    unavailable_ticks = 0
    last_profile: DeploymentProfile | None = None
    next_decision_at = start_time
    saturation = 0
    exceedances = 0
    detail: str | None = None
    failure: FailureCategory | None = None

    while simulator.session_time_s - start_time < manifest.horizon_s - 1e-12:
        remaining = manifest.horizon_s - (simulator.session_time_s - start_time)
        step_s = min(manifest.dt_s, remaining)
        actions: dict[str, Any] | None = None

        if simulator.session_time_s + 1e-12 >= next_decision_at:
            next_decision_at += manifest.decision_interval_s
            observation = simulator.observe(car_id=ego)[ego]
            context, gaps = controller_rule_context(observation, pack, session_id=f"{scenario.id}:{seed}")
            request = build_request(
                car_id=ego,
                session_time_s=simulator.session_time_s,
                observation=observation,
                rule_context=context,
                compute_budget_ms=manifest.compute_budget_ms,
                disturbance_keys=("wind", "grip", "sensor_noise", "driver_response"),
                expected_model_bundle_hash=expected_model_bundle_hash,
                offered_model_bundle_hash=offered_model_bundle_hash,
            )
            decision = _timed_decision(controller, request)
            decisions += 1
            latency.append(decision.latency_ms)
            for gap in gaps:
                reasons[gap] = reasons.get(gap, 0) + 1
            for reason in decision.reasons:
                reasons[reason.value] = reasons.get(reason.value, 0) + 1
            if decision.status is PlanningStatus.SOLVER_UNAVAILABLE:
                unavailable_ticks += 1
                detail = decision.detail
                if decisions == 1:
                    # A controller that is unavailable at its first tick has no
                    # implementation to evaluate. Simulating the rest of the
                    # horizon would manufacture a trajectory for a controller
                    # that never acted, so the run stops and is labelled.
                    return RunOutcome(
                        scenario_id=scenario.id,
                        seed=seed,
                        family=family,
                        controller=controller.name,
                        status="unavailable",
                        snapshot_hash=digest,
                        horizon_s=manifest.horizon_s,
                        dt_s=manifest.dt_s,
                        decisions=decisions,
                        withdrawn_decisions=1,
                        reason_counts=reasons,
                        detail=detail or "controller reported itself unavailable at its first decision tick",
                    )
            if decision.latency_ms > manifest.compute_budget_ms or (
                decision.status is PlanningStatus.DEADLINE_EXCEEDED
            ):
                # A late result is ignored, exactly as the serving spec requires.
                timeouts += 1
                withdrawn += 1
            elif decision.withdrawn:
                withdrawn += 1
            else:
                action = decision.action
                assert action is not None
                if context is not None and action.profile not in context.admissible_profiles:
                    violations += 1
                if last_profile is not None and action.profile is not last_profile:
                    changes += 1
                last_profile = action.profile
                actions = {ego: action}

        report = simulator.step(actions, step_s)
        saturation += len(report.saturation_events)
        exceedances += len(report.envelope_exceedances)
        if report.policy_actions:
            rival_log.append(
                {
                    "session_time_s": report.session_time_s,
                    "actions": {
                        car_id: rival.as_dict() for car_id, rival in sorted(report.policy_actions.items())
                    },
                }
            )

    if decisions and unavailable_ticks == decisions:
        return RunOutcome(
            scenario_id=scenario.id,
            seed=seed,
            family=family,
            controller=controller.name,
            status="unavailable",
            snapshot_hash=digest,
            horizon_s=manifest.horizon_s,
            dt_s=manifest.dt_s,
            decisions=decisions,
            withdrawn_decisions=withdrawn,
            reason_counts=reasons,
            detail=detail or "controller reported itself unavailable at every decision tick",
        )

    records = {
        (record.checkpoint_id, record.car_id): record
        for record in simulator.world.checkpoint_records
        if record.car_id == ego
    }
    checkpoints = tuple(
        CheckpointOutcome(
            checkpoint_id=checkpoint_id,
            reached=(checkpoint_id, ego) in records,
            elapsed_time_s=(
                records[(checkpoint_id, ego)].session_time_s - start_time
                if (checkpoint_id, ego) in records
                else None
            ),
            energy_j=(
                records[(checkpoint_id, ego)].battery_energy_j if (checkpoint_id, ego) in records else None
            ),
            incomplete_reason=(
                None
                if (checkpoint_id, ego) in records
                else "evaluation horizon reached before the ego car crossed this checkpoint"
            ),
        )
        for checkpoint_id in checkpoint_targets
    )

    retention_id = scenario.retention_checkpoint_id
    retained: bool | None = None
    if retention_id is not None:
        retained = any(
            record.kind == "retained_pass"
            and record.overtaking_car_id == ego
            and record.checkpoint_id == retention_id
            for record in simulator.world.passes
        )

    energy = simulator.world.ledgers[ego].energy_j
    terminal_failure = energy <= simulator.world.ledgers[ego].energy_min_j + 1e-9
    if terminal_failure:
        failure = FailureCategory.ENERGY_DEPLETION
    elif violations:
        failure = FailureCategory.INFEASIBLE_PROJECTION
    elif timeouts:
        failure = FailureCategory.PLANNER_TIMEOUT

    return RunOutcome(
        scenario_id=scenario.id,
        seed=seed,
        family=family,
        controller=controller.name,
        status="completed",
        snapshot_hash=digest,
        horizon_s=manifest.horizon_s,
        dt_s=manifest.dt_s,
        elapsed_time_s=simulator.session_time_s - start_time,
        final_progress_m=simulator.world.cars[ego].progress_m,
        final_position=_position_of(simulator, ego),
        final_energy_j=energy,
        checkpoints=checkpoints,
        retained_pass=retained,
        retention_checkpoint_id=retention_id,
        decisions=decisions,
        withdrawn_decisions=withdrawn,
        timeouts=timeouts,
        instruction_changes=changes,
        modelled_violations=violations,
        saturation_events=saturation,
        envelope_exceedances=exceedances,
        terminal_failure=terminal_failure,
        latency_ms=tuple(latency),
        rival_final_progress_m={
            car_id: state.progress_m
            for car_id, state in sorted(simulator.world.cars.items())
            if car_id != ego
        },
        reason_counts=reasons,
        rival_action_log=tuple(rival_log),
        failure_category=failure,
        detail=detail,
    )


def _timed_decision(controller: Controller, request: ControlRequest) -> ControlDecision:
    """Call a controller and stamp the wall-clock cost the harness observed.

    The harness's own measurement is authoritative: a controller cannot report a
    latency lower than the time it actually took.
    """
    started = time.perf_counter()
    decision = controller.decide(request)
    observed_ms = (time.perf_counter() - started) * 1000.0
    if decision.latency_ms >= observed_ms:
        return decision
    return ControlDecision(
        controller=decision.controller,
        status=decision.status,
        action=decision.action,
        reasons=decision.reasons,
        latency_ms=observed_ms,
        provenance=decision.provenance,
        detail=decision.detail,
    )


def run_benchmark(
    manifest: BenchmarkManifest,
    controllers: Sequence[Controller],
    *,
    paths: Paths | None = None,
    expected_model_bundle_hash: str | None = None,
    offered_model_bundle_hashes: Mapping[str, str] | None = None,
    rerun_command: str | None = None,
) -> BenchmarkRun:
    """Run every controller over every ``(scenario, seed)`` unit of ``manifest``.

    Every run is independent: its own simulator, restored from the same frozen
    scenario and seed, with the opponents re-deciding from their own
    observations. A run that raises is recorded in ``failed_runs`` with the
    exception text; it is never dropped, because a discarded environment error
    is a reproducibility defect rather than a low-reward episode.
    """
    if not controllers:
        raise ValueError("a benchmark needs at least one controller")
    names = [c.name for c in controllers]
    if len(set(names)) != len(names):
        raise ValueError("controller names must be unique inside one benchmark")

    pack = load_rule_pack(manifest.rule_pack_id, paths)
    started_at = datetime.now(UTC)
    outcomes: list[RunOutcome] = []
    failures: list[dict[str, Any]] = []
    offered = dict(offered_model_bundle_hashes or {})

    for scenario_id in manifest.scenario_ids:
        bundle = load_bundle(scenario_id, paths)
        for seed in manifest.seeds:
            for controller in controllers:
                try:
                    outcomes.append(
                        _run_one(
                            bundle=bundle,
                            manifest=manifest,
                            pack=pack,
                            controller=controller,
                            seed=seed,
                            expected_model_bundle_hash=expected_model_bundle_hash,
                            offered_model_bundle_hash=offered.get(controller.name),
                        )
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "scenario_id": scenario_id,
                            "seed": seed,
                            "controller": controller.name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    outcomes.append(
                        RunOutcome(
                            scenario_id=scenario_id,
                            seed=seed,
                            family=manifest.family_of(scenario_id),
                            controller=controller.name,
                            status="failed",
                            snapshot_hash="",
                            horizon_s=manifest.horizon_s,
                            dt_s=manifest.dt_s,
                            failure_category=FailureCategory.INFRASTRUCTURE_FAILURE,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    )

    unavailable = tuple(
        sorted(
            {
                outcome.controller
                for outcome in outcomes
                if outcome.status == "unavailable"
                and not any(other.controller == outcome.controller and other.measured for other in outcomes)
            }
        )
    )
    return BenchmarkRun(
        manifest=manifest,
        manifest_hash=manifest.manifest_hash,
        environment=environment_record(),
        started_at=started_at,
        finished_at=datetime.now(UTC),
        outcomes=tuple(outcomes),
        controller_names=tuple(names),
        unavailable_controllers=unavailable,
        failed_runs=tuple(failures),
        rerun_command=rerun_command
        or (f"./.venv/Scripts/python.exe -m afterlap_core.cli benchmark --manifest {manifest.id}"),
    )


__all__ += ["OWN_ENERGY_UNAVAILABLE", "Objective", "controller_rule_context", "percentile"]
