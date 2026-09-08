"""Own-car extended Kalman filter over progress, speed, acceleration and energy.

Process model
-------------

The state is ``x = [progress_m, speed_mps, acceleration_mps2, battery_energy_j]``
in float64. Over an elapsed ``dt`` with a measured DC-bus power input ``P``:

.. code-block:: text

    alpha  = exp(-dt / tau)                     relaxation of longitudinal accel
    a_eq   = -k_drag * v^2                      coasting drag equilibrium
    a'     = a_eq + (a - a_eq) * alpha
    v'     = v + 0.5 * (a + a') * dt            trapezoidal
    p'     = p + 0.5 * (v + v') * dt            trapezoidal
    e'     = e - drain(P, dt)

``drain`` is ``P * dt`` while deploying and ``P * dt * eta_harvest`` while
harvesting, because a joule taken off the DC bus and a joule stored in the
battery are not the same joule. The ``-k_drag * v^2`` term is the only state
nonlinearity, and it is what makes this an *extended* filter rather than a
linear one: ``d a' / d v = -2 * k_drag * v * (1 - alpha)`` propagates into the
speed and progress rows. :func:`MotionModel.jacobian` writes that derivative out
by hand and ``tests/estimation/test_ekf.py`` checks it against a central
finite difference.

Process noise
-------------

The motion block uses the standard continuous white-noise-jerk discretisation
driven by ``process_jerk_psd``. Two extra positive terms are added:

* clock uncertainty ``sigma_c`` inflates the progress and speed variances by
  ``(v * sigma_c)^2`` and ``(a * sigma_c)^2`` -- an uncertain elapsed time is an
  uncertain distance travelled;
* the energy variance grows by ``(power_model_sigma_w * dt)^2`` plus
  ``(unobserved_gap_sigma_w * integration_gap_s)^2``, where the gap comes from
  :mod:`afterlap_core.data.quality`. An unobserved stretch of the power channel
  is never integrated as zero power.

Every covariance update uses the Joseph form, so the posterior stays symmetric
positive semi-definite instead of drifting through rounding.

Energy observability
--------------------

``battery_energy_j`` is only initialised by a battery-state measurement the
source declares it actually measures. Without one the filter publishes an
explicitly missing ``ScalarValue`` together with a ``physical_bounds``
``IntervalValue``, and ``own_energy_capability`` is False. Integrated power still
narrows that interval from the reachable-set side -- that is partial energy
information -- but it never produces a point value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from afterlap_contracts import (
    IntervalValue,
    OwnCarEstimate,
    Provenance,
    Quality,
    ScalarValue,
)
from afterlap_core.timebase import classify_freshness, laps_and_s, wrap_s

from .config import OwnCarConfig
from .context import OWN_CAR_CHANNELS, EstimationContext, FamilyDiagnostic, Observation

STATE_PROGRESS = 0
STATE_SPEED = 1
STATE_ACCELERATION = 2
STATE_ENERGY = 3
STATE_DIM = 4

STATE_NAMES: tuple[str, ...] = ("progress_m", "speed_mps", "acceleration_mps2", "battery_energy_j")

#: Half-width, in sigmas, of the reachable-set bound used for partial energy.
REACHABLE_SET_SIGMAS = 3.0


@dataclass(frozen=True, slots=True)
class MotionModel:
    """The nonlinear motion map and its hand-written Jacobian."""

    acceleration_time_constant_s: float
    drag_per_m: float

    def __post_init__(self) -> None:
        if self.acceleration_time_constant_s <= 0.0:
            raise ValueError("acceleration time constant must be positive")
        if self.drag_per_m < 0.0:
            raise ValueError("drag coefficient cannot be negative")

    def _alpha(self, dt_s: float) -> float:
        return math.exp(-dt_s / self.acceleration_time_constant_s)

    def step(self, state: np.ndarray, dt_s: float, *, energy_change_j: float = 0.0) -> np.ndarray:
        """Advance ``state`` by ``dt_s``. ``energy_change_j`` is an exogenous input."""
        if dt_s < 0.0:
            raise ValueError("the motion model never runs backwards")
        p, v, a, e = (float(state[i]) for i in range(STATE_DIM))
        alpha = self._alpha(dt_s)
        a_eq = -self.drag_per_m * v * v
        a_next = a_eq + (a - a_eq) * alpha
        v_next = v + 0.5 * (a + a_next) * dt_s
        p_next = p + 0.5 * (v + v_next) * dt_s
        e_next = e + energy_change_j
        return np.array([p_next, v_next, a_next, e_next], dtype=np.float64)

    def jacobian(self, state: np.ndarray, dt_s: float) -> np.ndarray:
        """d step / d state, written out by hand.

        Derivations, with ``alpha = exp(-dt / tau)``::

            d a' / d v = -2 * k * v * (1 - alpha)
            d a' / d a = alpha
            d v' / d v = 1 + 0.5 * dt * (d a' / d v)
            d v' / d a = 0.5 * dt * (1 + alpha)
            d p' / d v = 0.5 * dt * (1 + d v' / d v)
            d p' / d a = 0.5 * dt * (d v' / d a)

        Energy is decoupled from motion in the process model: the filter
        integrates a *measured* power input, it does not infer energy from how
        the car is moving.
        """
        if dt_s < 0.0:
            raise ValueError("the motion model never runs backwards")
        v = float(state[STATE_SPEED])
        alpha = self._alpha(dt_s)
        da_dv = -2.0 * self.drag_per_m * v * (1.0 - alpha)
        da_da = alpha
        dv_dv = 1.0 + 0.5 * dt_s * da_dv
        dv_da = 0.5 * dt_s * (1.0 + alpha)
        dp_dv = 0.5 * dt_s * (1.0 + dv_dv)
        dp_da = 0.5 * dt_s * dv_da
        jacobian = np.zeros((STATE_DIM, STATE_DIM), dtype=np.float64)
        jacobian[STATE_PROGRESS, STATE_PROGRESS] = 1.0
        jacobian[STATE_PROGRESS, STATE_SPEED] = dp_dv
        jacobian[STATE_PROGRESS, STATE_ACCELERATION] = dp_da
        jacobian[STATE_SPEED, STATE_SPEED] = dv_dv
        jacobian[STATE_SPEED, STATE_ACCELERATION] = dv_da
        jacobian[STATE_ACCELERATION, STATE_SPEED] = da_dv
        jacobian[STATE_ACCELERATION, STATE_ACCELERATION] = da_da
        jacobian[STATE_ENERGY, STATE_ENERGY] = 1.0
        return jacobian


def motion_process_noise(jerk_psd: float, dt_s: float) -> np.ndarray:
    """Continuous white-noise-jerk covariance for the ``[p, v, a]`` block."""
    dt2 = dt_s * dt_s
    dt3 = dt2 * dt_s
    dt4 = dt3 * dt_s
    dt5 = dt4 * dt_s
    return jerk_psd * np.array(
        [
            [dt5 / 20.0, dt4 / 8.0, dt3 / 6.0],
            [dt4 / 8.0, dt3 / 3.0, dt2 / 2.0],
            [dt3 / 6.0, dt2 / 2.0, dt_s],
        ],
        dtype=np.float64,
    )


@dataclass(slots=True)
class EnergyLedger:
    """Battery-side energy bookkeeping, kept separate from the motion state.

    ``initialised`` is the observability gate. ``delta_j`` is the net battery
    energy change integrated from measured power since the filter started, and
    ``delta_variance`` is its uncertainty including unobserved integration time.
    """

    initialised: bool = False
    initialised_at_s: float | None = None
    initial_source: str | None = None
    delta_j: float = 0.0
    delta_variance: float = 0.0
    integrated_seconds: float = 0.0
    unobserved_seconds: float = 0.0
    last_power_w: float | None = None
    last_power_at_s: float | None = None
    corrections: int = 0
    last_correction_at_s: float | None = None

    def reachable_interval(self, minimum_j: float, maximum_j: float) -> tuple[float, float]:
        """Support of the current energy given an unknown start inside the window.

        ``e_now = e_start + delta`` with ``e_start`` anywhere in the physical
        window, so the reachable set is ``[min + delta_lo, max + delta_hi]``
        clipped back into the window. Integrated power therefore narrows the
        interval from one side without ever creating a point value.
        """
        spread = REACHABLE_SET_SIGMAS * math.sqrt(max(self.delta_variance, 0.0))
        lower = min(max(minimum_j + self.delta_j - spread, minimum_j), maximum_j)
        upper = max(min(maximum_j + self.delta_j + spread, maximum_j), minimum_j)
        if lower > upper:  # pragma: no cover - defensive against pathological configs
            lower, upper = minimum_j, maximum_j
        return lower, upper


@dataclass(slots=True)
class ChannelSample:
    """The newest usable sample seen on a channel the EKF does not carry in state."""

    value: float
    session_time_s: float
    provenance: Provenance
    quality: Quality
    source_id: str | None = None
    event_id: str | None = None


@dataclass(slots=True)
class OwnCarFilterState:
    """Everything the own-car filter needs to be restored exactly."""

    mean: np.ndarray
    covariance: np.ndarray
    time_s: float
    started: bool = False
    energy: EnergyLedger = field(default_factory=EnergyLedger)
    completed_laps: int = 0
    channels: dict[str, ChannelSample] = field(default_factory=dict)
    diagnostics: dict[str, FamilyDiagnostic] = field(default_factory=dict)
    smoothed_nis: dict[str, float] = field(default_factory=dict)
    update_counts: dict[str, int] = field(default_factory=dict)
    contributing_event_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def copy(self) -> OwnCarFilterState:
        return OwnCarFilterState(
            mean=self.mean.copy(),
            covariance=self.covariance.copy(),
            time_s=self.time_s,
            started=self.started,
            energy=EnergyLedger(**asdict(self.energy)),
            completed_laps=self.completed_laps,
            channels={k: ChannelSample(**asdict(v)) for k, v in self.channels.items()},
            diagnostics=dict(self.diagnostics),
            smoothed_nis=dict(self.smoothed_nis),
            update_counts=dict(self.update_counts),
            contributing_event_ids=list(self.contributing_event_ids),
            notes=list(self.notes),
        )


class OwnCarFilter:
    """The own-car EKF.

    The filter never invents an observation. A channel that was not observed
    contributes nothing but elapsed-time covariance growth, and a channel the
    source declares it does not measure can never initialise energy.
    """

    def __init__(self, config: OwnCarConfig) -> None:
        self.config = config
        self.model = MotionModel(
            acceleration_time_constant_s=config.motion.acceleration_time_constant_s.value,
            drag_per_m=config.motion.drag_per_m.value,
        )
        self.state = self._initial_state()

    # -- construction ---------------------------------------------------

    def _initial_state(self) -> OwnCarFilterState:
        initial = self.config.initial
        covariance = np.diag(
            np.array(
                [
                    initial.progress_sigma_m.value**2,
                    initial.speed_sigma_mps.value**2,
                    initial.acceleration_sigma_mps2.value**2,
                    initial.energy_sigma_j.value**2,
                ],
                dtype=np.float64,
            )
        )
        mean = np.array([0.0, 0.0, 0.0, math.nan], dtype=np.float64)
        return OwnCarFilterState(mean=mean, covariance=covariance, time_s=0.0)

    def reset(self) -> None:
        self.state = self._initial_state()

    # -- prediction -----------------------------------------------------

    def predict_to(
        self,
        target_time_s: float,
        *,
        clock_uncertainty_s: float = 0.0,
        integration_gap_s: float = 0.0,
        power_w: float | None = None,
    ) -> None:
        """Propagate mean and covariance forward to ``target_time_s``.

        The interval is subdivided into steps no longer than
        ``diagnostics.max_prediction_step_s`` so the first-order Jacobian stays a
        defensible linearisation. Covariance strictly grows with elapsed time and
        with clock uncertainty; nothing here ever shrinks it.
        """
        elapsed = target_time_s - self.state.time_s
        if elapsed < 0.0:
            raise ValueError(
                f"cannot predict backwards: target {target_time_s!r} precedes "
                f"state time {self.state.time_s!r}"
            )
        if elapsed == 0.0:
            return
        max_step = self.config.diagnostics.max_prediction_step_s.value
        steps = max(1, math.ceil(elapsed / max_step))
        dt = elapsed / steps
        gap_per_step = integration_gap_s / steps
        for _ in range(steps):
            self._predict_step(
                dt,
                clock_uncertainty_s=clock_uncertainty_s,
                integration_gap_s=gap_per_step,
                power_w=power_w,
            )
        self.state.time_s = target_time_s

    def _predict_step(
        self,
        dt_s: float,
        *,
        clock_uncertainty_s: float,
        integration_gap_s: float,
        power_w: float | None,
    ) -> None:
        state = self.state
        energy_change = self._energy_change(power_w, dt_s)
        jacobian = self.model.jacobian(state.mean, dt_s)
        state.mean = self.model.step(state.mean, dt_s, energy_change_j=energy_change)
        noise = self.process_noise(
            state.mean,
            dt_s,
            clock_uncertainty_s=clock_uncertainty_s,
            integration_gap_s=integration_gap_s,
        )
        covariance = jacobian @ state.covariance @ jacobian.T + noise
        state.covariance = 0.5 * (covariance + covariance.T)
        ledger = state.energy
        ledger.delta_j += energy_change
        ledger.delta_variance += float(noise[STATE_ENERGY, STATE_ENERGY])
        ledger.integrated_seconds += dt_s if power_w is not None else 0.0
        ledger.unobserved_seconds += integration_gap_s

    def _energy_change(self, power_w: float | None, dt_s: float) -> float:
        """Battery energy change over ``dt_s`` from a signed DC-bus power sample.

        Positive DC-bus power deploys and drains the battery one for one.
        Negative power harvests, and only ``harvest_efficiency`` of it arrives at
        the battery. Without a power sample the energy state simply holds while
        its variance grows.
        """
        if power_w is None:
            return 0.0
        if power_w >= 0.0:
            return -power_w * dt_s
        return -power_w * dt_s * self.config.energy.harvest_efficiency.value

    def process_noise(
        self,
        state: np.ndarray,
        dt_s: float,
        *,
        clock_uncertainty_s: float = 0.0,
        integration_gap_s: float = 0.0,
    ) -> np.ndarray:
        """Declared process noise ``Q`` for one step."""
        noise = np.zeros((STATE_DIM, STATE_DIM), dtype=np.float64)
        noise[:3, :3] = motion_process_noise(self.config.motion.process_jerk_psd.value, dt_s)
        speed = float(state[STATE_SPEED])
        acceleration = float(state[STATE_ACCELERATION])
        noise[STATE_PROGRESS, STATE_PROGRESS] += (abs(speed) * clock_uncertainty_s) ** 2
        noise[STATE_SPEED, STATE_SPEED] += (abs(acceleration) * clock_uncertainty_s) ** 2
        energy_sigma = self.config.energy.power_model_sigma_w.value * dt_s
        gap_sigma = self.config.energy.unobserved_gap_sigma_w.value * integration_gap_s
        noise[STATE_ENERGY, STATE_ENERGY] = energy_sigma**2 + gap_sigma**2
        return noise

    # -- correction -----------------------------------------------------

    def measurement_variance(
        self,
        channel: str,
        *,
        clock_uncertainty_s: float = 0.0,
    ) -> float:
        """Measurement variance ``R`` for one scalar channel, clock inflation included.

        A sample is timestamped by a clock we only know to ``sigma_c``. During
        ``sigma_c`` the quantity itself moved, so the effective measurement noise
        of progress grows by ``(v * sigma_c)^2`` and that of speed by
        ``(a * sigma_c)^2``. Clock uncertainty can only widen ``R``.
        """
        measurement = self.config.measurement
        mean = self.state.mean
        if channel == "speed_mps":
            base = measurement.speed_sigma_mps.value**2
            inflation = (abs(float(mean[STATE_ACCELERATION])) * clock_uncertainty_s) ** 2
        elif channel in ("progress_m", "lap_distance_m"):
            base = measurement.progress_sigma_m.value**2
            inflation = (abs(float(mean[STATE_SPEED])) * clock_uncertainty_s) ** 2
        elif channel == "acceleration_mps2":
            base = measurement.acceleration_sigma_mps2.value**2
            inflation = self.config.motion.process_jerk_psd.value * clock_uncertainty_s
        elif channel == "battery_energy_j":
            base = measurement.energy_sigma_j.value**2
            power = self.state.energy.last_power_w or 0.0
            inflation = (abs(power) * clock_uncertainty_s) ** 2
        else:  # pragma: no cover - guarded by the caller
            raise KeyError(f"channel {channel!r} is not fused by the own-car EKF")
        return base + inflation

    def _fuse_scalar(
        self,
        index: int,
        measurement: float,
        variance: float,
        *,
        family: str,
        observation: Observation,
    ) -> tuple[float, float]:
        """Joseph-form scalar update. Returns ``(residual, innovation_variance)``."""
        state = self.state
        h = np.zeros(STATE_DIM, dtype=np.float64)
        h[index] = 1.0
        predicted = float(state.mean[index])
        residual = measurement - predicted
        innovation_variance = float(state.covariance[index, index]) + variance
        if innovation_variance <= 0.0:  # pragma: no cover - defensive
            raise ValueError("innovation variance must be positive")
        gain = state.covariance @ h / innovation_variance
        state.mean = state.mean + gain * residual
        identity = np.eye(STATE_DIM, dtype=np.float64)
        spread = identity - np.outer(gain, h)
        covariance = spread @ state.covariance @ spread.T + np.outer(gain, gain) * variance
        state.covariance = 0.5 * (covariance + covariance.T)
        self._record_update(
            family=family,
            observation=observation,
            residual=residual,
            innovation_variance=innovation_variance,
            index=index,
        )
        return residual, innovation_variance

    def _record_update(
        self,
        *,
        family: str,
        observation: Observation,
        residual: float,
        innovation_variance: float,
        index: int,
    ) -> None:
        state = self.state
        normalised = residual * residual / innovation_variance
        smoothing = self.config.diagnostics.nis_smoothing.value
        previous = state.smoothed_nis.get(family)
        state.smoothed_nis[family] = (
            normalised if previous is None else (1.0 - smoothing) * previous + smoothing * normalised
        )
        state.update_counts[family] = state.update_counts.get(family, 0) + 1
        state.diagnostics[family] = FamilyDiagnostic(
            family=family,
            provenance=observation.provenance,
            quality=observation.quality,
            observed_at_s=observation.session_time_s,
            observation_age_s=max(0.0, state.time_s - observation.session_time_s),
            residual=residual,
            residual_normalised=math.sqrt(normalised),
            innovation_variance=innovation_variance,
            standard_deviation=math.sqrt(max(float(state.covariance[index, index]), 0.0)),
            source_id=observation.source_id,
            update_count=state.update_counts[family],
        )
        state.contributing_event_ids.append(observation.event_id)

    # -- observation intake ---------------------------------------------

    def ingest(self, observations: Sequence[Observation], context: EstimationContext) -> None:
        """Fuse a time-ordered batch of own-car observations up to the cutoff.

        The caller has already dropped everything after ``context.cutoff_s``;
        this method asserts that rather than re-filtering, so a future
        observation cannot slip in through a second path.
        """
        clock_sigma = context.effective_clock_uncertainty_s
        ordered = sorted(observations, key=lambda obs: (obs.session_time_s, obs.channel, obs.event_id))
        for observation in ordered:
            if observation.session_time_s > context.cutoff_s:  # pragma: no cover - defensive
                raise ValueError("an observation after the cutoff reached the filter")
            if not self.state.started:
                self._bootstrap(observation, context)
                continue
            self._advance_to(observation.session_time_s, clock_sigma)
            self._apply(observation, context, clock_sigma)
        if self.state.started:
            self._advance_to(context.cutoff_s, clock_sigma)
        self.apply_integration_gap(context.gap_for("electrical_power_w"))

    def apply_integration_gap(self, gap_s: float) -> None:
        """Widen energy uncertainty by an interval the power channel never observed.

        ``gap_s`` is ``IntegrationGapRecord.cumulative_gap_s`` from
        :mod:`afterlap_core.data.quality`. It is applied once per batch rather
        than folded into each prediction step, so re-running the same batch with
        the same gap gives the same widening.
        """
        if gap_s <= 0.0:
            return
        sigma = self.config.energy.unobserved_gap_sigma_w.value * gap_s
        variance = sigma * sigma
        self.state.covariance[STATE_ENERGY, STATE_ENERGY] += variance
        self.state.energy.delta_variance += variance
        self.state.energy.unobserved_seconds = gap_s

    def _advance_to(self, target_time_s: float, clock_sigma: float) -> None:
        if target_time_s <= self.state.time_s:
            return
        self.predict_to(
            target_time_s,
            clock_uncertainty_s=clock_sigma,
            power_w=self.state.energy.last_power_w,
        )

    def _bootstrap(self, observation: Observation, context: EstimationContext) -> None:
        """Seed the filter from the first usable motion observation."""
        state = self.state
        state.time_s = observation.session_time_s
        if observation.channel == "speed_mps" and observation.usable:
            state.mean[STATE_SPEED] = float(observation.value or 0.0)
            state.started = True
        elif observation.channel in ("progress_m", "lap_distance_m") and observation.usable:
            state.mean[STATE_PROGRESS] = float(observation.value or 0.0)
            state.started = True
        else:
            self._apply(observation, context, context.effective_clock_uncertainty_s)
            return
        state.completed_laps, _ = laps_and_s(float(state.mean[STATE_PROGRESS]), context.track_length_m)
        state.contributing_event_ids.append(observation.event_id)
        state.diagnostics[observation.channel] = FamilyDiagnostic(
            family=observation.channel,
            provenance=observation.provenance,
            quality=observation.quality,
            observed_at_s=observation.session_time_s,
            observation_age_s=0.0,
            standard_deviation=math.sqrt(float(state.covariance[STATE_SPEED, STATE_SPEED])),
            source_id=observation.source_id,
            update_count=1,
            note="filter bootstrap; no residual is defined for the first sample",
        )
        state.update_counts[observation.channel] = 1

    def _apply(self, observation: Observation, context: EstimationContext, clock_sigma: float) -> None:
        channel = observation.channel
        if not observation.usable:
            self._record_unusable(observation)
            return
        value = float(observation.value or 0.0)
        if channel == "speed_mps":
            self._fuse_scalar(
                STATE_SPEED,
                value,
                self.measurement_variance("speed_mps", clock_uncertainty_s=clock_sigma),
                family="speed_mps",
                observation=observation,
            )
        elif channel == "progress_m":
            self._fuse_scalar(
                STATE_PROGRESS,
                value,
                self.measurement_variance("progress_m", clock_uncertainty_s=clock_sigma),
                family="progress_m",
                observation=observation,
            )
            self.state.completed_laps, _ = laps_and_s(
                float(self.state.mean[STATE_PROGRESS]), context.track_length_m
            )
        elif channel == "lap_distance_m":
            unwrapped = self._unwrap(value, context.track_length_m)
            self._fuse_scalar(
                STATE_PROGRESS,
                unwrapped,
                self.measurement_variance("lap_distance_m", clock_uncertainty_s=clock_sigma),
                family="lap_distance_m",
                observation=observation,
            )
            self.state.completed_laps, _ = laps_and_s(
                float(self.state.mean[STATE_PROGRESS]), context.track_length_m
            )
        elif channel == "acceleration_mps2":
            self._fuse_scalar(
                STATE_ACCELERATION,
                value,
                self.measurement_variance("acceleration_mps2", clock_uncertainty_s=clock_sigma),
                family="acceleration_mps2",
                observation=observation,
            )
        elif channel == "battery_energy_j":
            self._apply_energy(observation, context, clock_sigma, value)
        elif channel == "electrical_power_w":
            ledger = self.state.energy
            ledger.last_power_w = value
            ledger.last_power_at_s = observation.session_time_s
            self._record_channel(observation, value)
        elif channel in ("battery_temperature_k", "recharge_ledger_j"):
            self._record_channel(observation, value)

    def _apply_energy(
        self,
        observation: Observation,
        context: EstimationContext,
        clock_sigma: float,
        value: float,
    ) -> None:
        """Correct or initialise battery energy from a battery-state measurement.

        Refused unless the source declares ``battery_energy_j`` measured. A
        channel that is merely *supported* -- modelled, defaulted or inferred --
        cannot open energy capability, because the capability claim would then be
        about the model rather than about the car.
        """
        state = self.state
        if not context.channel_is_measured("battery_energy_j"):
            state.notes.append(
                "battery_energy_j samples arrived on a channel the source does not declare measured; "
                "energy capability stays closed"
            )
            self._record_unusable(observation, reason="channel not declared measured")
            return
        window_min = self.config.energy.physical_min_j.value
        window_max = self.config.energy.physical_max_j.value
        if not (window_min <= value <= window_max):
            state.notes.append(
                f"battery_energy_j sample {value:.1f} J is outside the declared physical window"
            )
            self._record_unusable(observation, reason="outside the declared physical window")
            return
        ledger = state.energy
        if not ledger.initialised:
            state.mean[STATE_ENERGY] = value
            state.covariance[STATE_ENERGY, STATE_ENERGY] = self.config.measurement.energy_sigma_j.value**2
            ledger.initialised = True
            ledger.initialised_at_s = observation.session_time_s
            ledger.initial_source = observation.source_id or observation.provenance.value
            ledger.delta_j = 0.0
            ledger.delta_variance = 0.0
            state.contributing_event_ids.append(observation.event_id)
            state.update_counts["battery_energy_j"] = state.update_counts.get("battery_energy_j", 0) + 1
            state.diagnostics["battery_energy_j"] = FamilyDiagnostic(
                family="battery_energy_j",
                provenance=observation.provenance,
                quality=observation.quality,
                observed_at_s=observation.session_time_s,
                observation_age_s=0.0,
                standard_deviation=self.config.measurement.energy_sigma_j.value,
                source_id=observation.source_id,
                update_count=state.update_counts["battery_energy_j"],
                note=f"absolute energy initialised from {ledger.initial_source}",
            )
            return
        self._fuse_scalar(
            STATE_ENERGY,
            value,
            self.measurement_variance("battery_energy_j", clock_uncertainty_s=clock_sigma),
            family="battery_energy_j",
            observation=observation,
        )
        ledger.corrections += 1
        ledger.last_correction_at_s = observation.session_time_s

    def _record_channel(self, observation: Observation, value: float) -> None:
        self.state.channels[observation.channel] = ChannelSample(
            value=value,
            session_time_s=observation.session_time_s,
            provenance=observation.provenance,
            quality=observation.quality,
            source_id=observation.source_id,
            event_id=observation.event_id,
        )
        self.state.contributing_event_ids.append(observation.event_id)
        self.state.update_counts[observation.channel] = (
            self.state.update_counts.get(observation.channel, 0) + 1
        )
        self.state.diagnostics[observation.channel] = FamilyDiagnostic(
            family=observation.channel,
            provenance=observation.provenance,
            quality=observation.quality,
            observed_at_s=observation.session_time_s,
            observation_age_s=max(0.0, self.state.time_s - observation.session_time_s),
            source_id=observation.source_id,
            update_count=self.state.update_counts[observation.channel],
            note="carried through unfiltered; not part of the EKF state",
        )

    def _record_unusable(self, observation: Observation, *, reason: str | None = None) -> None:
        self.state.diagnostics[observation.channel] = FamilyDiagnostic(
            family=observation.channel,
            provenance=observation.provenance,
            quality=observation.quality,
            observed_at_s=observation.session_time_s,
            observation_age_s=max(0.0, self.state.time_s - observation.session_time_s),
            source_id=observation.source_id,
            update_count=self.state.update_counts.get(observation.channel, 0),
            note=reason or f"sample rejected with quality={observation.quality.value}",
        )

    def _unwrap(self, lap_distance_m: float, track_length_m: float) -> float:
        """Map a wrapped lap coordinate onto the unwrapped progress axis."""
        wrapped = wrap_s(lap_distance_m, track_length_m)
        base = self.state.completed_laps * track_length_m
        candidates = (base + wrapped - track_length_m, base + wrapped, base + wrapped + track_length_m)
        current = float(self.state.mean[STATE_PROGRESS])
        return min(candidates, key=lambda candidate: abs(candidate - current))

    # -- reporting -------------------------------------------------------

    @property
    def residual_alarm(self) -> bool:
        threshold = self.config.diagnostics.nis_alarm_threshold.value
        return any(value > threshold for value in self.state.smoothed_nis.values())

    def standard_deviation(self, index: int) -> float:
        return math.sqrt(max(float(self.state.covariance[index, index]), 0.0))

    def snapshot(self) -> dict[str, Any]:
        state = self.state
        return {
            "mean": state.mean.tolist(),
            "covariance": state.covariance.tolist(),
            "time_s": state.time_s,
            "started": state.started,
            "energy": asdict(state.energy),
            "completed_laps": state.completed_laps,
            "channels": {name: _channel_sample_payload(sample) for name, sample in state.channels.items()},
            "smoothed_nis": dict(state.smoothed_nis),
            "update_counts": dict(state.update_counts),
            "contributing_event_ids": list(state.contributing_event_ids),
            "notes": list(state.notes),
            "diagnostics": {name: _diagnostic_payload(diag) for name, diag in state.diagnostics.items()},
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.state = OwnCarFilterState(
            mean=np.array(snapshot["mean"], dtype=np.float64),
            covariance=np.array(snapshot["covariance"], dtype=np.float64),
            time_s=float(snapshot["time_s"]),
            started=bool(snapshot["started"]),
            energy=EnergyLedger(**snapshot["energy"]),
            completed_laps=int(snapshot["completed_laps"]),
            channels={name: _channel_sample_from(payload) for name, payload in snapshot["channels"].items()},
            diagnostics={
                name: _diagnostic_from(payload) for name, payload in snapshot["diagnostics"].items()
            },
            smoothed_nis=dict(snapshot["smoothed_nis"]),
            update_counts=dict(snapshot["update_counts"]),
            contributing_event_ids=list(snapshot["contributing_event_ids"]),
            notes=list(snapshot["notes"]),
        )


def _channel_sample_payload(sample: ChannelSample) -> dict[str, Any]:
    payload = asdict(sample)
    payload["provenance"] = sample.provenance.value
    payload["quality"] = sample.quality.value
    return payload


def _channel_sample_from(payload: dict[str, Any]) -> ChannelSample:
    fields = dict(payload)
    fields["provenance"] = Provenance(fields["provenance"])
    fields["quality"] = Quality(fields["quality"])
    return ChannelSample(**fields)


def _diagnostic_payload(diagnostic: FamilyDiagnostic) -> dict[str, Any]:
    payload = asdict(diagnostic)
    payload["provenance"] = diagnostic.provenance.value
    payload["quality"] = diagnostic.quality.value
    return payload


def _diagnostic_from(payload: dict[str, Any]) -> FamilyDiagnostic:
    fields = dict(payload)
    fields["provenance"] = Provenance(fields["provenance"])
    fields["quality"] = Quality(fields["quality"])
    return FamilyDiagnostic(**fields)


def _scalar(
    value: float | None,
    unit: str,
    *,
    provenance: Provenance,
    quality: Quality,
    observed_at_s: float | None,
    now_s: float,
    standard_deviation: float | None = None,
    source_id: str | None = None,
) -> ScalarValue:
    age = None if observed_at_s is None else max(0.0, now_s - observed_at_s)
    if value is None:
        return ScalarValue(
            value=None,
            unit=unit,
            provenance=provenance,
            quality=Quality.MISSING if quality is Quality.VALID else quality,
            observed_at_s=observed_at_s,
            age_s=age,
            source_id=source_id,
        )
    # A value that exists but is far past its cadence is stale, not missing:
    # ``missing`` is reserved for "there is no number", and the contract enforces
    # that. Reporting the number with quality=stale is the honest description.
    reported = Quality.STALE if quality is Quality.MISSING else quality
    return ScalarValue(
        value=value,
        unit=unit,
        provenance=provenance,
        quality=reported,
        observed_at_s=observed_at_s,
        age_s=age,
        standard_deviation=standard_deviation,
        source_id=source_id,
    )


def _channel_quality(
    diagnostic: FamilyDiagnostic | None,
    context: EstimationContext,
    channel: str,
    now_s: float,
) -> Quality:
    if diagnostic is None or diagnostic.observed_at_s is None:
        return Quality.MISSING
    if diagnostic.quality in (Quality.MISSING, Quality.INVALID):
        return diagnostic.quality
    age = max(0.0, now_s - diagnostic.observed_at_s)
    return classify_freshness(age, context.expected_period_for(channel))


def build_own_car_estimate(
    filter_: OwnCarFilter,
    context: EstimationContext,
    *,
    at_time_s: float | None = None,
) -> tuple[OwnCarEstimate, bool]:
    """Render the filter posterior as the frozen ``OwnCarEstimate`` contract.

    Returns ``(estimate, own_energy_capability)``. Capability is False whenever
    absolute battery energy was never initialised from a measured channel: the
    estimate then carries an explicitly missing ``ScalarValue`` and a
    ``physical_bounds`` interval, and no consumer can mistake the pair for a
    precise number.
    """
    state = filter_.state
    now_s = context.cutoff_s if at_time_s is None else at_time_s
    diagnostics = state.diagnostics

    progress_value = float(state.mean[STATE_PROGRESS])
    speed_value = float(state.mean[STATE_SPEED])
    acceleration_value = float(state.mean[STATE_ACCELERATION])
    laps, lap_distance = laps_and_s(progress_value, context.track_length_m)

    motion_known = state.started
    motion_quality = Quality.VALID if motion_known else Quality.MISSING
    progress_diag = diagnostics.get("progress_m") or diagnostics.get("lap_distance_m")
    speed_diag = diagnostics.get("speed_mps")
    if motion_known:
        motion_quality = _channel_quality(progress_diag or speed_diag, context, "progress_m", now_s)
        if motion_quality is Quality.MISSING:
            motion_quality = Quality.STALE

    progress = _scalar(
        progress_value if motion_known else None,
        "m",
        provenance=Provenance.ESTIMATED,
        quality=motion_quality,
        observed_at_s=progress_diag.observed_at_s if progress_diag else None,
        now_s=now_s,
        standard_deviation=filter_.standard_deviation(STATE_PROGRESS),
    )
    lap_distance_value = _scalar(
        lap_distance if motion_known else None,
        "m",
        provenance=Provenance.ESTIMATED,
        quality=motion_quality,
        observed_at_s=progress_diag.observed_at_s if progress_diag else None,
        now_s=now_s,
        standard_deviation=filter_.standard_deviation(STATE_PROGRESS),
    )
    speed_quality = motion_quality
    if motion_known and speed_value < 0.0:
        speed_quality = Quality.DEGRADED
    speed = _scalar(
        max(0.0, speed_value) if motion_known else None,
        "m/s",
        provenance=Provenance.ESTIMATED,
        quality=speed_quality,
        observed_at_s=speed_diag.observed_at_s if speed_diag else None,
        now_s=now_s,
        standard_deviation=filter_.standard_deviation(STATE_SPEED),
    )
    acceleration = _scalar(
        acceleration_value if motion_known else None,
        "m/s^2",
        provenance=Provenance.ESTIMATED,
        quality=motion_quality,
        observed_at_s=speed_diag.observed_at_s if speed_diag else None,
        now_s=now_s,
        standard_deviation=filter_.standard_deviation(STATE_ACCELERATION),
    )

    energy, energy_interval, capability = _energy_view(filter_, context, now_s)

    temperature_sample = state.channels.get("battery_temperature_k")
    temperature = _scalar(
        temperature_sample.value if temperature_sample else None,
        "K",
        provenance=temperature_sample.provenance if temperature_sample else Provenance.MEASURED,
        quality=_channel_quality(
            diagnostics.get("battery_temperature_k"), context, "battery_temperature_k", now_s
        ),
        observed_at_s=temperature_sample.session_time_s if temperature_sample else None,
        now_s=now_s,
        standard_deviation=(
            filter_.config.measurement.temperature_sigma_k.value if temperature_sample else None
        ),
        source_id=temperature_sample.source_id if temperature_sample else None,
    )
    power_sample = state.channels.get("electrical_power_w")
    power = _scalar(
        power_sample.value if power_sample else None,
        "W",
        provenance=power_sample.provenance if power_sample else Provenance.MEASURED,
        quality=_channel_quality(diagnostics.get("electrical_power_w"), context, "electrical_power_w", now_s),
        observed_at_s=power_sample.session_time_s if power_sample else None,
        now_s=now_s,
        standard_deviation=(filter_.config.energy.power_model_sigma_w.value if power_sample else None),
        source_id=power_sample.source_id if power_sample else None,
    )
    ledger_sample = state.channels.get("recharge_ledger_j")
    recharge = _scalar(
        ledger_sample.value if ledger_sample else None,
        "J",
        provenance=ledger_sample.provenance if ledger_sample else Provenance.MEASURED,
        quality=_channel_quality(diagnostics.get("recharge_ledger_j"), context, "recharge_ledger_j", now_s),
        observed_at_s=ledger_sample.session_time_s if ledger_sample else None,
        now_s=now_s,
        source_id=ledger_sample.source_id if ledger_sample else None,
    )

    estimate = OwnCarEstimate(
        car_id=context.car_id,
        progress_m=progress,
        lap_distance_m=lap_distance_value,
        completed_laps=max(0, laps),
        speed_mps=speed,
        acceleration_mps2=acceleration,
        battery_energy_j=energy,
        battery_energy_interval=energy_interval,
        battery_temperature_k=temperature,
        electrical_power_w=power,
        recharge_spent_this_lap_j=recharge,
    )
    return estimate, capability


def _energy_view(
    filter_: OwnCarFilter,
    context: EstimationContext,
    now_s: float,
) -> tuple[ScalarValue, IntervalValue | None, bool]:
    """Energy scalar, interval and capability flag.

    Three honest outcomes, and no fourth:

    * initialised -- a point value with its standard deviation, capability open;
    * partial (measured power integrated from an unknown start) -- a missing
      scalar plus a narrowed ``physical_bounds`` interval, capability closed;
    * nothing at all -- a missing scalar plus the full physical window,
      capability closed.
    """
    state = filter_.state
    ledger = state.energy
    window_min = filter_.config.energy.physical_min_j.value
    window_max = filter_.config.energy.physical_max_j.value
    diagnostic = state.diagnostics.get("battery_energy_j")

    if ledger.initialised and math.isfinite(float(state.mean[STATE_ENERGY])):
        observed_at = ledger.last_correction_at_s or ledger.initialised_at_s
        quality = _channel_quality(diagnostic, context, "battery_energy_j", now_s)
        if quality is Quality.MISSING:
            quality = Quality.STALE
        energy = _scalar(
            float(np.clip(state.mean[STATE_ENERGY], window_min, window_max)),
            "J",
            provenance=Provenance.ESTIMATED,
            quality=quality,
            observed_at_s=observed_at,
            now_s=now_s,
            standard_deviation=filter_.standard_deviation(STATE_ENERGY),
            source_id=ledger.initial_source,
        )
        return energy, None, True

    lower, upper = ledger.reachable_interval(window_min, window_max)
    partial = ledger.integrated_seconds > 0.0
    reason = (
        "absolute battery energy was never initialised from a measured channel; "
        "integrated power gives a reachable set only"
        if partial
        else "no battery-energy channel is measured by this source"
    )
    energy = ScalarValue(
        value=None,
        unit="J",
        provenance=Provenance.ESTIMATED if partial else Provenance.MEASURED,
        quality=Quality.MISSING,
        observed_at_s=None,
        source_id=None,
    )
    interval = IntervalValue(
        lower=lower,
        upper=upper,
        unit="J",
        kind="physical_bounds",
        provenance=Provenance.ESTIMATED if partial else Provenance.CONFIGURED,
        quality=Quality.DEGRADED,
        observed_at_s=ledger.last_power_at_s,
        age_s=(None if ledger.last_power_at_s is None else max(0.0, now_s - ledger.last_power_at_s)),
    )
    if reason not in state.notes:
        state.notes.append(reason)
    return energy, interval, False


def own_car_channel_families(observations: Iterable[Observation]) -> tuple[str, ...]:
    """Channel names in a batch that the own-car filter can consume."""
    return tuple(sorted({obs.channel for obs in observations if obs.channel in OWN_CAR_CHANNELS}))


__all__ = [
    "REACHABLE_SET_SIGMAS",
    "STATE_ACCELERATION",
    "STATE_DIM",
    "STATE_ENERGY",
    "STATE_NAMES",
    "STATE_PROGRESS",
    "STATE_SPEED",
    "ChannelSample",
    "EnergyLedger",
    "MotionModel",
    "OwnCarFilter",
    "OwnCarFilterState",
    "build_own_car_estimate",
    "motion_process_noise",
    "own_car_channel_families",
]
