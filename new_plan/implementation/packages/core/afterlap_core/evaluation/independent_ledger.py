"""An independent energy ledger and line-crossing reference.

**This module is deliberately written from the specification, not from the
simulator.** ``03_simulation/NUMERICS_AND_VALIDATION.md`` warns that a shared
bug makes a controller and its simulator agree with each other, and A03's own
handoff says its ``EnergyLedger.close_error()`` is the simulator auditing
itself. So nothing here imports ``afterlap_core.simulation.physics`` or
``afterlap_core.simulation.battery``; every equation below is typed out again
from the reference equations in the specification:

* ``F_drag = 0.5 * rho * CdA * v^2``
* ``F_grade = m * g * sin(grade)``
* ``a = (F_drive - F_drag - F_roll - F_grade) / m``
* ``P_battery_out = P_dc_deploy / eta_discharge``
* ``P_battery_in  = eta_charge * P_dc_harvest``
* ``C_th dT/dt = P_loss - h (T - T_ambient)``

The track's grade/curvature/grip interpolation is re-implemented here too, so a
defect in the simulator's own interpolation tables cannot cancel out.

What the checker consumes is a **recorded trajectory**: per-frame start and end
states, the electrical powers and forces that were in force across the frame,
and the simulator's own ledger totals. It never re-enters the simulator to ask
what the answer should be.

**Resolution.** ``NUMERICS_AND_VALIDATION.md`` asks the independent evaluator to
use a higher-resolution integrator than the run under test. Every reconstruction
here subdivides each recorded frame into :data:`DEFAULT_SUBSTEPS` pieces and
integrates with classical RK4 (motion, thermal) or composite Simpson (energy),
against a simulator that used explicit midpoint with the frame as its step.

**Independence, not equality.** The reconstructions are expected to differ from
the simulator by a truncation error, and the tolerances in
:class:`LedgerTolerances` were measured on the shipped fixtures and then frozen
(see the class docstring). A tolerance is never widened to make a disagreement
go away; a disagreement is a finding.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from afterlap_contracts import DeploymentProfile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from afterlap_core.simulation.config import CarConfig, TrackConfig
    from afterlap_core.simulation.engine import Simulator
    from afterlap_core.simulation.policies import DriverAction

__all__ = [
    "DEFAULT_SUBSTEPS",
    "GRAVITY_MPS2",
    "CarParameters",
    "Crossing",
    "CrossingDiscrepancy",
    "Discrepancy",
    "FrameFinding",
    "LedgerAudit",
    "LedgerTolerances",
    "ProgressSample",
    "RecordedTrajectory",
    "TrackReference",
    "TrajectoryFrame",
    "TrajectoryRecorder",
    "battery_terminal_in_w",
    "battery_terminal_out_w",
    "compare_crossings",
    "drag_force_n",
    "find_crossings",
    "grade_force_n",
    "hermite_crossing_time",
    "longitudinal_acceleration_mps2",
    "reconstruct",
    "recorded_crossings",
    "rolling_force_n",
    "thermal_derivative_k_per_s",
]

GRAVITY_MPS2: float = 9.80665
"""Standard gravity, as used by ``F_grade = m g sin(grade)``. A fixed constant."""

DEFAULT_SUBSTEPS: int = 8
"""Sub-intervals per recorded frame. The run under test uses one step per frame."""


# --------------------------------------------------------------------------- #
# Reference equations, retyped from the specification
# --------------------------------------------------------------------------- #


def drag_force_n(air_density_kgpm3: float, cda_m2: float, speed_mps: float) -> float:
    """``F_drag = 0.5 * rho * CdA * v^2`` in newtons (a non-negative resistance)."""
    return 0.5 * air_density_kgpm3 * cda_m2 * speed_mps * speed_mps


def rolling_force_n(mass_kg: float, crr: float, grade_rad: float) -> float:
    """Rolling resistance ``crr * m * g * cos(grade)`` against the road normal load."""
    return crr * mass_kg * GRAVITY_MPS2 * math.cos(grade_rad)


def grade_force_n(mass_kg: float, grade_rad: float) -> float:
    """``F_grade = m * g * sin(grade)``; positive opposes motion when climbing."""
    return mass_kg * GRAVITY_MPS2 * math.sin(grade_rad)


def longitudinal_acceleration_mps2(
    mass_kg: float,
    drive_n: float,
    drag_n: float,
    rolling_n: float,
    grade_n: float,
) -> float:
    """``a = (F_drive - F_drag - F_roll - F_grade) / m`` in m/s^2."""
    if mass_kg <= 0.0:
        raise ValueError("mass must be positive")
    return (drive_n - drag_n - rolling_n - grade_n) / mass_kg


def battery_terminal_out_w(p_dc_deploy_w: float, eta_discharge: float) -> float:
    """``P_battery_out = P_dc_deploy / eta_discharge``."""
    if not 0.0 < eta_discharge <= 1.0:
        raise ValueError("eta_discharge must lie in (0, 1]")
    return p_dc_deploy_w / eta_discharge


def battery_terminal_in_w(p_dc_harvest_w: float, eta_charge: float) -> float:
    """``P_battery_in = eta_charge * P_dc_harvest``."""
    if not 0.0 < eta_charge <= 1.0:
        raise ValueError("eta_charge must lie in (0, 1]")
    return eta_charge * p_dc_harvest_w


def thermal_derivative_k_per_s(
    temperature_k: float,
    c_th_j_per_k: float,
    loss_power_w: float,
    h_w_per_k: float,
    ambient_k: float,
) -> float:
    """``dT/dt`` from ``C_th dT/dt = P_loss - h (T - T_ambient)``."""
    if c_th_j_per_k <= 0.0:
        raise ValueError("thermal capacity must be positive")
    if h_w_per_k < 0.0:
        raise ValueError("heat transfer coefficient must be non-negative")
    return (loss_power_w - h_w_per_k * (temperature_k - ambient_k)) / c_th_j_per_k


# --------------------------------------------------------------------------- #
# Parameters and geometry, read independently from the configuration documents
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CarParameters:
    """Plain float parameters the checker needs, lifted out of a ``CarConfig``.

    Only *documented configuration* is read. No simulator code is invoked to
    obtain any of these numbers.
    """

    car_config_id: str
    mass_kg: float
    cda_m2: float
    crr: float
    air_density_kgpm3: float
    eta_discharge: float
    eta_charge: float
    battery_energy_min_j: float
    battery_energy_max_j: float
    aux_load_w: float
    c_th_j_per_k: float
    h_w_per_k: float
    ambient_temperature_k: float

    @classmethod
    def from_car_config(cls, car: CarConfig) -> CarParameters:
        return cls(
            car_config_id=car.id,
            mass_kg=float(car.mass_kg.value),
            cda_m2=float(car.cda_m2.value),
            crr=float(car.crr.value),
            air_density_kgpm3=float(car.air_density_kgpm3.value),
            eta_discharge=float(car.eta_discharge.value),
            eta_charge=float(car.eta_charge.value),
            battery_energy_min_j=float(car.battery_energy_min_j.value),
            battery_energy_max_j=float(car.battery_energy_max_j.value),
            aux_load_w=float(car.aux_load_w.value),
            c_th_j_per_k=float(car.c_th_j_per_k.value),
            h_w_per_k=float(car.h_w_per_k.value),
            ambient_temperature_k=float(car.ambient_temperature_k.value),
        )


@dataclass(frozen=True, slots=True)
class TrackReference:
    """Independent re-implementation of the track's interpolated profiles.

    The breakpoint values are read from the track document; the interpolation
    (smoothstep between breakpoints, periodic closure at the lap) is written
    again here so a defect in the simulator's own table cannot cancel out
    against this check.
    """

    track_id: str
    length_m: float
    nodes_s_m: tuple[float, ...]
    curvature_inv_m: tuple[float, ...]
    grade_rad: tuple[float, ...]
    mu: tuple[float, ...]

    @classmethod
    def from_track_config(cls, track: TrackConfig) -> TrackReference:
        length = float(track.length_m.value)
        ordered = sorted(track.segments, key=lambda seg: float(seg.s_m.value))
        nodes = [float(seg.s_m.value) for seg in ordered]
        curvature = [float(seg.curvature_inv_m.value) for seg in ordered]
        grade = [float(seg.grade_rad.value) for seg in ordered]
        mu = [float(seg.mu.value) for seg in ordered]
        return cls(
            track_id=track.id,
            length_m=length,
            nodes_s_m=(*nodes, length),
            curvature_inv_m=(*curvature, curvature[0]),
            grade_rad=(*grade, grade[0]),
            mu=(*mu, mu[0]),
        )

    def _interpolate(self, table: tuple[float, ...], s_m: float) -> float:
        s = s_m % self.length_m
        index = min(max(bisect_right(self.nodes_s_m, s) - 1, 0), len(self.nodes_s_m) - 2)
        low = self.nodes_s_m[index]
        span = self.nodes_s_m[index + 1] - low
        t = (s - low) / span if span > 0.0 else 0.0
        weight = t * t * (3.0 - 2.0 * t)
        return table[index] + weight * (table[index + 1] - table[index])

    def grade_at(self, s_m: float) -> float:
        return self._interpolate(self.grade_rad, s_m)

    def curvature_at(self, s_m: float) -> float:
        return self._interpolate(self.curvature_inv_m, s_m)

    def mu_at(self, s_m: float) -> float:
        return self._interpolate(self.mu, s_m)


# --------------------------------------------------------------------------- #
# The recorded trajectory
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TrajectoryFrame:
    """One recorded frame: the state at both ends plus what acted across it.

    ``substeps`` is how many sub-steps the *simulator* took inside this frame.
    When it is greater than one the instantaneous powers and forces recorded
    here belong to the last sub-step only, which the reconstruction reports
    rather than silently absorbing.
    """

    index: int
    start_time_s: float
    end_time_s: float
    dt_s: float
    substeps: int
    profile: DeploymentProfile

    start_progress_m: float
    end_progress_m: float
    start_speed_mps: float
    end_speed_mps: float
    start_temperature_k: float
    end_temperature_k: float
    start_battery_energy_j: float
    end_battery_energy_j: float
    start_lap: int
    end_lap: int

    deploy_power_dc_w: float
    harvest_power_dc_w: float
    auxiliary_power_w: float
    electrical_loss_power_w: float
    drive_force_n: float
    mechanical_braking_power_w: float

    delta_deployed_dc_j: float
    delta_harvested_dc_j: float
    delta_auxiliary_j: float
    delta_battery_out_j: float
    delta_battery_in_j: float
    delta_recharge_cumulative_j: float


@dataclass(frozen=True, slots=True)
class RecordedTrajectory:
    """Everything the independent checker is allowed to see about one run."""

    car_id: str
    scenario_id: str
    bundle_hash: str
    seed: int
    car: CarParameters
    track: TrackReference
    frames: tuple[TrajectoryFrame, ...]
    initial_battery_energy_j: float
    final_battery_energy_j: float
    final_recharge_cumulative_j: float
    simulator_close_error_j: float
    simulator_integrator: str

    @property
    def duration_s(self) -> float:
        if not self.frames:
            return 0.0
        return self.frames[-1].end_time_s - self.frames[0].start_time_s

    @property
    def progress_samples(self) -> tuple[ProgressSample, ...]:
        if not self.frames:
            return ()
        first = self.frames[0]
        samples = [
            ProgressSample(
                session_time_s=first.start_time_s,
                progress_m=first.start_progress_m,
                speed_mps=first.start_speed_mps,
            )
        ]
        samples.extend(
            ProgressSample(
                session_time_s=frame.end_time_s,
                progress_m=frame.end_progress_m,
                speed_mps=frame.end_speed_mps,
            )
            for frame in self.frames
        )
        return tuple(samples)

    def with_frames(self, frames: Sequence[TrajectoryFrame]) -> RecordedTrajectory:
        """A copy carrying different frames, for corruption-injection tests."""
        ordered = tuple(frames)
        return RecordedTrajectory(
            car_id=self.car_id,
            scenario_id=self.scenario_id,
            bundle_hash=self.bundle_hash,
            seed=self.seed,
            car=self.car,
            track=self.track,
            frames=ordered,
            initial_battery_energy_j=(
                ordered[0].start_battery_energy_j if ordered else self.initial_battery_energy_j
            ),
            final_battery_energy_j=(
                ordered[-1].end_battery_energy_j if ordered else self.final_battery_energy_j
            ),
            final_recharge_cumulative_j=self.final_recharge_cumulative_j,
            simulator_close_error_j=self.simulator_close_error_j,
            simulator_integrator=self.simulator_integrator,
        )


class TrajectoryRecorder:
    """Records a trajectory while a caller drives the simulator.

    The recorder reads the simulator's private truth deliberately: the evaluator
    is entitled to it, a controller is not. It records data, never predictions.
    """

    def __init__(self, simulator: Simulator, car_id: str) -> None:
        self._sim = simulator
        self._car_id = car_id
        self._frames: list[TrajectoryFrame] = []
        world = simulator.world
        if car_id not in world.cars:
            raise KeyError(f"scenario has no car {car_id!r}")
        self._initial_energy = float(world.ledgers[car_id].energy_j)
        self._pending: dict[str, Any] | None = None

    def _capture_state(self) -> dict[str, Any]:
        world = self._sim.world
        state = world.cars[self._car_id]
        ledger = world.ledgers[self._car_id]
        return {
            "time_s": world.race.session_time_s,
            "progress_m": state.progress_m,
            "speed_mps": state.speed_mps,
            "temperature_k": state.battery_temperature_k,
            "battery_energy_j": ledger.energy_j,
            "lap": state.lap,
            "deployed_dc_j": ledger.deployed_dc_j,
            "harvested_dc_j": ledger.harvested_dc_j,
            "auxiliary_j": ledger.auxiliary_j,
            "battery_out_j": ledger.battery_out_j,
            "battery_in_j": ledger.battery_in_j,
            "recharge_cumulative_j": ledger.recharge_cumulative_j,
        }

    def before_step(self) -> None:
        """Latch the start-of-frame state. Call immediately before ``step``."""
        self._pending = self._capture_state()

    def after_step(self, report: Any) -> TrajectoryFrame:
        """Close the frame with the end-of-frame state and the step's report."""
        if self._pending is None:
            raise RuntimeError("after_step called without a matching before_step")
        start = self._pending
        self._pending = None
        end = self._capture_state()
        state = self._sim.world.cars[self._car_id]
        frame = TrajectoryFrame(
            index=len(self._frames),
            start_time_s=float(start["time_s"]),
            end_time_s=float(end["time_s"]),
            dt_s=float(end["time_s"]) - float(start["time_s"]),
            substeps=int(getattr(report, "substeps", 1)),
            profile=state.active_profile,
            start_progress_m=float(start["progress_m"]),
            end_progress_m=float(end["progress_m"]),
            start_speed_mps=float(start["speed_mps"]),
            end_speed_mps=float(end["speed_mps"]),
            start_temperature_k=float(start["temperature_k"]),
            end_temperature_k=float(end["temperature_k"]),
            start_battery_energy_j=float(start["battery_energy_j"]),
            end_battery_energy_j=float(end["battery_energy_j"]),
            start_lap=int(start["lap"]),
            end_lap=int(end["lap"]),
            deploy_power_dc_w=float(state.deploy_power_dc_w),
            harvest_power_dc_w=float(state.harvest_power_dc_w),
            auxiliary_power_w=float(state.auxiliary_power_w),
            electrical_loss_power_w=float(state.electrical_loss_power_w),
            drive_force_n=float(state.drive_force_n),
            mechanical_braking_power_w=float(state.mechanical_braking_power_w),
            delta_deployed_dc_j=float(end["deployed_dc_j"]) - float(start["deployed_dc_j"]),
            delta_harvested_dc_j=float(end["harvested_dc_j"]) - float(start["harvested_dc_j"]),
            delta_auxiliary_j=float(end["auxiliary_j"]) - float(start["auxiliary_j"]),
            delta_battery_out_j=float(end["battery_out_j"]) - float(start["battery_out_j"]),
            delta_battery_in_j=float(end["battery_in_j"]) - float(start["battery_in_j"]),
            delta_recharge_cumulative_j=(
                float(end["recharge_cumulative_j"]) - float(start["recharge_cumulative_j"])
            ),
        )
        self._frames.append(frame)
        return frame

    def finish(self) -> RecordedTrajectory:
        sim = self._sim
        world = sim.world
        ledger = world.ledgers[self._car_id]
        return RecordedTrajectory(
            car_id=self._car_id,
            scenario_id=world.bundle.scenario.id,
            bundle_hash=world.bundle.bundle_hash,
            seed=world.seed,
            car=CarParameters.from_car_config(world.car_configs[self._car_id]),
            track=TrackReference.from_track_config(world.track),
            frames=tuple(self._frames),
            initial_battery_energy_j=self._initial_energy,
            final_battery_energy_j=float(ledger.energy_j),
            final_recharge_cumulative_j=float(ledger.recharge_cumulative_j),
            simulator_close_error_j=float(ledger.close_error()),
            simulator_integrator=world.integrator,
        )


