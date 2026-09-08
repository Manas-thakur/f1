"""The deterministic headless simulator.

Public API, exactly as specified in ``simulation/TECHNICAL_SPEC.md``::

    reset(manifest_or_scenario, seed)
    step(driver_actions, dt_s)
    snapshot()
    restore(snapshot)
    observe(sensor_config)

Step ordering follows ``NUMERICS_AND_VALIDATION.md``:

1. process safety/line events at their true crossing time (the step is split at
   the interpolated crossing rather than applying the transition a step late),
2. update legal profiles,
3. apply delayed driver actions,
4. compute tyre/engine/electrical forces,
5. integrate motion and battery,
6. update the thermal state,
7. detect geometry and passes,
8. create observations with noise and delay,
9. record completed checkpoints.

**Integrator**: explicit midpoint (RK2) on float64 for progress, speed and
lateral offset. The electrical demand is held constant across a step — it is a
driver-selected profile, not a continuous control — and is saturated once
against the full step, which makes the battery ledger close exactly rather than
to within a midpoint truncation error. The thermal state uses the analytic
solution of its linear ODE and is therefore exact for a constant loss power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from afterlap_contracts import DeploymentProfile, FlagState

from ..rng import KeyedRandom, StreamRegistry
from ..timebase import EventPriority, EventQueue, SessionClock, crossing_time, laps_and_s
from . import physics
from .battery import EnergyLedger, LedgerPlan, SaturationEvent
from .config import ObservationConfig, ScenarioBundle, ScenarioConfig, load_bundle
from .observation import Observation, observe
from .policies import DriverAction, OpponentPolicy, build_policy
from .state import (
    CarState,
    CheckpointRecord,
    PairState,
    PassRecord,
    QueuedAction,
    RaceState,
    TruthSample,
    WorldState,
)
from .track import TrackGeometry, footprints_overlap, geometry_for
from .track_source import DEFAULT_ENVIRONMENT, EnvironmentField

_MIN_SUBSTEP_S = 1.0e-4
"""Below this, an event boundary is applied at the end of the sub-step instead
of splitting again. It bounds the number of splits per step."""

_SPEED_EPS = 1.0e-9
_PREVIEW_M = 400.0
_PREVIEW_OFFSETS = np.unique(
    np.concatenate(
        (
            np.arange(0.0, 100.0, 4.0, dtype=np.float64),
            np.arange(100.0, _PREVIEW_M + 20.0, 20.0, dtype=np.float64),
        )
    )
)
"""Braking-preview grid: fine near the car where a curvature ramp resolves the
braking point, coarse further out where only the corner limit itself matters."""

_PREVIEW_OFFSETS_LIST: list[float] = _PREVIEW_OFFSETS.tolist()
_MAX_MODELLED_SPEED_MPS = 130.0
_BRAKE_DEADBAND_MPS = 0.05
"""Speed error below which the driver does not touch the brake."""

_BRAKE_BAND_MPS = 0.5
"""Speed error at which the driver is already braking at the full envelope."""

_CORNER_GRIP_SHARE = 0.95
"""Lateral share of the grip envelope the driver model plans a corner around."""

_BRAKING_SAFETY_MARGIN = 0.97
"""Fraction of the computed braking capability the preview plans against.

