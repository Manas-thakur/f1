"""Paired branching from a single snapshot.

Implements the recipe in ``simulation/OPPONENTS_AND_BRANCHING.md``. Two
branches restored from the same snapshot share their exogenous disturbance keys
through :class:`~afterlap_core.rng.KeyedRandom` — wind, grip and sensor noise are
keyed by ``(scenario, seed, event_type, physical time bin)``, so reaching the
same physical instant draws the same disturbance no matter how many calls each
branch made to get there. Opponents, by contrast, genuinely re-decide: each
branch's policies react to that branch's own observations.

A candidate branch can never inspect the reference branch. The two are separate
``Simulator`` instances and the only comparison happens afterwards, on a common
checkpoint definition frozen before the run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from afterlap_contracts import SCHEMA_VERSION, CheckpointDefinition, OutcomeRecord, Provenance

from ..paths import sha256_json
from .engine import Simulator
from .observation import Observation
from .policies import DriverAction

if TYPE_CHECKING:
    from .config import ScenarioBundle
    from .state import CheckpointRecord

Controller = Callable[[Observation], DriverAction]


@dataclass(frozen=True, slots=True)
class Treatment:
    """One experimental treatment: an identity plus the ego controller."""

    id: str
    controller: Controller
    description: str = ""


@dataclass(slots=True)
class BranchResult:
    """Everything a branch produced, aligned to a common checkpoint definition."""

    treatment_id: str
    snapshot_hash: str
    scenario_id: str
    ego_car_id: str
    horizon_s: float
    dt_s: float
    steps: int
    elapsed_time_s: float
    truncated: bool
    outcomes: tuple[OutcomeRecord, ...] = ()
    rival_actions: list[dict[str, Any]] = field(default_factory=list)
    final_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def outcome_by_checkpoint(self) -> dict[str, OutcomeRecord]:
        return {record.checkpoint.checkpoint_id: record for record in self.outcomes}

    @property
    def complete_outcomes(self) -> tuple[OutcomeRecord, ...]:
        return tuple(record for record in self.outcomes if record.incomplete_reason is None)


def capture_complete_state(simulator: Simulator) -> dict[str, Any]:
    """Snapshot every piece of mutable truth, ready for branching."""
    return simulator.snapshot()


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Stable identity of a snapshot, used in the experiment manifest."""
    return sha256_json(
        {
            "scenario_id": snapshot["scenario_id"],
            "bundle_hash": snapshot["bundle_hash"],
            "seed": snapshot["seed"],
            "session_time_s": snapshot["race"]["session_time_s"],
            "cars": snapshot["cars"],
            "ledgers": {
                car_id: {k: v for k, v in ledger.items() if k != "saturation_events"}
                for car_id, ledger in snapshot["ledgers"].items()
            },
        }
    )


def branch(bundle: ScenarioBundle, snapshot: dict[str, Any], treatment: Treatment) -> Simulator:
    """Restore an independent simulator from ``snapshot`` for one treatment.

    The treatment identity is not written into the world: it only decides which
    controller supplies the ego action, which is exactly the scope the plan
    requires for outcome identity.
    """
    del treatment
    simulator = Simulator()
    simulator.reset(bundle, seed=snapshot["seed"])
    simulator.restore(snapshot)
    return simulator


