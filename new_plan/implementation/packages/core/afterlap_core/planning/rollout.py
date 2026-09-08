"""Re-simulation of finalists against sampled rival scenarios.

The solver works on a smooth reduced model. Before a candidate can be accepted
it is re-run through the full simulator, with the rivals **reacting** through
their frozen policies rather than replaying a fixed trace: each scenario builds
its own variant of the scenario document (the rival's stored energy and its
behavioural mode) and lets the policy decide from its own observations. A plan
that only works against a rival who ignores it will therefore not survive.

The planner never reads ``WorldState``. Everything here comes from the public
branching API: :func:`~afterlap_core.simulation.run_branch` and the plain-data
snapshot it returns.

Two separate events
-------------------

``pass_before(checkpoint)`` and ``ahead_at(checkpoint)`` are *different* events
and are computed differently:

* ``pass_before`` is true when the simulator recorded a completed pass of the
  rival at or before the moment our car crossed the checkpoint line. A completed
  pass already requires full longitudinal clearance and non-overlapping
  footprints, so a contact-blocked move does not count.
* ``ahead_at`` is true when our car crossed the checkpoint line strictly before
  the rival crossed the same line, or the rival did not reach it inside the
  horizon. It is evaluated at common progress, not by dividing a gap by a speed.

They differ exactly when a pass is completed and then lost again before the
line, which is the case the greedy-pass test constructs.

Both are reported as weighted scenario frequencies with their sample counts and
``calibration_status=uncalibrated``: no calibrator exists yet, and a raw
frequency must never be published as a calibrated probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from afterlap_contracts import (
    CalibrationStatus,
    CheckpointOutcome,
    DeploymentProfile,
    ProbabilityStatement,
    ProfileSegment,
    ScenarioOutcome,
    StateEstimate,
)

from ..simulation import (
    DriverAction,
    Observation,
    ScenarioBundle,
    Simulator,
    Treatment,
    capture_complete_state,
    run_branch,
)
from ..simulation.config import resolve_bundle
from .config import PlannerConfig
from .scenarios import PlanScenario
from .segments import PlanFrame
from .surrogate import SurrogateWeights

__all__ = ["PlanningWorld", "RolloutEvidence", "SegmentController", "rollout_candidate"]

_COMPLETED_PASS = "completed_pass"


@dataclass(frozen=True, slots=True)
class PlanningWorld:
    """The simulator configuration the planner re-simulates against.

    Synthetic in every shipped configuration. It is a reduced physical model with
    documented assumptions, not a digital twin of any car or circuit, and a
    rollout result is evidence about *this model* only.
    """

    bundle: ScenarioBundle
    ego_car_id: str
    rival_car_id: str | None
    seed: int

    @classmethod
    def from_scenario(cls, scenario_id: str = "two-straight-counterattack", *, seed: int = 20260908):
        """Build a planning world for a scenario, under the conditions it names.

        ``resolve_bundle`` rather than ``load_bundle``: a real-circuit scenario
        names a weather tape, and a planner that re-simulated under still, dry
        reference air while the session ran under that tape would advise on a
        car it was not driving.
        """
        bundle = resolve_bundle(scenario_id, seed=seed)
        rivals = bundle.scenario.rival_ids
        return cls(
            bundle=bundle,
            ego_car_id=bundle.scenario.ego_car_id,
            rival_car_id=rivals[0] if rivals else None,
            seed=seed,
        )

    @property
    def checkpoint_ids(self) -> tuple[str, ...]:
        return self.bundle.track.checkpoint_ids


@dataclass(frozen=True, slots=True)
class RolloutEvidence:
    """What the re-simulation produced for one candidate."""

    outcomes: tuple[ScenarioOutcome, ...]
    probabilities: tuple[ProbabilityStatement, ...]
    expected_utility: float
    sample_count: int
    step_s: float
    horizon_s: float
    incomplete_count: int
    """Scenarios in which the reference progress was not reached inside the horizon."""


class SegmentController:
    """Executes a plan: the profile of whatever segment the car is in.

    Only the profile is commanded. The energy budget inside a segment is realised
    by the simulator's own profile model and the driver's execution delay, which
    is the point of expressing control as instructions rather than as a power
    trace: the planner cannot pretend a human tracked a millisecond schedule.
    """

    __slots__ = ("_bounds", "_fallback")

    def __init__(self, segments: tuple[ProfileSegment, ...], fallback: DeploymentProfile) -> None:
        self._bounds = tuple(
            (segment.start_progress_m, segment.end_progress_m, segment.profile_id) for segment in segments
        )
        self._fallback = fallback

    def __call__(self, observation: Observation) -> DriverAction:
        if not observation.has("progress_m"):
            return DriverAction(profile=self._fallback, label="plan:no_observation")
        progress = observation.get("progress_m")
        for start, end, profile in self._bounds:
            if start <= progress < end:
                return DriverAction(profile=profile, label=f"plan:{profile.value}")
        return DriverAction(profile=self._fallback, label="plan:outside_corridor")


def _variant_bundle(
    world: PlanningWorld,
    estimate: StateEstimate,
    scenario: PlanScenario,
) -> ScenarioBundle:
    """A scenario document placed at the current belief, with this rival hypothesis.

    The rival's stored energy and behavioural mode are the sampled quantities.
    Its *policy* still decides from its own observations, so it reacts to what we
    do inside the rollout instead of replaying a recorded trace.
    """
    scenario_config = world.bundle.scenario
    own = estimate.own_car
    states = dict(scenario_config.initial_states)

    ego_state = states[world.ego_car_id]
    states[world.ego_car_id] = ego_state.model_copy(
        update={
            "progress_m": ego_state.progress_m.model_copy(
                update={"value": float(own.progress_m.value or 0.0)}
            ),
            "speed_mps": ego_state.speed_mps.model_copy(update={"value": float(own.speed_mps.value or 1.0)}),
            "energy_j": ego_state.energy_j.model_copy(
                update={"value": float(own.battery_energy_j.value or 0.0)}
            ),
            "temperature_k": ego_state.temperature_k.model_copy(
                update={"value": float(own.battery_temperature_k.value or 300.0)}
            ),
        }
    )

    policies = dict(scenario_config.opponent_policies)
    rival_id = world.rival_car_id
    if rival_id is not None:
        rival_state = states[rival_id]
        belief = estimate.nearest_ahead or estimate.nearest_behind
        offset_m = 0.0
        if belief is not None and belief.gap_m.value is not None:
            offset_m = float(belief.gap_m.value)
        rival_progress = max(0.0, float(own.progress_m.value or 0.0) + offset_m)
        states[rival_id] = rival_state.model_copy(
            update={
                "progress_m": rival_state.progress_m.model_copy(update={"value": rival_progress}),
                "speed_mps": rival_state.speed_mps.model_copy(
                    update={"value": float(own.speed_mps.value or 1.0)}
                ),
                "energy_j": rival_state.energy_j.model_copy(update={"value": scenario.rival_reserve_j}),
            }
        )
        spec = policies[rival_id]
        policies[rival_id] = spec.model_copy(update={"kind": scenario.intention.value})

    updated = scenario_config.model_copy(
        update={"initial_states": states, "opponent_policies": policies, "gap_ahead_s": None}
    )
    return ScenarioBundle(scenario=updated, track=world.bundle.track, car_configs=world.bundle.car_configs)


def _crossings(snapshot: dict[str, Any], car_id: str, start_time_s: float) -> dict[str, float]:
    """Session times at which ``car_id`` crossed each checkpoint after the branch start."""
    times: dict[str, float] = {}
    for record in snapshot.get("checkpoint_records", []):
        if record["car_id"] != car_id or record["session_time_s"] < start_time_s - 1e-9:
            continue
        times.setdefault(record["checkpoint_id"], float(record["session_time_s"]))
    return times


def _completed_pass_times(snapshot: dict[str, Any], ego: str, rival: str | None) -> list[float]:
    return [
        float(record["session_time_s"])
        for record in snapshot.get("passes", [])
        if record["kind"] == _COMPLETED_PASS
        and record["overtaking_car_id"] == ego
        and (rival is None or record["overtaken_car_id"] == rival)
    ]


def rollout_candidate(
    segments: tuple[ProfileSegment, ...],
    frame: PlanFrame,
    scenarios: tuple[PlanScenario, ...],
    world: PlanningWorld,
    estimate: StateEstimate,
    config: PlannerConfig,
    weights: SurrogateWeights,
    *,
    candidate_id: str,
) -> RolloutEvidence:
    """Re-simulate ``segments`` across ``scenarios`` with reacting rivals."""
    if not segments:
        raise ValueError("a rollout needs at least one profile segment")
    horizon_s = float(config.budgets.rollout_horizon_s.value)
    step_s = float(config.budgets.rollout_step_s.value)
    checkpoint_ids = world.checkpoint_ids
    reference_m = frame.end_progress_m
    controller = SegmentController(segments, DeploymentProfile.NEUTRAL)

    outcomes: list[ScenarioOutcome] = []
    pass_weight: dict[str, float] = {}
    ahead_weight: dict[str, float] = {}
    observed_weight: dict[str, float] = {}
    incomplete = 0
    total_weight = sum(scenario.weight for scenario in scenarios) or 1.0

    for scenario in scenarios:
        bundle = _variant_bundle(world, estimate, scenario)
        simulator = Simulator()
        simulator.reset(bundle, seed=world.seed)
        snapshot = capture_complete_state(simulator)
        start_time_s = float(snapshot["race"]["session_time_s"])
        start_progress_m = float(snapshot["cars"][world.ego_car_id]["progress_m"])

        branch = run_branch(
            bundle,
            snapshot,
            Treatment(id=f"{candidate_id}:{scenario.scenario_id}", controller=controller),
            horizon_s=horizon_s,
            dt_s=step_s,
            checkpoint_ids=checkpoint_ids,
        )
        final = branch.final_snapshot
        ego_times = _crossings(final, world.ego_car_id, start_time_s)
        rival_times = (
            {} if world.rival_car_id is None else _crossings(final, world.rival_car_id, start_time_s)
        )
        passes = _completed_pass_times(final, world.ego_car_id, world.rival_car_id)

        covered_m = float(final["cars"][world.ego_car_id]["progress_m"]) - start_progress_m
        final_energy_j = float(final["ledgers"][world.ego_car_id]["energy_j"])
        average_speed = covered_m / branch.elapsed_time_s if branch.elapsed_time_s > 0.0 else 0.0
        reached = covered_m >= (reference_m - start_progress_m)
        if not reached:
            incomplete += 1
        time_to_reference_s = (
            (reference_m - start_progress_m) / average_speed if average_speed > 0.0 else float("inf")
        )

        checkpoints: list[CheckpointOutcome] = []
        for checkpoint_id in checkpoint_ids:
            ego_at = ego_times.get(checkpoint_id)
            if ego_at is None:
                continue
            rival_at = rival_times.get(checkpoint_id)
            ahead = rival_at is None or ego_at < rival_at
            observed_weight[checkpoint_id] = observed_weight.get(checkpoint_id, 0.0) + scenario.weight
            if ahead:
                ahead_weight[checkpoint_id] = ahead_weight.get(checkpoint_id, 0.0) + scenario.weight
            if any(moment <= ego_at + 1e-9 for moment in passes):
                pass_weight[checkpoint_id] = pass_weight.get(checkpoint_id, 0.0) + scenario.weight
            checkpoints.append(
                CheckpointOutcome(
                    checkpoint_id=checkpoint_id,
                    progress_m=float(world.bundle.track.checkpoint(checkpoint_id).s_m.value),
                    elapsed_time_s=ego_at - start_time_s,
                    gap_to_reference_s=None if rival_at is None else ego_at - rival_at,
                    own_energy_j=final_energy_j,
                    ahead_of_rival=ahead,
                )
            )

        behind_at_end = 0.0
        if world.rival_car_id is not None:
            rival_progress = float(final["cars"][world.rival_car_id]["progress_m"])
            own_progress = float(final["cars"][world.ego_car_id]["progress_m"])
            behind_at_end = 1.0 if rival_progress > own_progress else 0.0
        utility = (
            weights.elapsed_second_penalty * time_to_reference_s
            + weights.position_penalty * behind_at_end
            - weights.energy_value_rate * final_energy_j
        )
        outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario.scenario_id,
                weight=scenario.weight,
                checkpoints=tuple(checkpoints),
                utility=utility,
                elapsed_time_s=branch.elapsed_time_s,
                final_energy_j=final_energy_j,
                terminal_value=weights.energy_value_rate * final_energy_j,
                terminal_value_source="analytic",
                feasible=reached,
            )
        )

    probabilities: list[ProbabilityStatement] = []
    for checkpoint_id in checkpoint_ids:
        seen = observed_weight.get(checkpoint_id, 0.0)
        if seen <= 0.0:
            continue
        samples = sum(
            1 for outcome in outcomes if any(c.checkpoint_id == checkpoint_id for c in outcome.checkpoints)
        )
        for label, table in (
            ("pass_before", pass_weight),
            ("ahead_at", ahead_weight),
        ):
            frequency = table.get(checkpoint_id, 0.0) / seen
            probabilities.append(
                ProbabilityStatement(
                    event_definition=f"{label}(checkpoint={checkpoint_id})",
                    checkpoint_id=checkpoint_id,
                    value=frequency,
                    raw_frequency=frequency,
                    sample_count=samples,
                    model_version="planner-rollout-ensemble-v1",
                    calibration_status=CalibrationStatus.UNCALIBRATED,
                )
            )

    expected = sum(outcome.weight * outcome.utility for outcome in outcomes) / total_weight
    return RolloutEvidence(
        outcomes=tuple(outcomes),
        probabilities=tuple(probabilities),
        expected_utility=expected,
        sample_count=len(outcomes),
        step_s=step_s,
        horizon_s=horizon_s,
        incomplete_count=incomplete,
    )