It absorbs the preview grid discretisation, so the planned braking point is
slightly early rather than slightly late.
"""

DEPLOY_FRACTION: dict[DeploymentProfile, float] = {
    DeploymentProfile.HARVEST: 0.0,
    DeploymentProfile.CONSERVE: 0.20,
    DeploymentProfile.NEUTRAL: 0.50,
    DeploymentProfile.PUSH: 0.80,
    DeploymentProfile.OVERTAKE: 1.0,
}
"""Fraction of the deployment ceiling each coarse profile asks for."""

HARVEST_FRACTION: dict[DeploymentProfile, float] = {
    DeploymentProfile.HARVEST: 1.0,
    DeploymentProfile.CONSERVE: 0.85,
    DeploymentProfile.NEUTRAL: 0.65,
    DeploymentProfile.PUSH: 0.40,
    DeploymentProfile.OVERTAKE: 0.0,
}
"""Fraction of the available regenerative braking each profile blends in."""

TIMING_LINE_ID = "__timing_line__"

ATTEMPT_BAND_LENGTHS = 2.0
"""Multiples of the nose-to-tail distance inside which a follower is attempting."""


@dataclass(frozen=True, slots=True)
class _Evaluation:
    """Derivatives and diagnostics at one point of the step."""

    acceleration_mps2: float
    lateral_rate_mps: float
    heading_error_rad: float
    diagnostics: dict[str, float]


@dataclass(slots=True)
class _CarTrial:
    """The tentative result of integrating one car across a sub-step."""

    car_id: str
    progress_m: float
    speed_mps: float
    lateral_d_m: float
    heading_error_rad: float
    acceleration_mps2: float
    plan: LedgerPlan
    diagnostics: dict[str, float]
    start_progress_m: float


@dataclass(slots=True)
class StepReport:
    """Everything one ``step`` produced, for the caller and for validation."""

    session_time_s: float
    dt_s: float
    substeps: int
    events: list[dict[str, Any]] = field(default_factory=list)
    passes: list[PassRecord] = field(default_factory=list)
    saturation_events: list[SaturationEvent] = field(default_factory=list)
    checkpoints: list[CheckpointRecord] = field(default_factory=list)
    policy_actions: dict[str, DriverAction] = field(default_factory=dict)
    profile_downgrades: list[dict[str, Any]] = field(default_factory=list)
    envelope_exceedances: list[dict[str, Any]] = field(default_factory=list)
    """Recorded rather than hidden: the reduced model has no understeer escape,
    so a state where lateral demand exceeds the tyre envelope is reported as an
    unsupported condition instead of being silently clipped."""


class Simulator:
    """Headless deterministic physics and battle simulator."""

    def __init__(self) -> None:
        self._world: WorldState | None = None
        self._geometry: TrackGeometry | None = None
        self._sensor_config: ObservationConfig | None = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def reset(self, manifest_or_scenario: str | ScenarioConfig | ScenarioBundle, seed: int | None = None,
        environment: EnvironmentField | None = None,
    ):
        """Load a scenario and build the initial world state.

        ``seed`` overrides the scenario's own seed; the override is recorded in
        the snapshot so a run can always be traced back to the seed that
        produced it.
        """
        bundle = (
            manifest_or_scenario
            if isinstance(manifest_or_scenario, ScenarioBundle)
            else load_bundle(manifest_or_scenario)
        )
        scenario = bundle.scenario
        effective_seed = scenario.seed if seed is None else int(seed)
        world = WorldState(
            bundle=bundle,
            track=bundle.track,
            car_configs=dict(bundle.car_configs),
            driver_configs=dict(scenario.drivers),
            seed=effective_seed,
        )
        world.race = RaceState(session_time_s=0.0, flags=(FlagState.GREEN,))
        world.clock = SessionClock(session_time_s=0.0)
        world.events = EventQueue()
        world.streams = StreamRegistry(
            effective_seed,
            tuple(f"driver_response:{car_id}" for car_id in scenario.car_ids),
        )
        world.keyed = KeyedRandom(
            scenario.id,
            effective_seed,
            bin_width_s=float(scenario.observation.noise_time_bin_s.value),
        )

        for car_id in scenario.car_ids:
            initial = scenario.initial_states[car_id]
            car = bundle.car_configs[car_id]
            length = bundle.track.length
            laps, s_m = laps_and_s(float(initial.progress_m.value), length)
            world.cars[car_id] = CarState(
                car_id=car_id,
                progress_m=float(initial.progress_m.value),
                s_m=s_m,
                lap=laps,
                speed_mps=float(initial.speed_mps.value),
                lateral_d_m=float(initial.lateral_d_m.value),
                battery_energy_j=float(initial.energy_j.value),
                battery_temperature_k=float(initial.temperature_k.value),
                active_profile=initial.profile,
            )
            world.ledgers[car_id] = EnergyLedger(
                car_id=car_id,
                energy_j=float(initial.energy_j.value),
                energy_min_j=float(car.battery_energy_min_j.value),
                energy_max_j=float(car.battery_energy_max_j.value),
                eta_discharge=float(car.eta_discharge.value),
                eta_charge=float(car.eta_charge.value),
            )
            world.action_queues[car_id] = []
            world.active_actions[car_id] = DriverAction(profile=initial.profile)
            world.next_thresholds[car_id] = self._initial_thresholds(bundle, car_id, world.cars[car_id])

        for rival_id, spec in scenario.opponent_policies.items():
            params = {name: float(param.value) for name, param in spec.params.items()}
            world.policies[rival_id] = build_policy(spec.kind, params)

        for a in scenario.car_ids:
            for b in scenario.car_ids:
                if a == b:
                    continue
                gap = world.cars[a].progress_m - world.cars[b].progress_m
                clearance = self._clearance_m(bundle, a, b)
                label = "ahead" if gap > clearance else "behind" if gap < -clearance else "contesting"
                world.pairs[(a, b)] = PairState(label=label, armed=gap < -ATTEMPT_BAND_LENGTHS * clearance)

        if environment is None:
            environment = bundle.environment if bundle.environment is not None else DEFAULT_ENVIRONMENT
        world.environment = environment
        self._world = world
        self._geometry = geometry_for(bundle.track)
        self._sensor_config = scenario.observation
        self._record_truth_sample()
        return self

    # ------------------------------------------------------------------ #
    # helpers used by reset
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clearance_m(bundle: ScenarioBundle, a: str, b: str) -> float:
        """Nose-to-tail longitudinal separation between two car centres.

        This is the *longitudinal* condition only. Physical clearance is decided
        by the separating-axis footprint test, which is what catches a yawed car
        whose along-track extent is longer than its wheelbase. Adding a fixed
        margin here instead would make the footprint veto unreachable and turn
        the contact rule into decoration.
        """
        return 0.5 * (
            float(bundle.car_configs[a].length_m.value) + float(bundle.car_configs[b].length_m.value)
        )

    @staticmethod
    def _initial_thresholds(bundle: ScenarioBundle, car_id: str, state: CarState) -> dict[str, float]:
        """First unwrapped progress value at which each line is next crossed."""
        length = bundle.track.length
        thresholds: dict[str, float] = {}
        lines = [(TIMING_LINE_ID, float(bundle.track.timing_line_s_m.value))]
        lines.extend((cp.id, float(cp.s_m.value)) for cp in bundle.track.checkpoints)
        for line_id, s_line in lines:
            laps = math.floor((state.progress_m - s_line) / length) + 1
            thresholds[line_id] = laps * length + s_line
        del car_id
        return thresholds

    # ------------------------------------------------------------------ #
    # accessors
    # ------------------------------------------------------------------ #

    @property
    def world(self) -> WorldState:
        """Private truth. Exposed for tests and for the branching helper only."""
        if self._world is None:
            raise RuntimeError("the simulator has not been reset")
        return self._world

    @property
    def geometry(self) -> TrackGeometry:
        if self._geometry is None:
            raise RuntimeError("the simulator has not been reset")
        return self._geometry

    @property
    def sensor_config(self) -> ObservationConfig:
        if self._sensor_config is None:
            raise RuntimeError("the simulator has not been reset")
        return self._sensor_config

    @property
    def session_time_s(self) -> float:
        return self.world.race.session_time_s

    # ------------------------------------------------------------------ #
    # observation
    # ------------------------------------------------------------------ #

    def observe(
        self, sensor_config: ObservationConfig | None = None, car_id: str | None = None
    ) -> dict[str, Observation]:
        """Build observations. The only path from truth to a controller."""
        return observe(self.world, sensor_config or self.sensor_config, car_id)

    # ------------------------------------------------------------------ #
    # snapshot / restore
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict[str, Any]:
        return self.world.capture_complete_state()

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.world.restore(snapshot)

    # ------------------------------------------------------------------ #
    # stepping
    # ------------------------------------------------------------------ #

    def step(self, driver_actions: dict[str, DriverAction] | None, dt_s: float) -> StepReport:
        """Advance the world by ``dt_s`` seconds."""
        if dt_s <= 0.0:
            raise ValueError("a simulation step needs a positive duration")
        world = self.world
        report = StepReport(session_time_s=world.race.session_time_s, dt_s=dt_s, substeps=0)

        # --- (3a) accept new driver inputs into the reaction-delay queues ---
        supplied = dict(driver_actions or {})
        for car_id in sorted(world.cars):
            if car_id in supplied:
                self._enqueue_action(car_id, supplied[car_id], report)
        for rival_id, policy in sorted(world.policies.items()):
            if rival_id in supplied:
                continue
            action = self._policy_action(rival_id, policy)
            report.policy_actions[rival_id] = action
            self._enqueue_action(rival_id, action, report)

        remaining = dt_s
        self._process_events(world.race.session_time_s, report)

        while remaining > 1e-12:
            now = world.race.session_time_s
            # --- (3b) apply delayed driver actions whose time has come ---
            self._activate_actions(now)
            # --- (2) update legal profiles ---
            self._update_legal_profiles(report)

            h = min(remaining, self._next_boundary_gap(now, remaining))
            # --- (4, 5) forces and integration ---
            trials = self._integrate_all(h)
            split = self._earliest_crossing(now, h, trials)
            if split is not None and _MIN_SUBSTEP_S < split - now < h - _MIN_SUBSTEP_S:
                h = split - now
                trials = self._integrate_all(h)
            self._commit(trials, h, report)
            world.race.session_time_s = now + h
            world.clock.advance(h)
            remaining -= h
            report.substeps += 1
            # --- (1, 9) line events at their interpolated crossing time ---
            self._schedule_crossings(now, h, trials)
            self._process_events(world.race.session_time_s, report)

        # --- (7) geometry and passes ---
        self._detect_passes(report)
        # --- (8) buffer a truth sample for the delayed sensor path ---
        self._record_truth_sample()
        world.race.step_index += 1
        world.last_dt_s = dt_s
        world.race.leader_lap = max(state.lap for state in world.cars.values())
        return report

    # ------------------------------------------------------------------ #
    # driver action plumbing
    # ------------------------------------------------------------------ #

    def _policy_action(self, car_id: str, policy: OpponentPolicy) -> DriverAction:
        """Opponents decide from their own observation, never from truth."""
        world = self.world
        assert world.streams is not None
        observation = self.observe(car_id=car_id)[car_id]
        rng = world.streams.stream(f"driver_response:{car_id}")
        return policy.react(observation, rng)

    def _enqueue_action(self, car_id: str, action: DriverAction, report: StepReport) -> None:
        world = self.world
        assert world.streams is not None and world.keyed is not None
        driver = world.driver_configs[car_id]
        mean = float(driver.reaction_delay_mean_s.value)
        std = float(driver.reaction_delay_std_s.value)
        jitter = float(driver.execution_jitter_s.value)
        delay = mean
        if std > 0.0 or jitter > 0.0:
            # Keyed by physical time so a branch that reaches the same instant
            # draws the same human variability.
            perturbation = world.keyed.normal(f"driver_delay:{car_id}", world.race.session_time_s, scale=1.0)
            delay = mean + perturbation * math.hypot(std, jitter)
        delay = max(0.0, delay)
        world.action_sequence += 1
        world.action_queues[car_id].append(
            QueuedAction(
                apply_time_s=world.race.session_time_s + delay,
                car_id=car_id,
                action=action,
                issued_at_s=world.race.session_time_s,
                sequence=world.action_sequence,
            )
        )
        world.action_queues[car_id].sort(key=lambda queued: (queued.apply_time_s, queued.sequence))
        state = world.cars[car_id]
        state.pending_profile = action.profile
        state.pending_apply_time_s = world.action_queues[car_id][0].apply_time_s
        del report

    def _activate_actions(self, now: float) -> None:
        world = self.world
        for car_id, queue in world.action_queues.items():
            while queue and queue[0].apply_time_s <= now + 1e-12:
                queued = queue.pop(0)
                world.active_actions[car_id] = queued.action
                world.cars[car_id].active_profile = queued.action.profile
            state = world.cars[car_id]
            if queue:
                state.pending_profile = queue[0].action.profile
                state.pending_apply_time_s = queue[0].apply_time_s
            else:
                state.pending_profile = None
                state.pending_apply_time_s = None

    def _update_legal_profiles(self, report: StepReport) -> None:
        """Downgrade a profile the current physical state cannot support.

        This is the simulator's own physical admissibility, not the regulatory
        rule engine: it only enforces the battery window and the thermal derate.
        Regulatory admissibility is owned by the rules module.
        """
        world = self.world
        for car_id, state in world.cars.items():
            car = world.car_configs[car_id]
            ledger = world.ledgers[car_id]
            derate = physics.derate_factor(
                state.battery_temperature_k,
                float(car.derate_start_temperature_k.value),
                float(car.derate_end_temperature_k.value),
            )
            state.derate_factor = derate
            floor = float(car.battery_energy_min_j.value)
            depleted = ledger.energy_j <= floor + 1.0
            wants_deploy = DEPLOY_FRACTION[state.active_profile] > 0.0
            if (depleted or derate <= 0.0) and wants_deploy:
                report.profile_downgrades.append(
                    {
                        "session_time_s": world.race.session_time_s,
                        "car_id": car_id,
                        "from_profile": state.active_profile.value,
                        "to_profile": DeploymentProfile.HARVEST.value,
                        "reason": "energy_floor" if depleted else "thermal_derate",
                    }
                )
                state.active_profile = DeploymentProfile.HARVEST

    # ------------------------------------------------------------------ #
    # forces and integration
    # ------------------------------------------------------------------ #

    def _envelope_speed(self, car_id: str, s_m: float, braking_fraction: float) -> float:
        """Highest entry speed that still fits every corner in the preview.

        Backward braking-point construction over the preview grid. At each grid
        point the *available* longitudinal deceleration is what the friction
        ellipse leaves once the corner at that point has taken its share, so the
        result accounts for the fact that a car already cornering cannot brake
        at the full envelope. A naive ``mu*g`` propagation over-estimates the
        deceleration and lets the car arrive beyond the envelope.
        """
        world = self.world
        track = world.track
        car = world.car_configs[car_id]
        samples = s_m + _PREVIEW_OFFSETS
        curvature = np.abs(track.curvature_array(samples))
        # The planned corner speed reserves a slice of the grip envelope for
        # longitudinal use. Planning at 100% lateral utilisation leaves the car
        # with no braking authority exactly where it needs it, and any small
        # overshoot then cannot be recovered.
        mu = track.mu_array(samples) * _CORNER_GRIP_SHARE
        factor = car.downforce_factor_inv_m
        denominator = curvature - mu * factor
        corner_limit = np.where(
            denominator > 0.0,
            np.sqrt(mu * physics.GRAVITY_MPS2 / np.where(denominator > 0.0, denominator, 1.0)),
            _MAX_MODELLED_SPEED_MPS,
        )
        corner_limit = np.minimum(corner_limit, _MAX_MODELLED_SPEED_MPS)

        limits = corner_limit.tolist()
        curvatures = curvature.tolist()
        grips = mu.tolist()
        offsets = _PREVIEW_OFFSETS_LIST

        def available_decel(grip: float, curvature_at: float, at_speed: float) -> float:
            envelope_a = grip * (physics.GRAVITY_MPS2 + factor * at_speed * at_speed)
            lateral_a = at_speed * at_speed * curvature_at
            spare = envelope_a * envelope_a - lateral_a * lateral_a
            if spare <= 0.0:
                return 0.0
            return _BRAKING_SAFETY_MARGIN * braking_fraction * math.sqrt(spare)

        speed = limits[-1]
        for index in range(len(limits) - 2, -1, -1):
            distance = offsets[index + 1] - offsets[index]
            # Predictor at the exit of the interval, corrector at its entry: over
            # the interval the car is faster and the corner may be tighter than
            # at the exit, so taking the smaller of the two decelerations keeps
            # the planned braking point on the safe side.
            exit_decel = available_decel(grips[index + 1], curvatures[index + 1], speed)
            predicted = math.sqrt(speed * speed + 2.0 * exit_decel * distance)
            entry_decel = available_decel(grips[index], curvatures[index], predicted)
            decel = min(exit_decel, entry_decel)
            speed = min(limits[index], math.sqrt(speed * speed + 2.0 * decel * distance))
        return speed

    def _evaluate(
        self,
        car_id: str,
        progress_m: float,
        speed_mps: float,
        lateral_d_m: float,
        action: DriverAction,
        dt_s: float,
        plan: LedgerPlan | None,
    ) -> tuple[_Evaluation, LedgerPlan]:
        """Forces, electrical saturation and derivatives at one state point."""
        world = self.world
        track = world.track
        car = world.car_configs[car_id]
        driver = world.driver_configs[car_id]
        ledger = world.ledgers[car_id]

        mass = float(car.mass_kg.value)
        s_m = progress_m % track.length
        speed = max(0.0, speed_mps)
        session_time_s = world.race.session_time_s
        environment = world.environment

        # Atmosphere and surface come through the EnvironmentField seam. The
        # default StaticEnvironment returns the car document's density, still
        # air and a unit grip multiplier, so synthetic runs are bit-identical to
        # the pre-A16 engine; a conditions tape changes these two lines only.
        rho = environment.air_density_kgpm3(s_m, session_time_s, float(car.air_density_kgpm3.value))

        curvature = track.curvature_at(s_m)
        grade = track.grade_at(s_m)
        mu = track.mu_at(s_m) * environment.grip_multiplier(s_m, session_time_s)
        # Wind is projected onto the local heading; a headwind raises the air
        # speed the drag term sees without changing ground speed.
        heading = self._geometry.heading_at(s_m) if self._geometry is not None else 0.0
        air_speed = max(0.0, speed + environment.headwind_mps(s_m, heading, session_time_s))

        down_n = physics.downforce(rho, float(car.cla_m2.value), air_speed)
        envelope_n = physics.traction_limit(mass, physics.GRAVITY_MPS2, mu, down_n)
        # The raw demand is kept for diagnostics; only the envelope split uses
        # the clamped value, so a validation test can still see a violation.
        lateral_demand_n = mass * speed * speed * abs(curvature)
        long_envelope_n = physics.longitudinal_envelope(envelope_n, min(lateral_demand_n, envelope_n))

        drag_n = physics.drag_force(rho, float(car.cda_m2.value), air_speed)
        roll_n = physics.rolling_force(mass, physics.GRAVITY_MPS2, float(car.crr.value), grade)
        grade_n = physics.grade_force(mass, physics.GRAVITY_MPS2, grade)

        braking_fraction = float(driver.braking_envelope_fraction.value)
        envelope_speed = self._envelope_speed(car_id, s_m, braking_fraction)
        target_speed = action.pace_scale * envelope_speed

        derate = physics.derate_factor(
            world.cars[car_id].battery_temperature_k,
            float(car.derate_start_temperature_k.value),
            float(car.derate_end_temperature_k.value),
        )

        max_brake_n = min(float(car.max_brake_force_n.value), braking_fraction * long_envelope_n)
        ice_full_w = car.ice_power_at(speed)
        available_shaft_w = (ice_full_w + derate * float(car.max_deploy_power_w.value)) * float(
            car.drivetrain_efficiency.value
        )
        max_drive_n = physics.tractive_force(available_shaft_w, speed, float(car.max_tractive_force_n.value))

        if action.throttle is not None or action.brake is not None:
            throttle = 0.0 if action.throttle is None else action.throttle
            brake = 0.0 if action.brake is None else action.brake
        elif speed > target_speed + _BRAKE_DEADBAND_MPS:
            # Behind the braking curve. ``target_speed`` already encodes the
            # deceleration the tyres can actually deliver, so being above it
            # means the braking point has passed: brake at the envelope rather
            # than closing the error gently, which is what a driver does and
            # what keeps the car inside the friction ellipse.
            throttle = 0.0
            brake = min(1.0, (speed - target_speed) / _BRAKE_BAND_MPS)
        else:
            # First-order speed governor on the power side. ``tau`` is the time
            # constant with which the driver closes the gap to the target.
            tau = 0.6
            desired_a = (target_speed - speed) / tau
            required_n = mass * desired_a + drag_n + roll_n + grade_n
            if required_n >= 0.0:
                throttle = min(1.0, required_n / max_drive_n) if max_drive_n > 0.0 else 0.0
                brake = 0.0
            else:
                throttle = 0.0
                brake = min(1.0, -required_n / max_brake_n) if max_brake_n > 0.0 else 0.0

        brake_force_n = brake * max_brake_n
        mechanical_brake_w = brake_force_n * speed

        if plan is None:
            deploy_ceiling_w = derate * float(car.max_deploy_power_w.value)
            requested_deploy_w = DEPLOY_FRACTION[action.profile] * deploy_ceiling_w * throttle
            if car.regen_enabled:
                mechanical_available_w = min(
                    float(car.max_harvest_power_w.value),
                    float(car.regen_share.value) * mechanical_brake_w,
                )
                requested_harvest_w = (
                    HARVEST_FRACTION[action.profile] * action.harvest_request * mechanical_available_w
                )
            else:
                mechanical_available_w = 0.0
                requested_harvest_w = 0.0
            plan = ledger.plan(
                dt_s,
                requested_deploy_dc_w=requested_deploy_w,
                requested_harvest_dc_w=requested_harvest_w,
                mechanical_available_w=mechanical_available_w,
                aux_w=float(car.aux_load_w.value),
            )

        shaft_w = (ice_full_w * throttle + plan.actual_deploy_dc_w) * float(car.drivetrain_efficiency.value)
        drive_available_n = physics.tractive_force(shaft_w, speed, float(car.max_tractive_force_n.value))
        net_drive_n = drive_available_n - brake_force_n
        acceleration, applied_n = physics.longitudinal_acceleration(
            mass, net_drive_n, drag_n, roll_n, grade_n, long_envelope_n
        )
        if speed <= _SPEED_EPS and acceleration < 0.0:
            acceleration = 0.0

        limit_d = self.geometry.lateral_limit(s_m, float(car.width_m.value))
        target_d = max(-limit_d, min(action.target_lateral_d_m, limit_d))
        lateral_rate = float(driver.line_tracking_gain.value) * (target_d - lateral_d_m)
        heading_error = math.atan2(lateral_rate, max(speed, 1.0))

        diagnostics = {
            "drive_force_n": applied_n,
            "drag_force_n": drag_n,
            "rolling_force_n": roll_n,
            "grade_force_n": grade_n,
            "traction_limit_n": long_envelope_n,
            "traction_envelope_n": envelope_n,
            "lateral_demand_n": lateral_demand_n,
            "lateral_acceleration_mps2": speed * speed * abs(curvature),
            "tyre_utilisation": (
                math.hypot(lateral_demand_n, applied_n) / envelope_n if envelope_n > 0.0 else 0.0
            ),
            "ice_power_w": ice_full_w * throttle,
            "mechanical_braking_power_w": mechanical_brake_w,
            "target_speed_mps": target_speed,
            "envelope_speed_mps": envelope_speed,
            "derate_factor": derate,
        }
        return (
            _Evaluation(
                acceleration_mps2=acceleration,
                lateral_rate_mps=lateral_rate,
                heading_error_rad=heading_error,
                diagnostics=diagnostics,
            ),
            plan,
        )

    def _integrate_all(self, h: float) -> dict[str, _CarTrial]:
        """Explicit midpoint integration of every car across one sub-step."""
        world = self.world
        trials: dict[str, _CarTrial] = {}
        for car_id in sorted(world.cars):
            state = world.cars[car_id]
            action = world.active_actions[car_id]
            # Predictor at the start of the step, purely to locate the midpoint.
            # Its electrical plan is provisional and is thrown away.
            first, _ = self._evaluate(
                car_id, state.progress_m, state.speed_mps, state.lateral_d_m, action, h, None
            )
            mid_progress = state.progress_m + 0.5 * h * state.speed_mps
            mid_speed = max(0.0, state.speed_mps + 0.5 * h * first.acceleration_mps2)
            mid_lateral = state.lateral_d_m + 0.5 * h * first.lateral_rate_mps
            # Corrector at the midpoint. Its plan is the one that gets committed,
            # so the electrical demand is second-order accurate too, and it is
            # still saturated once against the whole step from the start-of-step
            # stored energy, which keeps the ledger closing exactly.
            second, plan = self._evaluate(car_id, mid_progress, mid_speed, mid_lateral, action, h, None)

            speed_next = max(0.0, state.speed_mps + h * second.acceleration_mps2)
            progress_next = state.progress_m + h * mid_speed
            lateral_next = state.lateral_d_m + h * second.lateral_rate_mps
            trials[car_id] = _CarTrial(
                car_id=car_id,
                progress_m=progress_next,
                speed_mps=speed_next,
                lateral_d_m=lateral_next,
                heading_error_rad=second.heading_error_rad,
                acceleration_mps2=second.acceleration_mps2,
                plan=plan,
                diagnostics=second.diagnostics,
                start_progress_m=state.progress_m,
            )
        return trials

    def _commit(self, trials: dict[str, _CarTrial], h: float, report: StepReport) -> None:
        world = self.world
        for car_id, trial in trials.items():
            state = world.cars[car_id]
            car = world.car_configs[car_id]
            ledger = world.ledgers[car_id]

            before = len(ledger.saturation_events)
            ledger.commit(trial.plan, world.race.session_time_s)
            report.saturation_events.extend(ledger.saturation_events[before:])

            state.progress_m = trial.progress_m
            laps, s_m = laps_and_s(trial.progress_m, world.track.length)
            state.lap = laps
            state.s_m = s_m
            state.distance_travelled_m += max(0.0, trial.progress_m - trial.start_progress_m)
            state.speed_mps = trial.speed_mps
            state.acceleration_mps2 = trial.acceleration_mps2
            state.lateral_d_m = trial.lateral_d_m
            state.heading_error_rad = trial.heading_error_rad
            state.elapsed_time_s += h

            # --- (6) thermal state, analytic over the sub-step ---
            state.battery_temperature_k = physics.thermal_step(
                state.battery_temperature_k,
                float(car.c_th_j_per_k.value),
                trial.plan.loss_w,
                float(car.h_w_per_k.value),
                float(car.ambient_temperature_k.value),
                h,
            )
            state.battery_energy_j = ledger.energy_j
            state.recharge_ledger_j = ledger.recharge_cumulative_j
            state.recharge_ledger_this_lap_j = ledger.recharge_this_lap_j
            state.deploy_power_dc_w = trial.plan.actual_deploy_dc_w
            state.harvest_power_dc_w = trial.plan.actual_harvest_dc_w
            state.battery_out_power_w = trial.plan.battery_out_w
            state.battery_in_power_w = trial.plan.battery_in_w
            state.auxiliary_power_w = trial.plan.aux_w
            state.electrical_loss_power_w = trial.plan.loss_w
            state.mechanical_rejected_power_w = trial.plan.mechanical_rejected_w
            for name, value in trial.diagnostics.items():
                setattr(state, name, value)

            if state.traction_envelope_n > 0.0 and state.lateral_demand_n > state.traction_envelope_n:
                report.envelope_exceedances.append(
                    {
                        "session_time_s": world.race.session_time_s,
                        "car_id": car_id,
                        "s_m": state.s_m,
                        "utilisation": state.lateral_demand_n / state.traction_envelope_n,
                        "status": "unsupported_by_reduced_model",
                    }
                )

    # ------------------------------------------------------------------ #
    # events, crossings and checkpoints
    # ------------------------------------------------------------------ #

    def _next_boundary_gap(self, now: float, remaining: float) -> float:
        """Time to the next queued event or delayed action inside this step."""
        world = self.world
        gap = remaining
        peek = world.events.peek_time()
        if peek is not None and peek > now + _MIN_SUBSTEP_S:
            gap = min(gap, peek - now)
        for queue in world.action_queues.values():
            if queue and queue[0].apply_time_s > now + _MIN_SUBSTEP_S:
                gap = min(gap, queue[0].apply_time_s - now)
        return max(gap, _MIN_SUBSTEP_S)

    def _earliest_crossing(self, now: float, h: float, trials: dict[str, _CarTrial]) -> float | None:
        """Interpolated time of the first line crossing inside this sub-step."""
        world = self.world
        earliest: float | None = None
        for car_id, trial in trials.items():
            for threshold in world.next_thresholds[car_id].values():
                if not trial.start_progress_m < threshold <= trial.progress_m:
                    continue
                moment = crossing_time(now, now + h, trial.start_progress_m, trial.progress_m, threshold)
                if moment is not None and (earliest is None or moment < earliest):
                    earliest = moment
        return earliest

    def _schedule_crossings(self, now: float, h: float, trials: dict[str, _CarTrial]) -> None:
        """Queue a line event for every threshold this sub-step actually passed."""
        world = self.world
        for car_id, trial in trials.items():
            thresholds = world.next_thresholds[car_id]
            for line_id in sorted(thresholds):
                threshold = thresholds[line_id]
                while trial.start_progress_m < threshold <= trial.progress_m:
                    moment = crossing_time(now, now + h, trial.start_progress_m, trial.progress_m, threshold)
                    world.events.push(
                        now + h if moment is None else moment,
                        EventPriority.PHYSICAL_LINE_EVENT,
                        {
                            "kind": "line_crossing",
                            "line_id": line_id,
                            "car_id": car_id,
                            "threshold_progress_m": threshold,
                        },
                    )
                    threshold += world.track.length
                thresholds[line_id] = threshold

    def _process_events(self, now: float, report: StepReport) -> None:
        """Apply every queued event at or before ``now`` in contract order."""
        world = self.world
        for event in world.events.pop_until(now + 1e-12):
            payload = dict(event.payload)
            payload["session_time_s"] = event.time_s
            payload["priority"] = int(event.priority)
            report.events.append(payload)
            if payload.get("kind") != "line_crossing":
                continue
            car_id = payload["car_id"]
            line_id = payload["line_id"]
            state = world.cars[car_id]
            ledger = world.ledgers[car_id]
            if line_id == TIMING_LINE_ID:
                # Only the per-lap counter resets. No battery refill, and the
                # cumulative regulatory ledger is untouched.
                ledger.reset_lap_counters()
                state.recharge_ledger_this_lap_j = ledger.recharge_this_lap_j
            else:
                record = CheckpointRecord(
                    checkpoint_id=line_id,
                    car_id=car_id,
                    lap=state.lap,
                    session_time_s=event.time_s,
                    progress_m=payload["threshold_progress_m"],
                    speed_mps=state.speed_mps,
                    battery_energy_j=ledger.energy_j,
                    recharge_cumulative_j=ledger.recharge_cumulative_j,
                )
                world.checkpoint_records.append(record)
                report.checkpoints.append(record)
                self._evaluate_retention(car_id, line_id, event.time_s, report)

    # ------------------------------------------------------------------ #
    # geometry and passes
    # ------------------------------------------------------------------ #

    def _overlapping(self, a: str, b: str) -> bool:
        world = self.world
        car_a = world.car_configs[a]
        car_b = world.car_configs[b]
        state_a = world.cars[a]
        state_b = world.cars[b]
        return footprints_overlap(
            self.geometry,
            state_a.s_m,
            state_a.lateral_d_m,
            state_a.heading_error_rad,
            float(car_a.length_m.value),
            float(car_a.width_m.value),
            state_b.s_m,
            state_b.lateral_d_m,
            state_b.heading_error_rad,
            float(car_b.length_m.value),
            float(car_b.width_m.value),
        )

    def _detect_passes(self, report: StepReport) -> None:
        """Pass labelling from footprint clearance and unwrapped progress.

        Three separate records are kept. ``attempted_pass`` fires once when the
        following car comes inside the attempt band. ``completed_pass`` requires
        both a full clearance in unwrapped progress **and** non-overlapping
        footprints, so a longitudinal scalar crossing while the cars are
        physically in contact is never rewarded. ``retained_pass`` is decided
        later, at a named checkpoint.

        The clearance band ``[-clear, +clear]`` is the hysteresis: a label only
        changes when the cars are unambiguously separated, so numerical jitter
        around the boundary cannot flap the label.
        """
        world = self.world
        now = world.race.session_time_s
        for (a, b), pair in world.pairs.items():
            delta = world.cars[a].progress_m - world.cars[b].progress_m
            clearance = self._clearance_m(world.bundle, a, b)
            attempt_band = ATTEMPT_BAND_LENGTHS * clearance

            if delta < -attempt_band:
                pair.armed = True

            if pair.label != "ahead" and pair.armed and not pair.attempted and delta > -attempt_band:
                pair.attempted = True
                record = PassRecord(
                    session_time_s=now,
                    overtaking_car_id=a,
                    overtaken_car_id=b,
                    kind="attempted_pass",
                )
                world.passes.append(record)
                report.passes.append(record)
                if pair.label == "behind":
                    pair.label = "contesting"

            if pair.label != "ahead" and delta > clearance:
                if self._overlapping(a, b):
                    record = PassRecord(
                        session_time_s=now,
                        overtaking_car_id=a,
                        overtaken_car_id=b,
                        kind="blocked_by_contact",
                        detail="footprints overlap; no pass is recorded",
                    )
                    world.passes.append(record)
                    report.passes.append(record)
                else:
                    pair.label = "ahead"
                    pair.completed_at_s = now
                    pair.completed_progress_m = world.cars[a].progress_m
                    pair.retained_evaluated = False
                    record = PassRecord(
                        session_time_s=now,
                        overtaking_car_id=a,
                        overtaken_car_id=b,
                        kind="completed_pass",
                    )
                    world.passes.append(record)
                    report.passes.append(record)
            elif pair.label == "ahead" and delta < -clearance:
                pair.label = "behind"
                pair.armed = False
                pair.attempted = False
                pair.completed_at_s = None
                pair.completed_progress_m = None
                pair.retained_evaluated = False

    def _evaluate_retention(self, car_id: str, checkpoint_id: str, moment: float, report: StepReport) -> None:
        """Decide retained-pass at the scenario's named retention checkpoint."""
        world = self.world
        retention = world.bundle.scenario.retention_checkpoint_id
        if retention is None or checkpoint_id != retention:
            return
        for (a, b), pair in world.pairs.items():
            if a != car_id or pair.completed_at_s is None or pair.retained_evaluated:
                continue
            delta = world.cars[a].progress_m - world.cars[b].progress_m
            clearance = self._clearance_m(world.bundle, a, b)
            retained = delta > clearance and not self._overlapping(a, b)
            pair.retained_evaluated = True
            record = PassRecord(
                session_time_s=moment,
                overtaking_car_id=a,
                overtaken_car_id=b,
                kind="retained_pass" if retained else "lost_pass",
                checkpoint_id=checkpoint_id,
            )
            world.passes.append(record)
            report.passes.append(record)

    # ------------------------------------------------------------------ #
    # sensor buffer
    # ------------------------------------------------------------------ #

    def _record_truth_sample(self) -> None:
        """Append the current truth to the delay buffer.

        The buffer holds truth. Noise, quantisation and gating are applied on
        the way *out*, in ``observation.observe``, so a snapshot restores the
        same buffer and therefore the same future observations.
        """
        world = self.world
        sample = TruthSample(
            session_time_s=world.race.session_time_s,
            cars={
                car_id: {
                    "speed_mps": state.speed_mps,
                    "progress_m": state.progress_m,
                    "s_m": state.s_m,
                    "lap": float(state.lap),
                    "lateral_d_m": state.lateral_d_m,
                    "acceleration_mps2": state.acceleration_mps2,
                    "battery_energy_j": state.battery_energy_j,
                    "battery_temperature_k": state.battery_temperature_k,
                    "recharge_this_lap_j": state.recharge_ledger_this_lap_j,
                    "recharge_cumulative_j": state.recharge_ledger_j,
                    # Signed DC-bus power, using the channel registry's stated
                    # convention: positive deploys to the wheels, negative
                    # harvests. The estimator integrates this to propagate
                    # energy; without it there is nothing to integrate and the
                    # energy belief drifts on the correction term alone.
                    "electrical_power_w": state.deploy_power_dc_w - state.harvest_power_dc_w,
                    "active_profile_code": state.active_profile.value,
                }
                for car_id, state in world.cars.items()
            },
        )
        world.sensor_buffer.append(sample)
        horizon = float(self.sensor_config.delay_s.value) + 2.0
        cutoff = world.race.session_time_s - horizon
        while len(world.sensor_buffer) > 2 and world.sensor_buffer[1].session_time_s < cutoff:
            world.sensor_buffer.pop(0)

    # ------------------------------------------------------------------ #
    # diagnostics
    # ------------------------------------------------------------------ #

    def detect_geometry_events(self) -> list[PassRecord]:
        """Re-run pass and contact detection against the current state.

        ``step`` calls the same routine at stage 7. Exposing it lets the geometry
        rule be exercised on a constructed configuration — a yawed car alongside
        another, say — without having to reach that configuration through a
        whole trajectory.
        """
        report = StepReport(session_time_s=self.world.race.session_time_s, dt_s=0.0, substeps=0)
        self._detect_passes(report)
        return report.passes

    def energy_close_errors(self) -> dict[str, float]:
        """Battery balance residual per car, in joules."""
        return {car_id: ledger.close_error() for car_id, ledger in self.world.ledgers.items()}

    def passes_of_kind(self, kind: str) -> list[PassRecord]:
        return [record for record in self.world.passes if record.kind == kind]


__all__ = ["DEPLOY_FRACTION", "HARVEST_FRACTION", "TIMING_LINE_ID", "Simulator", "StepReport"]
