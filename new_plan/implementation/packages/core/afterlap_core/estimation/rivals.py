"""128-particle belief filter over one rival's hidden energy, pace and intention.

What a particle is
------------------

Each particle carries:

* ``energy_j`` -- a hypothesis about the rival's stored battery energy, clipped
  to the legal window and never labelled measured;
* ``pace_bias_mps`` -- an Ornstein-Uhlenbeck pace offset absorbing tyre, aero and
  engine ambiguity, because a fast rival is not necessarily a deploying rival;
* ``mode`` -- a sampled behaviour mode, one of ``conserve``, ``normal``,
  ``attack``, ``defend``, following a persistent Markov path;
* ``mode_belief`` and ``mode_age_s`` -- the mode-memory state: the particle's
  analytic posterior over the four modes, and how long its sampled mode has been
  held.

Why the mode is both sampled and believed
-----------------------------------------

The sampled ``mode`` drives the *nonlinear* part of the model -- how much energy
that particle spends -- so it must be a real, persistent path, not an independent
draw each tick.

The **reported** intention posterior, however, comes from ``mode_belief``, which
is propagated and corrected analytically. That matters, and it is not a cosmetic
choice. Counting sampled modes makes the mode marginal a Monte Carlo estimate,
and between two modes whose likelihoods are *identical* -- which ``attack`` and
``defend`` are by construction at zero pressure -- there is no restoring force,
so that estimate random-walks and one mode is eventually absorbed. With 128
particles that happens within about a minute of observations, and the filter then
reports a confident intention it has no evidence for. Marginalising the mode
analytically removes that failure entirely: two observationally identical modes
stay observationally identical in the report, at any seed.

The cost is an explicit approximation: each particle's *energy* trajectory is
conditioned on its sampled mode path while its *weight* marginalises over modes.
That is the standard trade in a mixture particle filter, and it is recorded here
rather than hidden.

Observation model
-----------------

The filter never sees a rival's internal state. It sees the gap and, when the
source supplies it, the rival's speed. For a particle ``i`` the predicted pace
offset relative to our own car is::

    offset_i = pace_bias_i + deploy_i * (base_gain[mode_i] + pressure * pressure_gain[mode_i])
    deploy_i = clip(energy_i / deploy_reference_energy_j, 0, 1)

``deploy_i`` **saturates**. A rival with 2 MJ and a rival with 3.5 MJ produce the
identical pace signature, so watching a rival accelerate identifies "not nearly
empty" and nothing more. That saturation is deliberate: it is what stops the
energy posterior from collapsing on an acceleration observation.

``attack`` and ``defend`` also carry near-identical signatures by design (see
``behaviour.ambiguity_note`` in the manifest). Two behaviours that produce the
same observations must stay ambiguous.

Likelihood variance always includes three terms: the observation noise, the
*own-state* variance from the own-car EKF, and a configured model residual
variance. Ignoring either of the last two would make the filter confident about
a rival on the strength of a model it has no right to trust that far. A
dropout adds ``dropout_variance_growth_per_s`` per second of lost observation.

Weights, resampling and the support floor
-----------------------------------------

Weights live in log space and are normalised with log-sum-exp. Systematic
resampling fires when the effective sample size falls below
``ess_resample_fraction * N``. After resampling, bounded roughening is applied
and two floors are enforced:

* ``mode_weight_floor`` -- a little uniform mass is mixed into every particle's
  mode belief, so each mode always retains at least that much of the reported
  posterior. A mode cannot be driven to zero and become unrecoverable;
* ``min_particles_per_mode`` -- at least that many particles carry each sampled
  mode, so no mode silently disappears from the scenarios a planner rolls out.

Together those mean a mode that is contradicted for a long stretch still
recovers when the evidence reverses.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from afterlap_contracts import (
    IntentionWeights,
    IntervalValue,
    Provenance,
    Quality,
    RivalBelief,
    RivalIntention,
    ScalarValue,
)
from afterlap_core.rng import StreamRegistry, derive_seed

from .config import MODE_INDEX, MODE_ORDER, RivalConfig

#: Named RNG streams. Separate names mean adding a draw in one place cannot
#: shift the sequence another place sees.
STREAM_INIT = "rival_init"
STREAM_MODE = "rival_mode"
STREAM_PROCESS = "rival_process"
STREAM_RESAMPLE = "rival_resample"
STREAM_SCENARIO = "rival_scenario"
STREAM_NAMES: tuple[str, ...] = (
    STREAM_INIT,
    STREAM_MODE,
    STREAM_PROCESS,
    STREAM_RESAMPLE,
    STREAM_SCENARIO,
)

#: Bound, in sigmas, on a single step of rival energy process noise.
PROCESS_NOISE_CLIP_SIGMAS = 3.0


@dataclass(frozen=True, slots=True)
class RivalObservation:
    """One permitted look at a rival. Never a read of its internal state."""

    session_time_s: float
    gap_m: float | None = None
    gap_s: float | None = None
    rival_speed_mps: float | None = None
    gap_sigma_m: float | None = None
    event_ids: tuple[str, ...] = ()
    quality: Quality = Quality.VALID

    def __post_init__(self) -> None:
        if self.session_time_s < 0.0:
            raise ValueError("observation time cannot be negative")


@dataclass(frozen=True, slots=True)
class OwnStateSummary:
    """What the rival filter is allowed to know about our own car.

    The variances matter as much as the means: they enter every likelihood, so a
    poorly observed own car makes rival beliefs wider rather than falsely sharp.
    """

    speed_mps: float
    speed_variance: float = 0.0
    acceleration_mps2: float = 0.0
    progress_m: float = 0.0
    progress_variance: float = 0.0

    def __post_init__(self) -> None:
        if self.speed_variance < 0.0 or self.progress_variance < 0.0:
            raise ValueError("own-state variances cannot be negative")


@dataclass(frozen=True, slots=True)
class RivalContext:
    """Contextual conditioning shared by propagation and likelihood."""

    is_ahead: bool = True
    pressure: float = 0.0
    dropout_s: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.pressure <= 1.0:
            raise ValueError("pressure must lie in [0, 1]")
        if self.dropout_s < 0.0:
            raise ValueError("dropout cannot be negative")


@dataclass(slots=True)
class ParticleSet:
    """The particle arrays. All float64; ``mode`` is an index into MODE_ORDER."""

    energy_j: np.ndarray
    pace_bias_mps: np.ndarray
    mode: np.ndarray
    mode_age_s: np.ndarray
    mode_belief: np.ndarray
    log_weight: np.ndarray

    @property
    def size(self) -> int:
        return int(self.energy_j.shape[0])

    def copy(self) -> ParticleSet:
        return ParticleSet(
            energy_j=self.energy_j.copy(),
            pace_bias_mps=self.pace_bias_mps.copy(),
            mode=self.mode.copy(),
            mode_age_s=self.mode_age_s.copy(),
            mode_belief=self.mode_belief.copy(),
            log_weight=self.log_weight.copy(),
        )

    def weights(self) -> np.ndarray:
        return normalise_log_weights(self.log_weight)


def normalise_log_weights(log_weight: np.ndarray) -> np.ndarray:
    """Stable log-sum-exp normalisation into linear weights."""
    finite = np.isfinite(log_weight)
    if not finite.any():  # pragma: no cover - defensive
        return np.full(log_weight.shape, 1.0 / log_weight.size, dtype=np.float64)
    shifted = np.where(finite, log_weight, -np.inf)
    peak = float(np.max(shifted))
    exponentiated = np.exp(shifted - peak)
    total = float(np.sum(exponentiated))
    if total <= 0.0:  # pragma: no cover - defensive
        return np.full(log_weight.shape, 1.0 / log_weight.size, dtype=np.float64)
    return exponentiated / total


def effective_sample_size(weights: np.ndarray) -> float:
    """``1 / sum(w^2)`` for normalised weights."""
    total = float(np.sum(weights * weights))
    if total <= 0.0:  # pragma: no cover - defensive
        return 0.0
    return 1.0 / total


def systematic_resample(weights: np.ndarray, uniform: float, *, count: int | None = None) -> np.ndarray:
    """Systematic (low-variance) resampling indices from a single uniform draw.

    ``count`` defaults to ``len(weights)``. Drawing a different number of samples
    is what lets the mode-stratified resampler give each mode its own share of
    the particle budget without biasing which particles inside that mode survive.
    """
    draws = weights.shape[0] if count is None else count
    if draws <= 0:  # pragma: no cover - defensive
        return np.zeros(0, dtype=np.int64)
    positions = (np.arange(draws, dtype=np.float64) + uniform) / draws
    cumulative = np.cumsum(weights)
    cumulative[-1] = 1.0
    return np.searchsorted(cumulative, positions, side="left").astype(np.int64)


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantiles: Sequence[float]) -> list[float]:
    """Weighted quantiles by linear interpolation of the weighted CDF."""
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    sorted_weights = weights[order]
    total = float(np.sum(sorted_weights))
    if total <= 0.0:  # pragma: no cover - defensive
        return [float(sorted_values[0]) for _ in quantiles]
    cumulative = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total
    return [float(np.interp(q, cumulative, sorted_values)) for q in quantiles]


@dataclass(slots=True)
class RivalFilterDiagnostics:
    """Per-update record of what the filter did and why."""

    updates: int = 0
    resamples: int = 0
    last_ess: float = 0.0
    last_resampled: bool = False
    mode_floor_applications: int = 0
    support_reseeds: int = 0
    last_observation_s: float | None = None
    last_log_likelihood_spread: float = 0.0
    notes: list[str] = field(default_factory=list)


class RivalParticleFilter:
    """Belief over one rival, built only from permitted observations."""

    def __init__(
        self,
        config: RivalConfig,
        *,
        car_id: str,
        seed: int,
        time_s: float = 0.0,
    ) -> None:
        if not (config.is_hand_authored or config.transition_matrix_authorship == "estimated_from_synthetic"):
            raise ValueError("the mode transition matrix must declare its authorship")  # pragma: no cover
        self.config = config
        self.car_id = car_id
        self.seed = seed
        self.streams = StreamRegistry(derive_seed(seed, car_id), STREAM_NAMES)
        self.time_s = time_s
        self.diagnostics = RivalFilterDiagnostics()
        self.observation_history: list[RivalObservation] = []
        self.particles = self._sample_prior()
        self._last_gap_m: float | None = None
        self._last_gap_time_s: float | None = None

    # -- initialisation --------------------------------------------------

    def _sample_prior(self) -> ParticleSet:
        """Broad plausible prior. Uniform energy, zero-mean pace, uniform modes.

        The energy prior is uniform over the *plausible* sub-range declared in
        the manifest rather than over the whole physical window: a car sitting at
        the very edge of its window at an arbitrary mid-race instant is
        implausible. Nothing narrower is justified, because nothing observable
        pins a rival's battery down at initialisation.
        """
        rng = self.streams.stream(STREAM_INIT)
        count = self.config.filter.n_particles
        dynamics = self.config.dynamics
        energy = rng.uniform(dynamics.prior_energy_min_j.value, dynamics.prior_energy_max_j.value, size=count)
        pace = rng.normal(0.0, dynamics.pace_bias_sigma_mps.value, size=count)
        mode = np.tile(np.arange(len(MODE_ORDER), dtype=np.int64), count // len(MODE_ORDER) + 1)[:count]
        mode = rng.permutation(mode)
        age = np.zeros(count, dtype=np.float64)
        belief = np.full((count, len(MODE_ORDER)), 1.0 / len(MODE_ORDER), dtype=np.float64)
        log_weight = np.full(count, -math.log(count), dtype=np.float64)
        return ParticleSet(
            energy_j=energy.astype(np.float64),
            pace_bias_mps=pace.astype(np.float64),
            mode=mode.astype(np.int64),
            mode_age_s=age,
            mode_belief=belief,
            log_weight=log_weight,
        )

    # -- model -----------------------------------------------------------

    def deploy_fraction(self, energy_j: np.ndarray) -> np.ndarray:
        """Saturating deployment capability. See the module docstring."""
        reference = self.config.dynamics.deploy_reference_energy_j.value
        return np.clip(energy_j / reference, 0.0, 1.0)

    def speed_offset(self, particles: ParticleSet, context: RivalContext) -> np.ndarray:
        """Predicted pace of each particle relative to our own car, in m/s."""
        behaviour = self.config.behaviour
        base = behaviour.base_speed_gain_mps.as_array()[particles.mode]
        pressure = behaviour.pressure_speed_gain_mps.as_array()[particles.mode]
        gain = base + context.pressure * pressure
        return particles.pace_bias_mps + self.deploy_fraction(particles.energy_j) * gain

    def mode_power_w(self, particles: ParticleSet, context: RivalContext) -> np.ndarray:
        """Signed DC-bus power each particle's mode implies. Positive deploys."""
        behaviour = self.config.behaviour
        base = behaviour.base_power_w.as_array()[particles.mode]
        pressure = behaviour.pressure_power_w.as_array()[particles.mode]
        gain = base + context.pressure * pressure
        return self.deploy_fraction(particles.energy_j) * gain

    # -- propagation -----------------------------------------------------

    def propagate(self, dt_s: float, context: RivalContext) -> None:
        """Advance every particle by ``dt_s`` through the simplified rival model."""
        if dt_s < 0.0:
            raise ValueError("the rival filter never runs backwards")
        if dt_s == 0.0:
            return
        particles = self.particles
        matrix = self.config.step_transition(dt_s)
        # The analytic per-particle mode belief is predicted forward exactly.
        particles.mode_belief = self._floor_belief(particles.mode_belief @ matrix)
        # Age first, then transition: a particle that changes mode at this step
        # boundary has held its new mode for zero seconds, not for dt.
        particles.mode_age_s = particles.mode_age_s + dt_s
        self._sample_mode_path(matrix, likelihood=None)

        power = self.mode_power_w(particles, context)
        dynamics = self.config.dynamics
        rng = self.streams.stream(STREAM_PROCESS)
        count = particles.size

        noise_sigma = dynamics.energy_process_sigma_w.value * dt_s
        noise = np.clip(
            rng.normal(0.0, noise_sigma, size=count),
            -PROCESS_NOISE_CLIP_SIGMAS * noise_sigma,
            PROCESS_NOISE_CLIP_SIGMAS * noise_sigma,
        )
        particles.energy_j = np.clip(
            particles.energy_j - power * dt_s + noise,
            dynamics.energy_min_j.value,
            dynamics.energy_max_j.value,
        )

        tau = dynamics.pace_bias_time_constant_s.value
        decay = math.exp(-dt_s / tau)
        stationary = dynamics.pace_bias_process_sigma_mps.value
        pace_sigma = stationary * math.sqrt(max(1.0 - decay * decay, 0.0))
        pace_noise = np.clip(
            rng.normal(0.0, pace_sigma, size=count) if pace_sigma > 0.0 else np.zeros(count),
            -PROCESS_NOISE_CLIP_SIGMAS * max(pace_sigma, 1e-12),
            PROCESS_NOISE_CLIP_SIGMAS * max(pace_sigma, 1e-12),
        )
        particles.pace_bias_mps = particles.pace_bias_mps * decay + pace_noise
        self.time_s += dt_s

    def _floor_belief(self, belief: np.ndarray) -> np.ndarray:
        """Mix a little uniform mass into every per-particle mode belief.

        ``mode_weight_floor`` is implemented here, at the belief level, rather
        than as a post-hoc clamp on the aggregate. Mixing ``eps`` of uniform mass
        into each particle guarantees every mode keeps at least
        ``mode_weight_floor`` of the reported posterior and -- unlike a clamp --
        keeps the belief a proper distribution, so a contradicted mode recovers
        the instant the evidence reverses instead of being unrecoverable.
        """
        floor = self.config.filter.mode_weight_floor.value
        modes = len(MODE_ORDER)
        total = belief.sum(axis=1, keepdims=True)
        normalised = np.divide(belief, np.where(total > 0.0, total, 1.0))
        if floor <= 0.0:
            return normalised
        epsilon = min(1.0, floor * modes)
        return (1.0 - epsilon) * normalised + epsilon / modes

    def _sample_mode_path(self, matrix: np.ndarray, likelihood: np.ndarray | None) -> None:
        """Draw each particle's next discrete mode along a Markov path.

        The sampled mode drives the *nonlinear* part of the model -- how much
        energy the particle spends -- so it has to be a real, persistent path
        rather than an independent draw from a marginal. When a likelihood is
        supplied the draw is conditioned on it, which keeps the sampled path
        consistent with what was just observed.

        The reported intention posterior does **not** come from these samples; it
        comes from :attr:`ParticleSet.mode_belief`. See :meth:`intention_weights`.
        """
        particles = self.particles
        rows = matrix[particles.mode]
        if likelihood is not None:
            rows = rows * likelihood
        totals = rows.sum(axis=1, keepdims=True)
        safe = np.where(totals > 0.0, totals, 1.0)
        rows = np.where(totals > 0.0, rows / safe, 1.0 / len(MODE_ORDER))
        rng = self.streams.stream(STREAM_MODE)
        draws = rng.random(particles.size)
        cumulative = np.cumsum(rows, axis=1)
        new_mode = np.clip((draws[:, None] > cumulative).sum(axis=1).astype(np.int64), 0, len(MODE_ORDER) - 1)
        changed = new_mode != particles.mode
        particles.mode = new_mode
        particles.mode_age_s = np.where(changed, 0.0, particles.mode_age_s)
        self._enforce_mode_support()

    def _enforce_mode_support(self) -> None:
        """Keep at least ``min_particles_per_mode`` particles carrying each mode.

        This is about scenario diversity, not about the reported posterior: the
        planner draws rollouts from the sampled modes, so a mode with no carriers
        would silently vanish from every scenario even while the belief still gave
        it weight.
        """
        particles = self.particles
        minimum = self.config.filter.min_per_mode
        counts = np.bincount(particles.mode, minlength=len(MODE_ORDER))
        if int(np.min(counts)) >= minimum:
            return
        donors = np.argsort(particles.log_weight, kind="stable")
        cursor = 0
        for index in range(len(MODE_ORDER)):
            while counts[index] < minimum and cursor < particles.size:
                candidate = int(donors[cursor])
                cursor += 1
                current = int(particles.mode[candidate])
                if current == index or counts[current] <= minimum:
                    continue
                counts[current] -= 1
                particles.mode[candidate] = index
                particles.mode_age_s[candidate] = 0.0
                counts[index] += 1
                self.diagnostics.support_reseeds += 1

    # -- correction ------------------------------------------------------

    def observation_variance(self, base_sigma: float, own: OwnStateSummary, context: RivalContext) -> float:
        """Likelihood variance: observation + own-state + model + dropout."""
        residual = self.config.likelihood.model_residual_sigma_mps.value
        dropout = self.config.likelihood.dropout_variance_growth_per_s.value * context.dropout_s
        return base_sigma * base_sigma + own.speed_variance + residual * residual + dropout

    def gap_rate_variance(
        self,
        interval_s: float,
        own: OwnStateSummary,
        context: RivalContext,
        *,
        gap_sigma_m: float | None = None,
    ) -> float:
        """Variance of a gap rate formed by differencing two gap samples.

        Differencing amplifies position noise: two samples each with 1-sigma
        ``sigma_gap``, taken ``dt`` apart, give a rate with 1-sigma
        ``sqrt(2) * sigma_gap / dt``. At a 20 Hz cadence and a sub-metre position
        error that is tens of metres per second -- utterly uninformative -- while
        the configured floor alone would claim 0.3 m/s. Charging the amplified
        term is what stops the filter chasing position noise and reporting a
        confident, wrong intention. Widening the differencing interval is the only
        thing that makes the channel informative, which is exactly the physics.
        """
        if interval_s <= 0.0:
            raise ValueError("a gap rate needs a positive differencing interval")
        sigma_gap = (
            self.config.likelihood.gap_measurement_sigma_m.value if gap_sigma_m is None else gap_sigma_m
        )
        differencing = 2.0 * sigma_gap * sigma_gap / (interval_s * interval_s)
        floor = self.config.likelihood.gap_rate_sigma_mps.value
        return differencing + self.observation_variance(floor, own, context)

    def mode_log_likelihood(
        self,
        observation: RivalObservation,
        own: OwnStateSummary,
        context: RivalContext,
    ) -> tuple[np.ndarray, int]:
        """``log p(z | particle i, mode k)`` for every particle and every mode.

        Returns the ``(N, 4)`` array and the number of observation channels that
        contributed. Evaluating all four modes for every particle is what makes
        the mode posterior analytic instead of sampled.
        """
        particles = self.particles
        behaviour = self.config.behaviour
        deploy = self.deploy_fraction(particles.energy_j)
        gains = (
            behaviour.base_speed_gain_mps.as_array()
            + context.pressure * behaviour.pressure_speed_gain_mps.as_array()
        )
        offsets = particles.pace_bias_mps[:, None] + deploy[:, None] * gains[None, :]
        log_likelihood = np.zeros((particles.size, len(MODE_ORDER)), dtype=np.float64)
        used = 0

        measured = self._gap_rate(observation)
        if measured is not None:
            gap_rate, interval_s = measured
            variance = self.gap_rate_variance(interval_s, own, context, gap_sigma_m=observation.gap_sigma_m)
            # The gap between two cars closes at the rival's pace offset; our own
            # absolute speed cancels, which is why this channel is usable even
            # when only relative information is published.
            expected = offsets if context.is_ahead else -offsets
            log_likelihood += _gaussian_log_pdf(gap_rate, expected, variance)
            used += 1

        if observation.rival_speed_mps is not None:
            variance = self.observation_variance(
                self.config.likelihood.rival_speed_sigma_mps.value, own, context
            )
            log_likelihood += _gaussian_log_pdf(
                observation.rival_speed_mps, own.speed_mps + offsets, variance
            )
            used += 1
        return log_likelihood, used

    def update(
        self,
        observation: RivalObservation,
        own: OwnStateSummary,
        context: RivalContext,
    ) -> None:
        """Propagate to the observation time, weight the particles and resample."""
        dt = observation.session_time_s - self.time_s
        if dt < 0.0:
            raise ValueError("a rival observation earlier than the filter state cannot be applied")
        if dt > 0.0:
            self.propagate(dt, context)

        particles = self.particles
        log_likelihood, used_channels = self.mode_log_likelihood(observation, own, context)

        if used_channels:
            # The particle weight marginalises the mode out analytically: the
            # continuous state is judged on its ability to explain the data under
            # *some* intention, not under one sampled guess.
            log_belief = np.log(np.maximum(particles.mode_belief, np.finfo(np.float64).tiny))
            joint = log_belief + log_likelihood
            peak = np.max(joint, axis=1, keepdims=True)
            mixture = peak[:, 0] + np.log(np.sum(np.exp(joint - peak), axis=1))
            particles.log_weight = particles.log_weight + mixture
            particles.mode_belief = self._floor_belief(np.exp(joint - peak))
            likelihood_peak = np.max(log_likelihood, axis=1, keepdims=True)
            self._sample_mode_path(
                np.eye(len(MODE_ORDER), dtype=np.float64),
                likelihood=np.exp(log_likelihood - likelihood_peak),
            )
            self.diagnostics.last_log_likelihood_spread = float(np.max(mixture) - np.min(mixture))

        weights = self._normalise_weights()
        self.diagnostics.last_ess = effective_sample_size(weights)
        threshold = self.config.filter.ess_resample_fraction.value * particles.size
        self.diagnostics.last_resampled = False
        if self.diagnostics.last_ess < threshold:
            self._resample(weights)
            self._normalise_weights()
            self.diagnostics.resamples += 1
            self.diagnostics.last_resampled = True

        self.time_s = observation.session_time_s
        self.diagnostics.updates += 1
        self.diagnostics.last_observation_s = observation.session_time_s
        self.observation_history.append(observation)

    def _gap_rate(self, observation: RivalObservation) -> tuple[float, float] | None:
        """Gap rate and the interval it was formed over, or ``None``.

        The anchor sample advances only when a rate is actually produced, so
        successive rates are formed over *non-overlapping* intervals of at least
        ``belief_update_interval_s``. Overlapping differences of the same samples
        are not independent evidence, and treating them as if they were is how a
        particle filter talks itself into certainty about a rival it cannot see.
        """
        if observation.gap_m is None:
            return None
        if self._last_gap_m is None or self._last_gap_time_s is None:
            self._last_gap_m = observation.gap_m
            self._last_gap_time_s = observation.session_time_s
            return None
        interval_s = observation.session_time_s - self._last_gap_time_s
        if interval_s < self.config.likelihood.belief_update_interval_s.value:
            return None
        rate = (observation.gap_m - self._last_gap_m) / interval_s
        self._last_gap_m = observation.gap_m
        self._last_gap_time_s = observation.session_time_s
        return rate, interval_s

    def _normalise_weights(self) -> np.ndarray:
        """Log-sum-exp normalisation of the particle weights."""
        particles = self.particles
        weights = normalise_log_weights(particles.log_weight)
        with np.errstate(divide="ignore"):
            particles.log_weight = np.log(np.maximum(weights, np.finfo(np.float64).tiny))
        return weights

    def _resample(self, weights: np.ndarray) -> None:
        """Systematic resampling followed by bounded roughening.

        The mode belief travels with its particle, so resampling cannot delete a
        mode: a particle whose sampled path is ``attack`` still carries whatever
        posterior mass its belief assigns to ``defend``.
        """
        rng = self.streams.stream(STREAM_RESAMPLE)
        indices = systematic_resample(weights, float(rng.random()))
        particles = self.particles
        particles.energy_j = particles.energy_j[indices]
        particles.pace_bias_mps = particles.pace_bias_mps[indices]
        particles.mode = particles.mode[indices]
        particles.mode_age_s = particles.mode_age_s[indices]
        particles.mode_belief = particles.mode_belief[indices]
        particles.log_weight = np.full(particles.size, -math.log(particles.size), dtype=np.float64)
        self._jitter_after_resample(rng)
        self._enforce_mode_support()

    def _jitter_after_resample(self, rng: np.random.Generator) -> None:
        """Bounded roughening so duplicated particles do not stay identical.

        The jitter is a fraction of the prior spread and is clipped, so it can
        never move a particle further than the process model could have moved it.
        """
        particles = self.particles
        dynamics = self.config.dynamics
        energy_span = dynamics.prior_energy_max_j.value - dynamics.prior_energy_min_j.value
        energy_sigma = 0.01 * energy_span
        energy_jitter = np.clip(
            rng.normal(0.0, energy_sigma, size=particles.size),
            -PROCESS_NOISE_CLIP_SIGMAS * energy_sigma,
            PROCESS_NOISE_CLIP_SIGMAS * energy_sigma,
        )
        particles.energy_j = np.clip(
            particles.energy_j + energy_jitter,
            dynamics.energy_min_j.value,
            dynamics.energy_max_j.value,
        )
        pace_sigma = 0.05 * dynamics.pace_bias_sigma_mps.value
        pace_jitter = np.clip(
            rng.normal(0.0, pace_sigma, size=particles.size),
            -PROCESS_NOISE_CLIP_SIGMAS * pace_sigma,
            PROCESS_NOISE_CLIP_SIGMAS * pace_sigma,
        )
        particles.pace_bias_mps = particles.pace_bias_mps + pace_jitter

    # -- reporting -------------------------------------------------------

    def intention_weights(self) -> IntentionWeights:
        """Posterior over reactive intentions, rounded so it sums to exactly 1."""
        weights = self.particles.weights()
        totals = weights @ self.particles.mode_belief
        total = float(np.sum(totals))
        # A zero total can only come from an underflowed weight vector; the
        # uniform fallback keeps the contract satisfied instead of raising.
        totals = np.full(len(MODE_ORDER), 1.0 / len(MODE_ORDER)) if total <= 0.0 else totals / total
        values = [float(v) for v in totals]
        values[-1] = 1.0 - sum(values[:-1])
        return IntentionWeights(
            conserve=values[MODE_INDEX[RivalIntention.CONSERVE]],
            normal=values[MODE_INDEX[RivalIntention.NORMAL]],
            attack=values[MODE_INDEX[RivalIntention.ATTACK]],
            defend=values[MODE_INDEX[RivalIntention.DEFEND]],
        )

    def energy_quantiles(self, coverage: float | None = None) -> tuple[float, float]:
        """Weighted quantile bounds of the energy posterior at ``coverage``."""
        nominal = coverage if coverage is not None else self.config.quantiles.interval_coverage.value
        tail = (1.0 - nominal) / 2.0
        lower, upper = weighted_quantile(
            self.particles.energy_j, self.particles.weights(), (tail, 1.0 - tail)
        )
        return lower, upper

    def energy_mean(self) -> tuple[float, float]:
        """Weighted posterior mean and standard deviation of rival energy."""
        weights = self.particles.weights()
        mean = float(np.sum(weights * self.particles.energy_j))
        variance = float(np.sum(weights * (self.particles.energy_j - mean) ** 2))
        return mean, math.sqrt(max(variance, 0.0))

    def pace_bias(self) -> tuple[float, float]:
        weights = self.particles.weights()
        mean = float(np.sum(weights * self.particles.pace_bias_mps))
        variance = float(np.sum(weights * (self.particles.pace_bias_mps - mean) ** 2))
        return mean, math.sqrt(max(variance, 0.0))

    def to_belief(
        self,
        *,
        slot: str,
        is_ahead: bool,
        now_s: float,
        gap_s: float | None,
        gap_m: float | None,
        relative_speed_mps: float | None,
        lateral_geometry_known: bool = False,
        lap_time_s: float = 90.0,
        reference_speed_mps: float | None = None,
    ) -> RivalBelief:
        """Render the posterior as the frozen ``RivalBelief`` contract.

        Energy is reported as a quantile interval with a declared coverage and a
        mean whose provenance is ``estimated``. The contract itself refuses a
        ``measured`` provenance for rival energy; this method never tries.
        """
        observed_at = self.diagnostics.last_observation_s
        age = None if observed_at is None else max(0.0, now_s - observed_at)
        coverage = self.config.quantiles.interval_coverage.value
        lower, upper = self.energy_quantiles(coverage)
        mean, sigma = self.energy_mean()
        pace_mean, pace_sigma = self.pace_bias()
        gap_sigma = self.config.likelihood.gap_rate_sigma_mps.value

        return RivalBelief(
            car_id=self.car_id,
            slot=slot,
            is_ahead=is_ahead,
            gap_s=_optional_scalar(gap_s, "s", age, observed_at, standard_deviation=None),
            gap_m=_optional_scalar(gap_m, "m", age, observed_at, standard_deviation=None),
            relative_speed_mps=_optional_scalar(
                relative_speed_mps, "m/s", age, observed_at, standard_deviation=gap_sigma
            ),
            energy_interval_j=IntervalValue(
                lower=lower,
                upper=upper,
                unit="J",
                kind="quantile",
                coverage=coverage,
                provenance=Provenance.ESTIMATED,
                quality=Quality.DEGRADED,
                observed_at_s=observed_at,
                age_s=age,
            ),
            energy_mean_j=ScalarValue(
                value=mean,
                unit="J",
                provenance=Provenance.ESTIMATED,
                quality=Quality.DEGRADED,
                observed_at_s=observed_at,
                age_s=age,
                standard_deviation=sigma,
            ),
            pace_bias_s_per_lap=_pace_bias_scalar(
                pace_mean,
                pace_sigma,
                lap_time_s=lap_time_s,
                reference_speed_mps=reference_speed_mps,
                observed_at_s=observed_at,
                age_s=age,
            ),
            intentions=self.intention_weights(),
            observation_age_s=age,
            lateral_geometry_known=lateral_geometry_known,
        )

    # -- snapshot --------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Particles, RNG state, mode memory and observation history."""
        particles = self.particles
        return {
            "car_id": self.car_id,
            "seed": self.seed,
            "time_s": self.time_s,
            "particles": {
                "energy_j": particles.energy_j.tolist(),
                "pace_bias_mps": particles.pace_bias_mps.tolist(),
                "mode": particles.mode.tolist(),
                "mode_age_s": particles.mode_age_s.tolist(),
                "mode_belief": particles.mode_belief.tolist(),
                "log_weight": particles.log_weight.tolist(),
            },
            "rng": self.streams.capture(),
            "diagnostics": {
                "updates": self.diagnostics.updates,
                "resamples": self.diagnostics.resamples,
                "last_ess": self.diagnostics.last_ess,
                "last_resampled": self.diagnostics.last_resampled,
                "mode_floor_applications": self.diagnostics.mode_floor_applications,
                "support_reseeds": self.diagnostics.support_reseeds,
                "last_observation_s": self.diagnostics.last_observation_s,
                "last_log_likelihood_spread": self.diagnostics.last_log_likelihood_spread,
                "notes": list(self.diagnostics.notes),
            },
            "history": [
                {
                    "session_time_s": obs.session_time_s,
                    "gap_m": obs.gap_m,
                    "gap_s": obs.gap_s,
                    "rival_speed_mps": obs.rival_speed_mps,
                    "gap_sigma_m": obs.gap_sigma_m,
                    "event_ids": list(obs.event_ids),
                    "quality": obs.quality.value,
                }
                for obs in self.observation_history
            ],
            "last_gap_m": self._last_gap_m,
            "last_gap_time_s": self._last_gap_time_s,
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.car_id = snapshot["car_id"]
        self.seed = snapshot["seed"]
        self.time_s = float(snapshot["time_s"])
        payload = snapshot["particles"]
        self.particles = ParticleSet(
            energy_j=np.array(payload["energy_j"], dtype=np.float64),
            pace_bias_mps=np.array(payload["pace_bias_mps"], dtype=np.float64),
            mode=np.array(payload["mode"], dtype=np.int64),
            mode_age_s=np.array(payload["mode_age_s"], dtype=np.float64),
            mode_belief=np.array(payload["mode_belief"], dtype=np.float64),
            log_weight=np.array(payload["log_weight"], dtype=np.float64),
        )
        self.streams.restore(snapshot["rng"])
        diagnostics = snapshot["diagnostics"]
        self.diagnostics = RivalFilterDiagnostics(
            updates=int(diagnostics["updates"]),
            resamples=int(diagnostics["resamples"]),
            last_ess=float(diagnostics["last_ess"]),
            last_resampled=bool(diagnostics["last_resampled"]),
            mode_floor_applications=int(diagnostics["mode_floor_applications"]),
            support_reseeds=int(diagnostics["support_reseeds"]),
            last_observation_s=diagnostics["last_observation_s"],
            last_log_likelihood_spread=float(diagnostics["last_log_likelihood_spread"]),
            notes=list(diagnostics["notes"]),
        )
        self.observation_history = [
            RivalObservation(
                session_time_s=item["session_time_s"],
                gap_m=item["gap_m"],
                gap_s=item["gap_s"],
                rival_speed_mps=item["rival_speed_mps"],
                gap_sigma_m=item["gap_sigma_m"],
                event_ids=tuple(item["event_ids"]),
                quality=Quality(item["quality"]),
            )
            for item in snapshot["history"]
        ]
        self._last_gap_m = snapshot["last_gap_m"]
        self._last_gap_time_s = snapshot["last_gap_time_s"]


def _largest_remainder(expected: np.ndarray, total: int) -> np.ndarray:
    """Round a vector of expected counts to integers summing exactly to ``total``."""
    floors = np.floor(expected).astype(np.int64)
    floors = np.maximum(floors, 0)
    deficit = total - int(floors.sum())
    if deficit > 0:
        remainders = expected - np.floor(expected)
        order = np.argsort(-remainders, kind="stable")
        for position in range(deficit):
            floors[order[position % order.size]] += 1
    elif deficit < 0:  # pragma: no cover - floors can only undershoot
        order = np.argsort(expected - np.floor(expected), kind="stable")
        position = 0
        while deficit < 0:
            index = order[position % order.size]
            if floors[index] > 0:
                floors[index] -= 1
                deficit += 1
            position += 1
    return floors


def _gaussian_log_pdf(observed: float, expected: np.ndarray, variance: float) -> np.ndarray:
    if variance <= 0.0:  # pragma: no cover - defensive
        raise ValueError("likelihood variance must be positive")
    residual = observed - expected
    return -0.5 * (residual * residual / variance + math.log(2.0 * math.pi * variance))


def _pace_bias_scalar(
    pace_mean_mps: float,
    pace_sigma_mps: float,
    *,
    lap_time_s: float,
    reference_speed_mps: float | None,
    observed_at_s: float | None,
    age_s: float | None,
) -> ScalarValue:
    """Convert a pace offset in m/s into seconds per lap.

    ``t = L / v`` gives ``dt/dv = -t / v``, so a sustained offset ``dv`` is worth
    ``-lap_time * dv / v`` seconds a lap. Without a reference speed the
    conversion is undefined and the field is reported missing rather than guessed.
    """
    if reference_speed_mps is None or reference_speed_mps <= 0.0 or lap_time_s <= 0.0:
        return ScalarValue(
            value=None,
            unit="s",
            provenance=Provenance.ESTIMATED,
            quality=Quality.MISSING,
            observed_at_s=observed_at_s,
            age_s=age_s,
        )
    scale = lap_time_s / reference_speed_mps
    return ScalarValue(
        value=-pace_mean_mps * scale,
        unit="s",
        provenance=Provenance.ESTIMATED,
        quality=Quality.DEGRADED,
        observed_at_s=observed_at_s,
        age_s=age_s,
        standard_deviation=pace_sigma_mps * scale,
    )


def _optional_scalar(
    value: float | None,
    unit: str,
    age_s: float | None,
    observed_at_s: float | None,
    *,
    standard_deviation: float | None,
) -> ScalarValue:
    if value is None:
        return ScalarValue(
            value=None,
            unit=unit,
            provenance=Provenance.ESTIMATED,
            quality=Quality.MISSING,
            observed_at_s=observed_at_s,
            age_s=age_s,
        )
    return ScalarValue(
        value=value,
        unit=unit,
        provenance=Provenance.ESTIMATED,
        quality=Quality.VALID,
        observed_at_s=observed_at_s,
        age_s=age_s,
        standard_deviation=standard_deviation,
    )


__all__ = [
    "PROCESS_NOISE_CLIP_SIGMAS",
    "STREAM_INIT",
    "STREAM_MODE",
    "STREAM_NAMES",
    "STREAM_PROCESS",
    "STREAM_RESAMPLE",
    "STREAM_SCENARIO",
    "OwnStateSummary",
    "ParticleSet",
    "RivalContext",
    "RivalFilterDiagnostics",
    "RivalObservation",
    "RivalParticleFilter",
    "effective_sample_size",
    "normalise_log_weights",
    "systematic_resample",
    "weighted_quantile",
]
