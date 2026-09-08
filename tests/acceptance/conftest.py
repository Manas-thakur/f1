"""Fixtures for the cross-module acceptance suite.

Imported relatively (``from .conftest import ...``) per decision D-03: a bare
top-level ``conftest`` module collides with the other suites' fixture files.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from afterlap_contracts import (
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    PlanningStatus,
    ReasonCode,
    StateEstimate,
    fixtures,
)
from afterlap_core.evaluation.controllers import ControlDecision, Controller, build_request
from afterlap_core.evaluation.harness import controller_rule_context
from afterlap_core.rules import RulePack, load_rule_pack
from afterlap_core.simulation import Simulator, load_bundle
from afterlap_core.simulation.policies import DriverAction

if TYPE_CHECKING:
    from afterlap_core.simulation.config import ScenarioBundle
    from afterlap_core.simulation.observation import Observation

DT_S = 0.02
DECISION_INTERVAL_S = 1.0
COMPUTE_BUDGET_MS = 200.0
SCENARIO_ID = "two-straight-counterattack"
RULE_PACK_ID = "synthetic-pack-v1"


@pytest.fixture(scope="session")
def bundle() -> ScenarioBundle:
    return load_bundle(SCENARIO_ID)


@pytest.fixture(scope="session")
def rule_pack() -> RulePack:
    return load_rule_pack(RULE_PACK_ID)


@dataclass(slots=True)
class SliceTrace:
    """Everything one closed-loop run produced, for assertions afterwards."""

    decisions: list[ControlDecision]
    observations: list[dict[str, Any]]
    contexts: list[Any]
    capability_gaps: list[tuple[str, ...]]
    final_progress_m: float
    final_energy_j: float
    final_position: int
    rival_progress_m: dict[str, float]
    rival_energy_j: dict[str, float]
    rival_actions: list[dict[str, Any]]
    passes: list[dict[str, Any]]
    checkpoints: list[tuple[str, int, float]]
    snapshot: dict[str, Any]


def run_slice(
    bundle: ScenarioBundle,
    pack: RulePack,
    controller: Controller,
    *,
    horizon_s: float,
    seed: int | None = None,
    simulator: Simulator | None = None,
    eligibility: EligibilityState = EligibilityState.UNKNOWN,
    compute_budget_ms: float = COMPUTE_BUDGET_MS,
) -> SliceTrace:
    """Scenario -> step -> observation -> rules -> checked plan -> outcome.

    The only path from the world to the controller is ``Simulator.observe``, and
    the only path from the controller to the world is a ``DriverAction`` handed
    to ``Simulator.step``. Nothing in this loop reads ``Simulator.world`` on the
    controller's behalf.
    """
    if simulator is None:
        simulator = Simulator()
        simulator.reset(bundle, seed=seed)
    ego = bundle.scenario.ego_car_id
    start = simulator.session_time_s
    next_decision = start
    trace = SliceTrace(
        decisions=[],
        observations=[],
        contexts=[],
        capability_gaps=[],
        final_progress_m=0.0,
        final_energy_j=0.0,
        final_position=1,
        rival_progress_m={},
        rival_energy_j={},
        rival_actions=[],
        passes=[],
        checkpoints=[],
        snapshot={},
    )

    while simulator.session_time_s - start < horizon_s - 1e-12:
        step_s = min(DT_S, horizon_s - (simulator.session_time_s - start))
        actions = None
        if simulator.session_time_s + 1e-12 >= next_decision:
            next_decision += DECISION_INTERVAL_S
            observation = simulator.observe(car_id=ego)[ego]
            context, gaps = controller_rule_context(
                observation, pack, session_id="acceptance", eligibility=eligibility
            )
            request = build_request(
                car_id=ego,
                session_time_s=simulator.session_time_s,
                observation=observation,
                rule_context=context,
                compute_budget_ms=compute_budget_ms,
                disturbance_keys=("wind", "grip", "sensor_noise", "driver_response"),
            )
            decision = controller.decide(request)
            trace.decisions.append(decision)
            trace.observations.append(observation.as_plain())
            trace.contexts.append(context)
            trace.capability_gaps.append(gaps)
            if decision.action is not None:
                actions = {ego: decision.action}
        report = simulator.step(actions, step_s)
        if report.policy_actions:
            trace.rival_actions.append(
                {
                    "session_time_s": report.session_time_s,
                    "actions": {
                        car_id: action.as_dict() for car_id, action in sorted(report.policy_actions.items())
                    },
                }
            )

    world = simulator.world
    trace.final_progress_m = world.cars[ego].progress_m
    trace.final_energy_j = world.ledgers[ego].energy_j
    trace.final_position = 1 + sum(
        1
        for car_id, state in world.cars.items()
        if car_id != ego and state.progress_m > world.cars[ego].progress_m
    )
    trace.rival_progress_m = {
        car_id: state.progress_m for car_id, state in sorted(world.cars.items()) if car_id != ego
    }
    trace.rival_energy_j = {
        car_id: ledger.energy_j for car_id, ledger in sorted(world.ledgers.items()) if car_id != ego
    }
    trace.passes = [record.as_dict() for record in world.passes]
    trace.checkpoints = [
        (record.checkpoint_id, record.lap, record.session_time_s)
        for record in world.checkpoint_records
        if record.car_id == ego
    ]
    trace.snapshot = simulator.snapshot()
    return trace


def estimate_from_observation(
    observation: Observation,
    *,
    now_s: float,
    revision: int,
    track_length_m: float,
) -> StateEstimate:
    """Carry one simulator observation into the planner's estimate contract.

    Synthetic adapter. Only the channels the observation actually exposes are
    written; everything else keeps the contract fixture's value, which is
    labelled synthetic at source. A missing own-energy channel leaves the
    fixture's degraded-energy shape in place rather than inventing a number.
    """
    base = fixtures.state_estimate()
    at_s = observation.observed_at_s
    age_s = max(0.0, now_s - at_s)

    def scalar(field: Any, value: float) -> Any:
        return field.model_copy(update={"value": value, "observed_at_s": at_s, "age_s": age_s})

    updates: dict[str, Any] = {
        "speed_mps": scalar(base.own_car.speed_mps, observation.get("speed_mps")),
        "progress_m": scalar(base.own_car.progress_m, max(0.0, observation.get("progress_m"))),
        "lap_distance_m": scalar(base.own_car.lap_distance_m, max(0.0, observation.get("s_m"))),
        "acceleration_mps2": scalar(base.own_car.acceleration_mps2, observation.get("acceleration_mps2")),
        "battery_temperature_k": scalar(
            base.own_car.battery_temperature_k, observation.get("battery_temperature_k")
        ),
        "recharge_spent_this_lap_j": scalar(
            base.own_car.recharge_spent_this_lap_j,
            max(0.0, observation.get("recharge_this_lap_j")),
        ),
        "active_profile_id": observation.context["active_profile"],
    }
    if observation.has("battery_energy_j"):
        updates["battery_energy_j"] = scalar(
            base.own_car.battery_energy_j, observation.get("battery_energy_j")
        )
    own = base.own_car.model_copy(update=updates)

    rivals = []
    for rival in observation.rivals:
        template = base.rival_beliefs[0]
        is_ahead = float(rival["relative_progress_m"]) > 0.0
        rivals.append(
            template.model_copy(
                update={
                    "car_id": str(rival["car_id"]),
                    "slot": "ahead_1" if is_ahead else "behind_1",
                    "is_ahead": is_ahead,
                    "gap_s": scalar(template.gap_s, float(rival["gap_s"])),
                    "gap_m": scalar(template.gap_m, float(rival["relative_progress_m"])),
                    "relative_speed_mps": scalar(
                        template.relative_speed_mps, float(rival["relative_speed_mps"])
                    ),
                    "observation_age_s": age_s,
                }
            )
        )
    race = base.race_context.model_copy(update={"track_length_m": track_length_m})
    return base.model_copy(
        update={
            "own_car": own,
            "rival_beliefs": tuple(rivals),
            "race_context": race,
            "cutoff_s": at_s,
            "created_at_s": now_s,
            "revision": revision,
        }
    )


class MpcController:
    """The comparison matrix's MPC-only row, adapted to the controller protocol.

    A06's ``plan`` is called with no continuation model, so the learned
    contribution is disabled by construction and this is the *MPC-only* row, not
    the full system. The planner runs its own independent checker; a candidate it
    rejects never reaches the car, and a result that is not ``ok`` withdraws.
    """

    uses_actor = False
    uses_learned_return = False

    def __init__(self, pack: RulePack, bundle: ScenarioBundle, *, seed: int = 42) -> None:
        from afterlap_core.planning import PlanningWorld

        self._pack = pack
        self._bundle = bundle
        self._seed = seed
        self._world = PlanningWorld.from_scenario(bundle.scenario.id, seed=seed)
        self._revision = 0
        self.results: list[Any] = []

    @property
    def name(self) -> str:
        return "mpc_only"

    def decide(self, request: Any) -> ControlDecision:
        from afterlap_core.planning import plan

        if request.rule_context is None or not request.observation.channels:
            return ControlDecision(
                controller=self.name,
                status=PlanningStatus.INPUT_UNAVAILABLE,
                action=None,
                reasons=(ReasonCode.STALE_OBSERVATIONS,),
                provenance="withdrawn",
                detail="no observation old enough to plan from",
            )
        self._revision += 1
        estimate = estimate_from_observation(
            request.observation,
            now_s=request.session_time_s,
            revision=self._revision,
            track_length_m=self._bundle.track.length,
        )
        started = time.perf_counter()
        result = plan(
            estimate,
            request.rule_context,
            None,
            max(0.05, request.compute_budget_ms / 1000.0),
            manifest=self._pack.manifest,
            world=self._world,
            now_s=request.session_time_s,
            seed=self._seed,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.results.append(result)

        if result.status is not PlanningStatus.OK or result.selected_plan_id is None:
            return ControlDecision(
                controller=self.name,
                status=result.status,
                action=None,
                reasons=result.reason_codes,
                latency_ms=latency_ms,
                provenance="withdrawn",
                detail=result.detail,
            )
        selected = next(c for c in result.accepted if c.id == result.selected_plan_id)
        if selected.constraint_result.status is not CheckStatus.PASS:
            return ControlDecision(
                controller=self.name,
                status=PlanningStatus.NO_FEASIBLE_CANDIDATE,
                action=None,
                reasons=(*result.reason_codes, ReasonCode.ELIGIBILITY_UNKNOWN),
                latency_ms=latency_ms,
                provenance="withdrawn",
                detail=f"selected plan carried a {selected.constraint_result.status.value} verdict",
            )
        profile: DeploymentProfile = selected.profile_segments[0].profile_id
        return ControlDecision(
            controller=self.name,
            status=PlanningStatus.OK,
            action=DriverAction(profile=profile, issued_at_s=request.session_time_s, label=selected.id),
            reasons=result.reason_codes,
            latency_ms=latency_ms,
            provenance=result.baseline_identity,
        )


@pytest.fixture(scope="module")
def mpc_controller(rule_pack: RulePack, bundle: ScenarioBundle) -> MpcController:
    return MpcController(rule_pack, bundle)