def record_trajectory(
    simulator: Simulator,
    *,
    car_id: str,
    dt_s: float,
    steps: int,
    controller: Callable[[Any], DriverAction] | None = None,
) -> RecordedTrajectory:
    """Drive ``simulator`` for ``steps`` frames and record ``car_id``'s trajectory.

    ``controller`` receives the ego observation and returns a ``DriverAction``.
    When it is ``None`` every car is driven by its configured policy.
    """
    if steps <= 0:
        raise ValueError("a recorded trajectory needs at least one frame")
    recorder = TrajectoryRecorder(simulator, car_id)
    for _ in range(steps):
        actions = None
        if controller is not None:
            observation = simulator.observe(car_id=car_id)[car_id]
            actions = {car_id: controller(observation)}
        recorder.before_step()
        report = simulator.step(actions, dt_s)
        recorder.after_step(report)
    return recorder.finish()


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One signed difference between the reconstruction and the simulator.

    ``difference`` is always ``independent - simulator`` in ``unit``. A positive
    battery-energy difference means the reconstruction believes the car should
    hold *more* energy than the simulator recorded.
    """

    name: str
    unit: str
    simulator_value: float
    independent_value: float
    difference: float
    tolerance: float
    within_tolerance: bool
    method: str
    relative_difference: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "simulator_value": self.simulator_value,
            "independent_value": self.independent_value,
            "difference": self.difference,
            "relative_difference": self.relative_difference,
            "tolerance": self.tolerance,
            "within_tolerance": self.within_tolerance,
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class FrameFinding:
    """A single frame whose recorded state cannot be explained by its flows."""

    frame_index: int
    session_time_s: float
    kind: str
    detail: str
    residual: float
    unit: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "session_time_s": self.session_time_s,
            "kind": self.kind,
            "detail": self.detail,
            "residual": self.residual,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class LedgerTolerances:
    """Tolerances measured on the shipped fixtures, then frozen.

    Established by running :func:`reconstruct` over all five shipped scenarios
    (both cars, 20 s at dt = 0.02 s, 1 000 frames) with the tolerances set
    effectively infinite, then freezing each one above the largest residual
    observed. ``NUMERICS_AND_VALIDATION.md``: "Establish numerical tolerances
    empirically using the reference solver, then freeze them before benchmark
    evaluation. Do not select a tolerance that hides a failing conservation
    test." The measured numbers behind each default are in ``handoffs/A13.md``.

    **Split frames are separated out deliberately.** A recorded frame carries a
    single set of instantaneous powers and forces. When the simulator split that
    frame at a regulatory boundary or a delayed driver action, those values
    describe only the final sub-step, so any check driven by them is limited by
    the *recording*, not by the simulator. Those checks therefore have their own,
    much looser, explicitly labelled tolerances, and the tight checks are stated
    over unsplit frames only. On the shipped ``test-loop`` scenarios 983 of 1 000
    frames are split, because every opponent action carries a 0.35 s reaction
    delay whose apply time falls inside almost every step.
    """

    battery_conversion_j: float = 1.0e-4
    """Whole-run bus-to-terminal conversion. Exact arithmetic; float noise only.
    Measured worst 3.7e-8 J; frozen at A03's own close-error scale of 1e-4 J."""

    cuk_identity_j: float = 1.0e-6
    """Sum of ``|d(recharge ledger) - d(harvested DC)|``. An exact identity: the
    CU-K ledger integrates the DC-bus quantity, so a ledger that integrated
    battery gain instead would differ by a factor of ``eta_charge``.
    Measured worst 0.0 J."""

    battery_power_frame_j: float = 1.0e-6
    """Per-unsplit-frame allowance for the power-integrated battery energy.
    Measured worst 1.3e-10 J per frame."""

    battery_power_split_frame_j: float = 2.0e1
    """Per-split-frame allowance for the same check. Measured worst 3.1 J."""

    cuk_power_frame_j: float = 1.0e-6
    """Per-unsplit-frame allowance for the power-integrated CU-K ledger."""

    cuk_power_split_frame_j: float = 2.0e1
    """Per-split-frame allowance for the same check. Measured worst 1.2 J."""

    thermal_k: float = 1.0e-9
    """Worst unsplit-frame RK4 thermal residual against the analytic step.
    Measured worst 1.7e-13 K."""

    thermal_split_k: float = 1.0e-2
    """Worst split-frame thermal residual. Measured worst 1.8e-3 K."""

    motion_speed_mps: float = 1.0e-2
    """Worst unsplit-frame speed residual of the independent RK4 restart.
    Measured worst 7.5e-4 m/s."""

    motion_speed_split_mps: float = 2.0
    """Worst split-frame speed residual. Measured worst 0.29 m/s."""

    work_energy_frame_j: float = 5.0
    """Per-unsplit-frame work/kinetic-energy balance residual. Measured worst
    1.28 J per frame (``loop-regen-disabled``, where only 17 of 1 000 frames are
    unsplit and one of them is a hard braking frame); every other fixture is
    below 0.16 J per frame."""

    work_energy_split_frame_j: float = 2.0e2
    """Per-split-frame allowance for the same balance. Measured worst 38.3 J."""

    free_energy_j: float = 1.0e-3
    """Per-frame battery balance residual above which a frame is flagged as
    unexplained energy. Measured worst 1.5e-11 J."""


