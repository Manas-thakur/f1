"""Synthetic observation sequences for the estimation tests.

Everything here is generated in this file. Nothing imports
``afterlap_core.simulation`` -- these tests must not depend on another agent's
module, and more importantly the estimator must be demonstrably testable against
observation sequences whose hidden truth the estimator has no path to.

Two generators are provided:

``model_matched_run``
    Draws the own car from *exactly* the filter's declared process model plus its
    declared measurement noise. Coverage measured on this is a consistency check
    of the linearisation and the noise bookkeeping. It says nothing about a real
    car, and the handoff states that.

``throttled_run``
    Adds a proportional driver term the filter does not model, so the filter sees
    an unmodelled input and the RMSE reported is not a self-fulfilling number.

The rival generator produces gap and speed observations from a hidden mode
schedule. ``RivalTruth`` is a privileged label: only ``test_calibration.py`` and
the truth-mutation check read it, and neither hands it to the filter.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    Provenance,
    Quality,
    RivalIntention,
    SessionMode,
    SourceCapability,
    TelemetryEvent,
)
from afterlap_core.estimation import (
    EstimationContext,
    OwnCarConfig,
    RivalConfig,
    create_state,
    load_own_car_config,
    load_rival_config,
)
from afterlap_core.estimation.assembly import EstimatorState
from afterlap_core.estimation.config import MODE_ORDER

TRACK_LENGTH_M = 5200.0
SESSION_ID = "estimation-synthetic-001"
OWN_CAR_ID = "own"
RIVAL_CAR_ID = "rival-a"
SECOND_RIVAL_ID = "rival-b"
SYNTHETIC_NOTICE = "Synthetic generator. Not measured telemetry and not a calibrated car."


@dataclass(frozen=True, slots=True)
class OwnTruth:
    """Privileged own-car truth. Never handed to a filter."""

    time_s: float
    progress_m: float
    speed_mps: float
    acceleration_mps2: float
    energy_j: float
    power_w: float


@dataclass(frozen=True, slots=True)
class RivalTruth:
    """Privileged rival truth. Never handed to a filter."""

    time_s: float
    progress_m: float
    speed_mps: float
    energy_j: float
    mode: RivalIntention


@dataclass(frozen=True, slots=True)
class SyntheticRun:
    """One generated scenario: truth plus the observations a source would emit."""

    scenario_id: str
    own_truth: tuple[OwnTruth, ...]
    rival_truth: tuple[RivalTruth, ...]
    events: tuple[TelemetryEvent, ...]
    dt_s: float
    energy_channel: bool

    def events_until(self, cutoff_s: float) -> tuple[TelemetryEvent, ...]:
        return tuple(event for event in self.events if event.source_time_s <= cutoff_s)

    def own_truth_at(self, time_s: float) -> OwnTruth:
        return min(self.own_truth, key=lambda item: abs(item.time_s - time_s))

    def rival_truth_at(self, time_s: float) -> RivalTruth:
        return min(self.rival_truth, key=lambda item: abs(item.time_s - time_s))


def _event(
    sequence: int,
    car_id: str,
    channel: str,
    value: float | None,
    unit: str,
    source_time_s: float,
    *,
    quality: Quality = Quality.VALID,
    provenance: Provenance = Provenance.SIMULATED,
    latency_s: float = 0.02,
) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"{car_id}-{channel}-{sequence:06d}",
        session_id=SESSION_ID,
        car_id=car_id,
        sequence=sequence,
        source_time_s=source_time_s,
        received_time_s=source_time_s + latency_s,
        channel=channel,
        value=value,
        unit=unit,
        provenance=provenance,
        quality=quality,
    )


@dataclass(slots=True)
class _Sequencer:
    value: int = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def generate_own_truth(
    config: OwnCarConfig,
    *,
    steps: int,
    dt_s: float,
    seed: int,
    initial_speed_mps: float = 75.0,
    initial_energy_j: float = 2_400_000.0,
    throttle_gain: float = 0.0,
    target_speed_mps: float = 75.0,
    power_amplitude_w: float = 90_000.0,
) -> tuple[OwnTruth, ...]:
    """Integrate a hidden own-car trajectory.

    With ``throttle_gain == 0`` the trajectory is drawn from the filter's own
    declared process model, so a coverage measurement on it isolates the
    linearisation and the noise bookkeeping. A positive gain adds a driver term
    the filter does not model.
    """
    rng = np.random.default_rng(seed)
    tau = config.motion.acceleration_time_constant_s.value
    drag = config.motion.drag_per_m.value
    jerk_psd = config.motion.process_jerk_psd.value
    eta = config.energy.harvest_efficiency.value
    minimum = config.energy.physical_min_j.value
    maximum = config.energy.physical_max_j.value

    alpha = math.exp(-dt_s / tau)
    speed = initial_speed_mps
    acceleration = 0.0
    progress = 0.0
    energy = initial_energy_j
    rows: list[OwnTruth] = [
        OwnTruth(0.0, progress, speed, acceleration, energy, 0.0),
    ]
    for step in range(1, steps + 1):
        time_s = step * dt_s
        power = power_amplitude_w * math.sin(2.0 * math.pi * time_s / 9.0)
        equilibrium = -drag * speed * speed + throttle_gain * (target_speed_mps - speed)
        next_acceleration = equilibrium + (acceleration - equilibrium) * alpha
        next_acceleration += rng.normal(0.0, math.sqrt(jerk_psd * dt_s))
        next_speed = speed + 0.5 * (acceleration + next_acceleration) * dt_s
        next_progress = progress + 0.5 * (speed + next_speed) * dt_s
        drain = power * dt_s if power >= 0.0 else power * dt_s * eta
        energy = min(max(energy - drain, minimum), maximum)
        progress, speed, acceleration = next_progress, next_speed, next_acceleration
        rows.append(OwnTruth(time_s, progress, speed, acceleration, energy, power))
    return tuple(rows)


def generate_rival_truth(
    config: RivalConfig,
    own_truth: Sequence[OwnTruth],
    *,
    seed: int,
    mode_schedule: Sequence[tuple[float, RivalIntention]] | None = None,
    initial_gap_m: float = 48.0,
    initial_energy_j: float = 2_800_000.0,
    pace_bias_mps: float = 0.0,
) -> tuple[RivalTruth, ...]:
    """Integrate a hidden rival that follows a mode schedule.

    The rival's pace and energy drain use the same functional form the filter
    assumes, with an independent per-run pace bias. The filter is not told the
    schedule, the bias or the energy.
    """
    rng = np.random.default_rng(seed)
    schedule = tuple(mode_schedule or ((0.0, RivalIntention.NORMAL),))
    behaviour = config.behaviour
    base_speed = behaviour.base_speed_gain_mps.as_array()
    base_power = behaviour.base_power_w.as_array()
    reference = config.dynamics.deploy_reference_energy_j.value
    minimum = config.dynamics.energy_min_j.value
    maximum = config.dynamics.energy_max_j.value

    energy = initial_energy_j
    progress = own_truth[0].progress_m + initial_gap_m
    rows: list[RivalTruth] = []
    for index, own in enumerate(own_truth):
        mode = schedule[0][1]
        for start, candidate in schedule:
            if own.time_s >= start:
                mode = candidate
        mode_index = MODE_ORDER.index(mode)
        deploy = min(max(energy / reference, 0.0), 1.0)
        offset = pace_bias_mps + deploy * base_speed[mode_index]
        speed = own.speed_mps + offset
        if index > 0:
            dt = own.time_s - own_truth[index - 1].time_s
            progress += speed * dt
            energy = min(max(energy - deploy * base_power[mode_index] * dt, minimum), maximum)
        rows.append(RivalTruth(own.time_s, progress, speed, energy, mode))
    # A tiny unmodelled wobble so the rival is never exactly the filter's model.
    wobble = rng.normal(0.0, 0.05, size=len(rows))
    return tuple(
        replace(row, speed_mps=row.speed_mps + float(wobble[index])) for index, row in enumerate(rows)
    )


def build_events(
    own_truth: Sequence[OwnTruth],
    rival_truth: Sequence[RivalTruth],
    *,
    seed: int,
    energy_channel: bool = True,
    energy_period_s: float = 0.5,
    speed_sigma_mps: float = 0.2,
    progress_sigma_m: float = 0.6,
    energy_sigma_j: float = 15_000.0,
    rival_car_id: str = RIVAL_CAR_ID,
    dropout: tuple[float, float] | None = None,
) -> tuple[TelemetryEvent, ...]:
    """Emit the observations a source would publish for this hidden trajectory."""
    rng = np.random.default_rng(seed)
    sequencer = _Sequencer()
    events: list[TelemetryEvent] = []
    for index, own in enumerate(own_truth):
        if dropout is not None and dropout[0] <= own.time_s <= dropout[1]:
            continue
        events.append(
            _event(
                sequencer.next(),
                OWN_CAR_ID,
                "speed_mps",
                own.speed_mps + float(rng.normal(0.0, speed_sigma_mps)),
                "m/s",
                own.time_s,
            )
        )
        events.append(
            _event(
                sequencer.next(),
                OWN_CAR_ID,
                "progress_m",
                own.progress_m + float(rng.normal(0.0, progress_sigma_m)),
                "m",
                own.time_s,
            )
        )
        if energy_channel:
            events.append(
                _event(
                    sequencer.next(),
                    OWN_CAR_ID,
                    "electrical_power_w",
                    own.power_w,
                    "W",
                    own.time_s,
                )
            )
            if index % max(1, round(energy_period_s / 0.05)) == 0:
                events.append(
                    _event(
                        sequencer.next(),
                        OWN_CAR_ID,
                        "battery_energy_j",
                        own.energy_j + float(rng.normal(0.0, energy_sigma_j)),
                        "J",
                        own.time_s,
                    )
                )
    for rival in rival_truth:
        if dropout is not None and dropout[0] <= rival.time_s <= dropout[1]:
            continue
        events.append(
            _event(
                sequencer.next(),
                rival_car_id,
                "progress_m",
                rival.progress_m + float(rng.normal(0.0, progress_sigma_m)),
                "m",
                rival.time_s,
            )
        )
        events.append(
            _event(
                sequencer.next(),
                rival_car_id,
                "speed_mps",
                rival.speed_mps + float(rng.normal(0.0, speed_sigma_mps)),
                "m/s",
                rival.time_s,
            )
        )
    events.sort(key=lambda event: (event.source_time_s, event.car_id, event.channel))
    return tuple(events)


def make_run(
    own_config: OwnCarConfig,
    rival_config: RivalConfig,
    *,
    scenario_id: str,
    seed: int,
    duration_s: float = 20.0,
    dt_s: float = 0.05,
    energy_channel: bool = True,
    throttle_gain: float = 0.0,
    mode_schedule: Sequence[tuple[float, RivalIntention]] | None = None,
    initial_energy_j: float = 2_400_000.0,
    rival_energy_j: float = 2_800_000.0,
    rival_pace_bias_mps: float = 0.0,
    dropout: tuple[float, float] | None = None,
) -> SyntheticRun:
    steps = round(duration_s / dt_s)
    own_truth = generate_own_truth(
        own_config,
        steps=steps,
        dt_s=dt_s,
        seed=seed,
        throttle_gain=throttle_gain,
        initial_energy_j=initial_energy_j,
    )
    rival_truth = generate_rival_truth(
        rival_config,
        own_truth,
        seed=seed + 7919,
        mode_schedule=mode_schedule,
        initial_energy_j=rival_energy_j,
        pace_bias_mps=rival_pace_bias_mps,
    )
    events = build_events(
        own_truth,
        rival_truth,
        seed=seed + 104_729,
        energy_channel=energy_channel,
        dropout=dropout,
    )
    return SyntheticRun(
        scenario_id=scenario_id,
        own_truth=own_truth,
        rival_truth=rival_truth,
        events=events,
        dt_s=dt_s,
        energy_channel=energy_channel,
    )


def capability(*, with_energy: bool = True, source_id: str = "synthetic-source") -> SourceCapability:
    channels = ["speed_mps", "progress_m"]
    limitations = [SYNTHETIC_NOTICE]
    if with_energy:
        channels += ["battery_energy_j", "electrical_power_w", "battery_temperature_k"]
    else:
        limitations.append("no battery-energy channel; precise energy advice is unsupported")
    limitations.append("lateral placement not resolvable from this source")
    return SourceCapability(
        source_id=source_id,
        mode=SessionMode.SIMULATION,
        supported_channels=tuple(channels),
        measured_channels=tuple(channels),
        update_rates_hz={c: 20.0 for c in channels},
        clock_error_s=0.0,
        limitations=tuple(limitations),
    )


def make_context(
    cutoff_s: float,
    *,
    with_energy: bool = True,
    clock_uncertainty_s: float = 0.0,
    rival_car_ids: tuple[str, ...] = (RIVAL_CAR_ID,),
    integration_gap_s: float = 0.0,
    observation_dropout_s: float = 0.0,
    total_laps: int | None = 8,
    source_capability: SourceCapability | None = None,
) -> EstimationContext:
    declared = source_capability if source_capability is not None else capability(with_energy=with_energy)
    return EstimationContext(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        cutoff_s=cutoff_s,
        track_length_m=TRACK_LENGTH_M,
        clock_uncertainty_s=clock_uncertainty_s,
        total_laps=total_laps,
        rival_car_ids=rival_car_ids,
        capability=declared,
        integration_gap_s=({"electrical_power_w": integration_gap_s} if integration_gap_s else {}),
        expected_periods_s={channel: 0.05 for channel in declared.supported_channels},
        lateral_geometry_known=False,
        observation_dropout_s=observation_dropout_s,
    )


@dataclass(slots=True)
class MutatedTruth:
    """Container proving the tests can scramble truth without touching events."""

    own_truth: tuple[OwnTruth, ...] = ()
    rival_truth: tuple[RivalTruth, ...] = ()
    notes: list[str] = field(default_factory=list)


@pytest.fixture(scope="session")
def own_config() -> OwnCarConfig:
    return load_own_car_config()


@pytest.fixture(scope="session")
def rival_config() -> RivalConfig:
    return load_rival_config()


@pytest.fixture
def fresh_state(own_config: OwnCarConfig, rival_config: RivalConfig) -> EstimatorState:
    return create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=20260908,
        own_config=own_config,
        rival_config=rival_config,
    )


@pytest.fixture
def matched_run(own_config: OwnCarConfig, rival_config: RivalConfig) -> SyntheticRun:
    return make_run(own_config, rival_config, scenario_id="matched-01", seed=11)


@pytest.fixture
def throttled_run(own_config: OwnCarConfig, rival_config: RivalConfig) -> SyntheticRun:
    return make_run(
        own_config,
        rival_config,
        scenario_id="throttled-01",
        seed=23,
        throttle_gain=0.4,
    )


__all__ = [
    "OWN_CAR_ID",
    "RIVAL_CAR_ID",
    "SECOND_RIVAL_ID",
    "SESSION_ID",
    "TRACK_LENGTH_M",
    "MutatedTruth",
    "OwnTruth",
    "RivalTruth",
    "SyntheticRun",
    "build_events",
    "capability",
    "generate_own_truth",
    "generate_rival_truth",
    "make_context",
    "make_run",
]