def run_branch(
    bundle: ScenarioBundle,
    snapshot: dict[str, Any],
    treatment: Treatment,
    *,
    horizon_s: float,
    dt_s: float,
    checkpoint_ids: tuple[str, ...] | None = None,
    decision_id: str | None = None,
) -> BranchResult:
    """Run one branch to the evaluation horizon and record its outcomes.

    Follows the pseudocode in ``OPPONENTS_AND_BRANCHING.md``: restore, install
    the treatment's controller, loop until the horizon, then record outcomes
    against the common checkpoint definition. A checkpoint the branch never
    reached produces an *incomplete* outcome record; it is never silently
    replaced by an earlier checkpoint.
    """
    if horizon_s <= 0.0:
        raise ValueError("an evaluation horizon must be positive")
    if dt_s <= 0.0:
        raise ValueError("the branch step must be positive")

    simulator = branch(bundle, snapshot, treatment)
    scenario = bundle.scenario
    ego = scenario.ego_car_id
    wanted = checkpoint_ids if checkpoint_ids is not None else scenario.evaluation_checkpoints
    start_time = simulator.session_time_s
    baseline_records = len(simulator.world.checkpoint_records)

    rival_actions: list[dict[str, Any]] = []
    steps = 0
    while simulator.session_time_s - start_time < horizon_s - 1e-12:
        remaining = horizon_s - (simulator.session_time_s - start_time)
        step = min(dt_s, remaining)
        observation = simulator.observe(car_id=ego)[ego]
        action = treatment.controller(observation)
        report = simulator.step({ego: action}, step)
        rival_actions.append(
            {
                "session_time_s": report.session_time_s,
                "actions": {
                    car_id: rival_action.as_dict()
                    for car_id, rival_action in sorted(report.policy_actions.items())
                },
            }
        )
        steps += 1

    new_records = simulator.world.checkpoint_records[baseline_records:]
    outcomes = _build_outcomes(
        bundle=bundle,
        treatment=treatment,
        records=new_records,
        wanted=wanted,
        horizon_s=horizon_s,
        simulator=simulator,
        start_time=start_time,
        decision_id=decision_id,
    )
    truncated = any(record.incomplete_reason is not None for record in outcomes)
    return BranchResult(
        treatment_id=treatment.id,
        snapshot_hash=snapshot_hash(snapshot),
        scenario_id=scenario.id,
        ego_car_id=ego,
        horizon_s=horizon_s,
        dt_s=dt_s,
        steps=steps,
        elapsed_time_s=simulator.session_time_s - start_time,
        truncated=truncated,
        outcomes=outcomes,
        rival_actions=rival_actions,
        final_snapshot=simulator.snapshot(),
    )


def _build_outcomes(
    *,
    bundle: ScenarioBundle,
    treatment: Treatment,
    records: list[CheckpointRecord],
    wanted: tuple[str, ...],
    horizon_s: float,
    simulator: Simulator,
    start_time: float,
    decision_id: str | None,
) -> tuple[OutcomeRecord, ...]:
    ego = bundle.scenario.ego_car_id
    by_checkpoint = {record.checkpoint_id: record for record in records if record.car_id == ego}
    outcomes: list[OutcomeRecord] = []
    for checkpoint_id in wanted:
        track_checkpoint = bundle.track.checkpoint(checkpoint_id)
        record = by_checkpoint.get(checkpoint_id)
        definition = CheckpointDefinition(
            checkpoint_id=checkpoint_id,
            progress_m=(record.progress_m if record is not None else float(track_checkpoint.s_m.value)),
            description=track_checkpoint.description,
        )
        if record is None:
            outcomes.append(
                OutcomeRecord(
                    schema_version=SCHEMA_VERSION,
                    id=f"{treatment.id}:{checkpoint_id}:incomplete",
                    session_id=bundle.scenario.id,
                    decision_id=decision_id,
                    checkpoint=definition,
                    evaluation_horizon_s=horizon_s,
                    event_observed=False,
                    elapsed_time_s=None,
                    energy_j=None,
                    provenance=Provenance.SIMULATED,
                    incomplete_reason=(
                        "evaluation horizon reached before the ego car crossed this checkpoint; "
                        "this branch is not comparable at this checkpoint"
                    ),
                )
            )
            continue
        position = 1 + sum(
            1
            for car_id, state in simulator.world.cars.items()
            if car_id != ego and state.progress_m > simulator.world.cars[ego].progress_m
        )
        outcomes.append(
            OutcomeRecord(
                schema_version=SCHEMA_VERSION,
                id=f"{treatment.id}:{checkpoint_id}",
                session_id=bundle.scenario.id,
                decision_id=decision_id,
                checkpoint=definition,
                evaluation_horizon_s=horizon_s,
                event_observed=True,
                elapsed_time_s=record.session_time_s - start_time,
                energy_j=record.battery_energy_j,
                position=position,
                provenance=Provenance.SIMULATED,
            )
        )
    return tuple(outcomes)


def run_paired(
    bundle: ScenarioBundle,
    snapshot: dict[str, Any],
    treatments: tuple[Treatment, ...],
    *,
    horizon_s: float,
    dt_s: float,
    checkpoint_ids: tuple[str, ...] | None = None,
) -> dict[str, BranchResult]:
    """Run several treatments from one snapshot and return them by treatment id."""
    ids = [treatment.id for treatment in treatments]
    if len(set(ids)) != len(ids):
        raise ValueError("treatment ids must be unique inside one paired comparison")
    return {
        treatment.id: run_branch(
            bundle,
            snapshot,
            treatment,
            horizon_s=horizon_s,
            dt_s=dt_s,
            checkpoint_ids=checkpoint_ids,
        )
        for treatment in treatments
    }


__all__ = [
    "BranchResult",
    "Controller",
    "Treatment",
    "branch",
    "capture_complete_state",
    "run_branch",
    "run_paired",
    "snapshot_hash",
]