@dataclass(frozen=True, slots=True)
class LedgerAudit:
    """The result of one independent reconstruction."""

    car_id: str
    scenario_id: str
    frame_count: int
    duration_s: float
    substeps_per_frame: int
    frames_with_split_steps: int
    discrepancies: tuple[Discrepancy, ...]
    frame_findings: tuple[FrameFinding, ...]
    tolerances: LedgerTolerances
    notes: tuple[str, ...] = ()

    @property
    def flagged(self) -> bool:
        """True when anything failed its stated tolerance."""
        return bool(self.frame_findings) or any(not d.within_tolerance for d in self.discrepancies)

    def by_name(self, name: str) -> Discrepancy:
        for item in self.discrepancies:
            if item.name == name:
                return item
        raise KeyError(f"no discrepancy named {name!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "car_id": self.car_id,
            "scenario_id": self.scenario_id,
            "frame_count": self.frame_count,
            "duration_s": self.duration_s,
            "substeps_per_frame": self.substeps_per_frame,
            "frames_with_split_steps": self.frames_with_split_steps,
            "discrepancies": [d.as_dict() for d in self.discrepancies],
            "frame_findings": [f.as_dict() for f in self.frame_findings],
            "flagged": self.flagged,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# Reconstruction
# --------------------------------------------------------------------------- #


def _relative(difference: float, scale: float) -> float | None:
    return difference / scale if scale > 0.0 else None


def _rk4_speed(
    car: CarParameters,
    track: TrackReference,
    *,
    speed_mps: float,
    progress_m: float,
    drive_n: float,
    dt_s: float,
    substeps: int,
) -> tuple[float, float, float]:
    """Integrate the spec force balance at high resolution over one frame.

    Returns ``(speed, progress, drive_work_j)``. ``drive_n`` is the applied
    longitudinal force recorded for the frame and is held constant; everything
    resisting it is recomputed here from the reference equations.
    """
    h = dt_s / substeps
    speed = speed_mps
    progress = progress_m
    drive_work = 0.0

    def accel(v: float, s: float) -> float:
        v = max(0.0, v)
        grade = track.grade_at(s % track.length_m)
        return longitudinal_acceleration_mps2(
            car.mass_kg,
            drive_n,
            drag_force_n(car.air_density_kgpm3, car.cda_m2, v),
            rolling_force_n(car.mass_kg, car.crr, grade),
            grade_force_n(car.mass_kg, grade),
        )

    for _ in range(substeps):
        k1v = accel(speed, progress)
        k1p = speed
        k2v = accel(speed + 0.5 * h * k1v, progress + 0.5 * h * k1p)
        k2p = speed + 0.5 * h * k1v
        k3v = accel(speed + 0.5 * h * k2v, progress + 0.5 * h * k2p)
        k3p = speed + 0.5 * h * k2v
        k4v = accel(speed + h * k3v, progress + h * k3p)
        k4p = speed + h * k3v
        speed_next = speed + (h / 6.0) * (k1v + 2.0 * k2v + 2.0 * k3v + k4v)
        progress_next = progress + (h / 6.0) * (k1p + 2.0 * k2p + 2.0 * k3p + k4p)
        # Simpson over the sub-interval for the drive work: F is constant, so
        # this is the distance integral, which is exactly the RK4 increment.
        drive_work += drive_n * (progress_next - progress)
        speed = max(0.0, speed_next)
        progress = progress_next
    return speed, progress, drive_work


def _rk4_temperature(
    car: CarParameters,
    *,
    temperature_k: float,
    loss_power_w: float,
    dt_s: float,
    substeps: int,
) -> float:
    h = dt_s / substeps
    temperature = temperature_k
    for _ in range(substeps):
        k1 = thermal_derivative_k_per_s(
            temperature, car.c_th_j_per_k, loss_power_w, car.h_w_per_k, car.ambient_temperature_k
        )
        k2 = thermal_derivative_k_per_s(
            temperature + 0.5 * h * k1,
            car.c_th_j_per_k,
            loss_power_w,
            car.h_w_per_k,
            car.ambient_temperature_k,
        )
        k3 = thermal_derivative_k_per_s(
            temperature + 0.5 * h * k2,
            car.c_th_j_per_k,
            loss_power_w,
            car.h_w_per_k,
            car.ambient_temperature_k,
        )
        k4 = thermal_derivative_k_per_s(
            temperature + h * k3,
            car.c_th_j_per_k,
            loss_power_w,
            car.h_w_per_k,
            car.ambient_temperature_k,
        )
        temperature += (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
    return temperature


def reconstruct(
    trajectory: RecordedTrajectory,
    *,
    substeps: int = DEFAULT_SUBSTEPS,
    tolerances: LedgerTolerances | None = None,
) -> LedgerAudit:
    """Rebuild the ledgers, the work balance and the thermal state independently.

    Every quantity below is computed from the reference equations and the
    recorded trajectory. Nothing is read back from the simulator except the
    numbers being checked.
    """
    if substeps < 1:
        raise ValueError("the independent integrator needs at least one sub-step")
    if not trajectory.frames:
        raise ValueError("cannot reconstruct an empty trajectory")
    tol = tolerances or LedgerTolerances()
    car = trajectory.car
    track = trajectory.track

    energy_from_bus = trajectory.initial_battery_energy_j
    energy_from_power = trajectory.initial_battery_energy_j
    cuk_identity_j = 0.0
    cuk_from_power_j = 0.0
    findings: list[FrameFinding] = []
    split_frames = 0

    worst_speed = {False: 0.0, True: 0.0}
    worst_speed_frame = {False: -1, True: -1}
    worst_thermal = {False: 0.0, True: 0.0}
    work_residual = {False: 0.0, True: 0.0}
    throughput_j = 0.0

    for frame in trajectory.frames:
        split = frame.substeps > 1
        if split:
            split_frames += 1

        # --- (1) bus-to-terminal conversion, exact arithmetic --------------- #
        gain_j = battery_terminal_in_w(frame.delta_harvested_dc_j, car.eta_charge)
        drain_j = battery_terminal_out_w(frame.delta_deployed_dc_j, car.eta_discharge)
        expected_delta = gain_j - drain_j - frame.delta_auxiliary_j
        energy_from_bus += expected_delta
        recorded_delta = frame.end_battery_energy_j - frame.start_battery_energy_j
        residual = recorded_delta - expected_delta
        throughput_j += abs(frame.delta_deployed_dc_j) + abs(frame.delta_harvested_dc_j)
        if abs(residual) > tol.free_energy_j:
            findings.append(
                FrameFinding(
                    frame_index=frame.index,
                    session_time_s=frame.start_time_s,
                    kind="unexplained_battery_energy",
                    detail=(
                        "recorded battery energy change does not equal "
                        "eta_charge*harvest_dc - deploy_dc/eta_discharge - auxiliary"
                    ),
                    residual=residual,
                    unit="J",
                )
            )

        # --- (2) battery energy re-integrated from instantaneous powers ----- #
        net_w = (
            battery_terminal_in_w(frame.harvest_power_dc_w, car.eta_charge)
            - battery_terminal_out_w(frame.deploy_power_dc_w, car.eta_discharge)
            - frame.auxiliary_power_w
        )
        step_h = frame.dt_s / substeps
        for _ in range(substeps):
            energy_from_power += net_w * step_h

        # --- (3) the CU-K ledger integrates the DC-bus quantity ------------- #
        cuk_identity_j += abs(frame.delta_recharge_cumulative_j - frame.delta_harvested_dc_j)
        cuk_from_power_j += frame.harvest_power_dc_w * frame.dt_s

        # --- (4) motion, restarted from the recorded start of every frame --- #
        speed_end, _progress, _work = _rk4_speed(
            car,
            track,
            speed_mps=frame.start_speed_mps,
            progress_m=frame.start_progress_m,
            drive_n=frame.drive_force_n,
            dt_s=frame.dt_s,
            substeps=substeps,
        )
        speed_residual = speed_end - frame.end_speed_mps
        if abs(speed_residual) > abs(worst_speed[split]):
            worst_speed[split] = speed_residual
            worst_speed_frame[split] = frame.index

        # --- (5) work / kinetic-energy balance on the recorded trajectory --- #
        kinetic_change = (
            0.5
            * car.mass_kg
            * (frame.end_speed_mps * frame.end_speed_mps - frame.start_speed_mps * frame.start_speed_mps)
        )
        drive_work = frame.drive_force_n * (frame.end_progress_m - frame.start_progress_m)
        resistive_work = _resistive_work_j(car, track, frame=frame, substeps=substeps)
        work_residual[split] += (drive_work - resistive_work) - kinetic_change

        # --- (6) thermal state ---------------------------------------------- #
        temperature_end = _rk4_temperature(
            car,
            temperature_k=frame.start_temperature_k,
            loss_power_w=frame.electrical_loss_power_w,
            dt_s=frame.dt_s,
            substeps=substeps,
        )
        thermal_residual = temperature_end - frame.end_temperature_k
        if abs(thermal_residual) > abs(worst_thermal[split]):
            worst_thermal[split] = thermal_residual

    total = len(trajectory.frames)
    unsplit_frames = total - split_frames
    final_recorded = trajectory.final_battery_energy_j
    bus_difference = energy_from_bus - final_recorded
    power_difference = energy_from_power - final_recorded
    power_tolerance = (
        tol.battery_power_frame_j * unsplit_frames + tol.battery_power_split_frame_j * split_frames
    )
    cuk_difference = cuk_from_power_j - trajectory.final_recharge_cumulative_j
    cuk_power_tolerance = tol.cuk_power_frame_j * unsplit_frames + tol.cuk_power_split_frame_j * split_frames
    work_tolerance = tol.work_energy_frame_j * unsplit_frames
    work_split_tolerance = tol.work_energy_split_frame_j * split_frames

    discrepancies = (
        Discrepancy(
            name="battery_energy_from_bus_ledgers",
            unit="J",
            simulator_value=final_recorded,
            independent_value=energy_from_bus,
            difference=bus_difference,
            relative_difference=_relative(bus_difference, throughput_j),
            tolerance=tol.battery_conversion_j,
            within_tolerance=abs(bus_difference) <= tol.battery_conversion_j,
            method=(
                "E0 + sum(eta_charge*dE_harvest_dc - dE_deploy_dc/eta_discharge - dE_aux) over every "
                "frame, using only the DC-bus and auxiliary ledgers and the configured efficiencies"
            ),
        ),
        Discrepancy(
            name="battery_energy_from_powers",
            unit="J",
            simulator_value=final_recorded,
            independent_value=energy_from_power,
            difference=power_difference,
            relative_difference=_relative(power_difference, throughput_j),
            tolerance=power_tolerance,
            within_tolerance=abs(power_difference) <= power_tolerance,
            method=(
                f"integration of eta_charge*P_harvest_dc - P_deploy_dc/eta_discharge - P_aux at "
                f"{substeps} sub-intervals per frame; tolerance derived from {unsplit_frames} unsplit "
                f"and {split_frames} split frames"
            ),
        ),
        Discrepancy(
            name="cuk_ledger_equals_dc_bus_harvest",
            unit="J",
            simulator_value=0.0,
            independent_value=cuk_identity_j,
            difference=cuk_identity_j,
            relative_difference=None,
            tolerance=tol.cuk_identity_j,
            within_tolerance=cuk_identity_j <= tol.cuk_identity_j,
            method=(
                "sum of |d(recharge ledger) - d(harvested DC)| per frame; a ledger that integrated "
                "battery gain instead of the DC bus would differ by a factor of eta_charge"
            ),
        ),
        Discrepancy(
            name="cuk_ledger_from_harvest_power",
            unit="J",
            simulator_value=trajectory.final_recharge_cumulative_j,
            independent_value=cuk_from_power_j,
            difference=cuk_difference,
            relative_difference=_relative(cuk_difference, trajectory.final_recharge_cumulative_j),
            tolerance=cuk_power_tolerance,
            within_tolerance=abs(cuk_difference) <= cuk_power_tolerance,
            method="integral of the recorded DC-bus harvest power over the run",
        ),
        Discrepancy(
            name="worst_unsplit_frame_speed_residual",
            unit="m/s",
            simulator_value=0.0,
            independent_value=worst_speed[False],
            difference=worst_speed[False],
            relative_difference=None,
            tolerance=tol.motion_speed_mps,
            within_tolerance=abs(worst_speed[False]) <= tol.motion_speed_mps,
            method=(
                f"RK4 at {substeps} sub-intervals restarted from each unsplit frame's recorded start "
                f"(worst frame index {worst_speed_frame[False]})"
            ),
        ),
        Discrepancy(
            name="worst_split_frame_speed_residual",
            unit="m/s",
            simulator_value=0.0,
            independent_value=worst_speed[True],
            difference=worst_speed[True],
            relative_difference=None,
            tolerance=tol.motion_speed_split_mps,
            within_tolerance=abs(worst_speed[True]) <= tol.motion_speed_split_mps,
            method=(
                "same integrator on frames the simulator split; the recorded drive force describes "
                f"only the final sub-step there, so this check is limited by the recording "
                f"(worst frame index {worst_speed_frame[True]})"
            ),
        ),
        Discrepancy(
            name="work_energy_balance_unsplit",
            unit="J",
            simulator_value=0.0,
            independent_value=work_residual[False],
            difference=work_residual[False],
            relative_difference=None,
            tolerance=work_tolerance,
            within_tolerance=abs(work_residual[False]) <= work_tolerance,
            method=(
                "sum over unsplit frames of (F_drive * ds - integral of resistive force * v dt) minus "
                "the change in kinetic energy, with the resistive forces recomputed from the reference "
                "equations by composite Simpson"
            ),
        ),
        Discrepancy(
            name="work_energy_balance_split",
            unit="J",
            simulator_value=0.0,
            independent_value=work_residual[True],
            difference=work_residual[True],
            relative_difference=None,
            tolerance=work_split_tolerance,
            within_tolerance=abs(work_residual[True]) <= work_split_tolerance,
            method="the same balance over frames the simulator split; limited by the recording",
        ),
        Discrepancy(
            name="worst_unsplit_frame_thermal_residual",
            unit="K",
            simulator_value=0.0,
            independent_value=worst_thermal[False],
            difference=worst_thermal[False],
            relative_difference=None,
            tolerance=tol.thermal_k,
            within_tolerance=abs(worst_thermal[False]) <= tol.thermal_k,
            method=f"RK4 at {substeps} sub-intervals on C_th dT/dt = P_loss - h (T - T_ambient)",
        ),
        Discrepancy(
            name="worst_split_frame_thermal_residual",
            unit="K",
            simulator_value=0.0,
            independent_value=worst_thermal[True],
            difference=worst_thermal[True],
            relative_difference=None,
            tolerance=tol.thermal_split_k,
            within_tolerance=abs(worst_thermal[True]) <= tol.thermal_split_k,
            method="the same integrator on split frames; limited by the recording",
        ),
    )

    notes: list[str] = []
    if split_frames:
        notes.append(
            f"{split_frames} of {total} frames were split by the simulator. In those frames the "
            "recorded instantaneous powers and forces describe only the final sub-step, so every "
            "check driven by them is limited by the recording rather than by the simulator; those "
            "checks are reported separately and carry their own looser tolerances."
        )
    if all(track.grade_at(s) == 0.0 for s in (0.0, 0.25, 0.5, 0.75)):
        notes.append(
            f"track {track.track_id} is level at every sampled point, so the F_grade term contributes "
            "nothing to this trajectory and is exercised only by the unit test"
        )

    return LedgerAudit(
        car_id=trajectory.car_id,
        scenario_id=trajectory.scenario_id,
        frame_count=total,
        duration_s=trajectory.duration_s,
        substeps_per_frame=substeps,
        frames_with_split_steps=split_frames,
        discrepancies=discrepancies,
        frame_findings=tuple(findings),
        tolerances=tol,
        notes=tuple(notes),
    )


def _resistive_work_j(
    car: CarParameters,
    track: TrackReference,
    *,
    frame: TrajectoryFrame,
    substeps: int,
) -> float:
    """Work done against drag, rolling resistance and grade over one frame.

    Composite Simpson in *time* over a linear speed profile between the frame's
    recorded endpoints. The forces are recomputed from the reference equations
    at every node rather than reusing the frame's recorded force diagnostics.
    """
    v0 = frame.start_speed_mps
    v1 = frame.end_speed_mps
    p0 = frame.start_progress_m

    def integrand(tau: float) -> float:
        v = v0 + tau * (v1 - v0)
        # Position from the trapezoidal displacement of a linear speed profile.
        s = p0 + frame.dt_s * tau * (v0 + 0.5 * tau * (v1 - v0))
        grade = track.grade_at(s % track.length_m)
        resist = (
            drag_force_n(car.air_density_kgpm3, car.cda_m2, v)
            + rolling_force_n(car.mass_kg, car.crr, grade)
            + grade_force_n(car.mass_kg, grade)
        )
        return resist * v

    nodes = 2 * substeps
    h = 1.0 / nodes
    total = integrand(0.0) + integrand(1.0)
    for index in range(1, nodes):
        weight = 4.0 if index % 2 else 2.0
        total += weight * integrand(index * h)
    return total * (h / 3.0) * frame.dt_s


# --------------------------------------------------------------------------- #
# Independent line-crossing reference
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProgressSample:
    """One sample of the progress trace, with its own speed."""

    session_time_s: float
    progress_m: float
    speed_mps: float


@dataclass(frozen=True, slots=True)
class Crossing:
    """A reconstructed crossing of a named line."""

    label: str
    lap: int
    threshold_progress_m: float
    session_time_s: float
    method: str = "cubic_hermite_bisection"


@dataclass(frozen=True, slots=True)
class CrossingDiscrepancy:
    """One reconstructed crossing against the simulator's own record."""

    label: str
    lap: int
    reference_time_s: float
    recorded_time_s: float | None
    difference_s: float | None
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lap": self.lap,
            "reference_time_s": self.reference_time_s,
            "recorded_time_s": self.recorded_time_s,
            "difference_s": self.difference_s,
            "status": self.status,
        }


def hermite_crossing_time(
    a: ProgressSample,
    b: ProgressSample,
    threshold_m: float,
    *,
    iterations: int = 200,
) -> float | None:
    """Time at which progress crosses ``threshold_m`` between two samples.

    Progress is reconstructed as the cubic Hermite interpolant of position with
    the sampled speeds as its derivatives — a strictly higher-order
    reconstruction than the linear interpolation the simulator splits its step
    with — and the crossing is located by bisection to machine precision.
    """
    if b.session_time_s <= a.session_time_s:
        return None
    if not (min(a.progress_m, b.progress_m) <= threshold_m <= max(a.progress_m, b.progress_m)):
        return None
    if a.progress_m == b.progress_m:
        return None
    h = b.session_time_s - a.session_time_s

    def position(tau: float) -> float:
        t2 = tau * tau
        t3 = t2 * tau
        h00 = 2.0 * t3 - 3.0 * t2 + 1.0
        h10 = t3 - 2.0 * t2 + tau
        h01 = -2.0 * t3 + 3.0 * t2
        h11 = t3 - t2
        return h00 * a.progress_m + h10 * h * a.speed_mps + h01 * b.progress_m + h11 * h * b.speed_mps

    low, high = 0.0, 1.0
    rising = b.progress_m > a.progress_m
    for _ in range(iterations):
        mid = 0.5 * (low + high)
        above = position(mid) >= threshold_m
        if above == rising:
            high = mid
        else:
            low = mid
    return a.session_time_s + 0.5 * (low + high) * h


def find_crossings(
    samples: Sequence[ProgressSample],
    *,
    track_length_m: float,
    lines: Mapping[str, float],
) -> tuple[Crossing, ...]:
    """Locate every crossing of every named line in a progress trace.

    ``lines`` maps a label to its lap coordinate ``s`` in metres. Progress is
    unwrapped, so a line at ``s`` is crossed at ``lap * length + s`` for each
    lap the trace covers.
    """
    if track_length_m <= 0.0:
        raise ValueError("track length must be positive")
    if len(samples) < 2:
        return ()
    ordered = sorted(samples, key=lambda s: s.session_time_s)
    lowest = min(sample.progress_m for sample in ordered)
    highest = max(sample.progress_m for sample in ordered)
    found: list[Crossing] = []
    for label, s_m in sorted(lines.items()):
        first_lap = math.floor((lowest - s_m) / track_length_m)
        last_lap = math.ceil((highest - s_m) / track_length_m)
        for lap in range(first_lap, last_lap + 1):
            threshold = lap * track_length_m + s_m
            if not lowest <= threshold <= highest:
                continue
            for previous, current in pairwise(ordered):
                moment = hermite_crossing_time(previous, current, threshold)
                if moment is not None:
                    found.append(
                        Crossing(
                            label=label,
                            lap=lap,
                            threshold_progress_m=threshold,
                            session_time_s=moment,
                        )
                    )
                    break
    return tuple(sorted(found, key=lambda c: (c.session_time_s, c.label)))


def recorded_crossings(simulator: Simulator, car_id: str) -> tuple[tuple[str, int, float], ...]:
    """The simulator's own checkpoint records for one car, as plain tuples."""
    return tuple(
        (record.checkpoint_id, record.lap, record.session_time_s)
        for record in simulator.world.checkpoint_records
        if record.car_id == car_id
    )


def compare_crossings(
    reference: Sequence[Crossing],
    recorded: Sequence[tuple[str, int, float]],
) -> tuple[CrossingDiscrepancy, ...]:
    """Match reconstructed crossings to recorded ones and report the differences.

    A crossing found by only one of the two is reported with an explicit status
    rather than dropped, because a *missing* crossing is the more serious defect.
    """
    recorded_map = {(label, lap): moment for label, lap, moment in recorded}
    seen: set[tuple[str, int]] = set()
    results: list[CrossingDiscrepancy] = []
    for crossing in reference:
        key = (crossing.label, crossing.lap)
        seen.add(key)
        moment = recorded_map.get(key)
        results.append(
            CrossingDiscrepancy(
                label=crossing.label,
                lap=crossing.lap,
                reference_time_s=crossing.session_time_s,
                recorded_time_s=moment,
                difference_s=None if moment is None else crossing.session_time_s - moment,
                status="matched" if moment is not None else "missing_from_simulator",
            )
        )
    for (label, lap), moment in sorted(recorded_map.items()):
        if (label, lap) in seen:
            continue
        results.append(
            CrossingDiscrepancy(
                label=label,
                lap=lap,
                reference_time_s=float("nan"),
                recorded_time_s=moment,
                difference_s=None,
                status="missing_from_reference",
            )
        )
    return tuple(results)
