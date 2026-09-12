"""Weighted scenario trajectories for planner rollouts.

A scenario is *one particle rolled forward continuously*, not a fresh draw at
each tick. That is the whole point: a sampled opponent must not be able to jump
from empty to full battery between two steps, and its intention must persist the
way the mode-transition prior says it persists. Sampling independently per tick
would produce trajectories whose statistics look right and whose behaviour is
physically impossible, and a planner rolling those out would systematically
under-value energy.

Reuse
-----

``sample_scenarios`` never mutates the live belief. It copies the particle set,
draws ``count`` indices from the current weights and rolls those copies forward
in a private RNG stream keyed by ``seed``. Repeated planning at the same tick may
therefore reuse the same particles with updated weights, which is what makes
successive plans comparable rather than re-randomised.

Widening
--------

``dropout_s`` and ``model_mismatch`` widen the process noise applied along the
rollout. A belief that has not been observed for a while, or one whose residuals
say the model is wrong, produces visibly wider scenarios rather than the same
confident fan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from afterlap_contracts import EnsembleBelief, RivalIntention, WeightedSample
from afterlap_core.rng import derive_seed

from .config import MODE_ORDER
from .rivals import (
    PROCESS_NOISE_CLIP_SIGMAS,
    ParticleSet,
    RivalContext,
    RivalParticleFilter,
)


@dataclass(frozen=True, slots=True)
class ScenarioTrajectory:
    """One weighted opponent future.

    Arrays are aligned on ``times_s`` and share its length, including the initial
    sample at ``times_s[0]``.
    """

    scenario_id: str
    weight: float
    times_s: np.ndarray
    energy_j: np.ndarray
    speed_offset_mps: np.ndarray
    modes: tuple[RivalIntention, ...]
    initial_particle_index: int

    def __post_init__(self) -> None:
        lengths = {
            self.times_s.shape[0],
            self.energy_j.shape[0],
            self.speed_offset_mps.shape[0],
            len(self.modes),
        }
        if len(lengths) != 1:
            raise ValueError("scenario arrays must all share the trajectory length")
        if self.weight < 0.0:
            raise ValueError("scenario weight cannot be negative")

    @property
    def horizon_s(self) -> float:
        return float(self.times_s[-1] - self.times_s[0])

    def energy_lag1_autocorrelation(self) -> float:
        """Lag-1 autocorrelation of the energy trace, or NaN if it is constant."""
        series = self.energy_j
        if series.shape[0] < 3:
            return math.nan
        centred = series - series.mean()
        denominator = float(np.dot(centred, centred))
        if denominator <= 0.0:
            return math.nan
        return float(np.dot(centred[:-1], centred[1:]) / denominator)

    def max_absolute_energy_step_j(self) -> float:
        if self.energy_j.shape[0] < 2:
            return 0.0
        return float(np.max(np.abs(np.diff(self.energy_j))))


@dataclass(frozen=True, slots=True)
class ScenarioEnsemble:
    """The weighted set handed to the planner."""

    car_id: str
    trajectories: tuple[ScenarioTrajectory, ...]
    step_s: float
    horizon_s: float
    seed: int
    dropout_s: float = 0.0
    model_mismatch: float = 1.0
    reachable_energy_step_j: float = 0.0

    def __post_init__(self) -> None:
        if not self.trajectories:
            raise ValueError("a scenario ensemble needs at least one trajectory")
        total = sum(t.weight for t in self.trajectories)
        if total <= 0.0:
            raise ValueError("scenario weights must sum to a positive number")

    @property
    def weights(self) -> np.ndarray:
        return np.array([t.weight for t in self.trajectories], dtype=np.float64)

    def energy_at(self, step: int) -> np.ndarray:
        return np.array([t.energy_j[step] for t in self.trajectories], dtype=np.float64)

    def energy_spread_at(self, step: int) -> float:
        """Weighted standard deviation of energy across the ensemble at ``step``.

        Note the caveat: energy is clipped to the legal window, so once a
        meaningful share of the ensemble has run flat this statistic saturates and
        stops responding to added process noise. Use
        :meth:`offset_spread_at` or a shorter horizon to observe widening.
        """
        return self._spread(self.energy_at(step))

    def offset_at(self, step: int) -> np.ndarray:
        return np.array([t.speed_offset_mps[step] for t in self.trajectories], dtype=np.float64)

    def offset_spread_at(self, step: int) -> float:
        """Weighted standard deviation of the sampled pace offset at ``step``.

        Unlike energy this quantity is not clipped, so it is the honest place to
        read whether the ensemble actually widened.
        """
        return self._spread(self.offset_at(step))

    def _spread(self, values: np.ndarray) -> float:
        weights = self.weights
        weights = weights / float(np.sum(weights))
        mean = float(np.sum(weights * values))
        return math.sqrt(float(np.sum(weights * (values - mean) ** 2)))

    def as_ensemble_belief(self, step: int = -1) -> EnsembleBelief:
        """Terminal (or ``step``) energy as the frozen weighted-sample contract."""
        samples = tuple(
            WeightedSample(
                sample_id=trajectory.scenario_id,
                weight=trajectory.weight,
                values={
                    "energy_j": float(trajectory.energy_j[step]),
                    "speed_offset_mps": float(trajectory.speed_offset_mps[step]),
                    "mode_index": float(MODE_ORDER.index(trajectory.modes[step])),
                },
            )
            for trajectory in self.trajectories
        )
        weights = self.weights
        weights = weights / float(np.sum(weights))
        ess = 1.0 / float(np.sum(weights * weights))
        return EnsembleBelief(samples=samples, unit="J", effective_sample_size=ess)


def reachable_energy_step_j(filter_: RivalParticleFilter, step_s: float, model_mismatch: float) -> float:
    """Largest energy change a single step could physically produce.

    Deployment at the configured ceiling plus the clipped process noise. A
    sampler that exceeded this would be producing a battery that teleports.
    """
    dynamics = filter_.config.dynamics
    deploy = dynamics.max_deploy_power_w.value * step_s
    noise = PROCESS_NOISE_CLIP_SIGMAS * dynamics.energy_process_sigma_w.value * step_s * model_mismatch
    return deploy + noise


def sample_scenarios(
    belief: RivalParticleFilter,
    count: int,
    seed: int,
    *,
    horizon_s: float = 12.0,
    step_s: float = 0.5,
    context: RivalContext | None = None,
    dropout_s: float = 0.0,
    model_mismatch: float = 1.0,
) -> ScenarioEnsemble:
    """Draw ``count`` temporally correlated opponent futures from ``belief``.

    ``seed`` fully determines the draw: the same belief, count and seed give the
    same ensemble, which is what lets a paired experiment compare two plans
    against identical opponents. The live filter is not modified.
    """
    if count <= 0:
        raise ValueError("scenario count must be positive")
    if step_s <= 0.0:
        raise ValueError("scenario step must be positive")
    if horizon_s < step_s:
        raise ValueError("scenario horizon must be at least one step")
    if model_mismatch < 1.0:
        raise ValueError("model mismatch widens uncertainty; it can never narrow it")
    if dropout_s < 0.0:
        raise ValueError("dropout cannot be negative")

    rival_context = context or RivalContext()
    steps = round(horizon_s / step_s)
    rng = np.random.default_rng(derive_seed(seed, belief.car_id, belief.seed, count, steps))

    weights = belief.particles.weights()
    indices = rng.choice(belief.particles.size, size=count, replace=True, p=weights)

    widening = model_mismatch * (1.0 + dropout_s * _dropout_widening(belief))
    dynamics = belief.config.dynamics
    transition = belief.config.step_transition(step_s)
    cumulative = np.cumsum(transition, axis=1)
    behaviour = belief.config.behaviour
    base_speed = behaviour.base_speed_gain_mps.as_array()
    pressure_speed = behaviour.pressure_speed_gain_mps.as_array()
    base_power = behaviour.base_power_w.as_array()
    pressure_power = behaviour.pressure_power_w.as_array()
    reference = dynamics.deploy_reference_energy_j.value
    energy_sigma = dynamics.energy_process_sigma_w.value * step_s * widening
    pace_tau = dynamics.pace_bias_time_constant_s.value
    pace_decay = math.exp(-step_s / pace_tau)
    pace_sigma = (
        dynamics.pace_bias_process_sigma_mps.value * math.sqrt(max(1.0 - pace_decay**2, 0.0)) * widening
    )

    source = belief.particles
    energy = source.energy_j[indices].copy()
    pace = source.pace_bias_mps[indices].copy()
    mode = source.mode[indices].copy()
    scenario_weights = weights[indices]
    scenario_weights = scenario_weights / float(np.sum(scenario_weights))

    times = belief.time_s + step_s * np.arange(steps + 1, dtype=np.float64)
    energy_trace = np.empty((count, steps + 1), dtype=np.float64)
    offset_trace = np.empty((count, steps + 1), dtype=np.float64)
    mode_trace = np.empty((count, steps + 1), dtype=np.int64)

    def offsets(energy_now: np.ndarray, pace_now: np.ndarray, mode_now: np.ndarray) -> np.ndarray:
        deploy = np.clip(energy_now / reference, 0.0, 1.0)
        gain = base_speed[mode_now] + rival_context.pressure * pressure_speed[mode_now]
        return np.asarray(pace_now + deploy * gain)

    energy_trace[:, 0] = energy
    offset_trace[:, 0] = offsets(energy, pace, mode)
    mode_trace[:, 0] = mode

    for step in range(1, steps + 1):
        draws = rng.random(count)
        rows = cumulative[mode]
        mode = np.clip((draws[:, None] > rows).sum(axis=1).astype(np.int64), 0, len(MODE_ORDER) - 1)
        deploy = np.clip(energy / reference, 0.0, 1.0)
        power = deploy * (base_power[mode] + rival_context.pressure * pressure_power[mode])
        noise = np.clip(
            rng.normal(0.0, energy_sigma, size=count) if energy_sigma > 0.0 else np.zeros(count),
            -PROCESS_NOISE_CLIP_SIGMAS * max(energy_sigma, 1e-12),
            PROCESS_NOISE_CLIP_SIGMAS * max(energy_sigma, 1e-12),
        )
        energy = np.clip(
            energy - power * step_s + noise,
            dynamics.energy_min_j.value,
            dynamics.energy_max_j.value,
        )
        pace_noise = np.clip(
            rng.normal(0.0, pace_sigma, size=count) if pace_sigma > 0.0 else np.zeros(count),
            -PROCESS_NOISE_CLIP_SIGMAS * max(pace_sigma, 1e-12),
            PROCESS_NOISE_CLIP_SIGMAS * max(pace_sigma, 1e-12),
        )
        pace = pace * pace_decay + pace_noise
        energy_trace[:, step] = energy
        offset_trace[:, step] = offsets(energy, pace, mode)
        mode_trace[:, step] = mode

    trajectories = tuple(
        ScenarioTrajectory(
            scenario_id=f"{belief.car_id}-scenario-{index:04d}",
            weight=float(scenario_weights[index]),
            times_s=times.copy(),
            energy_j=energy_trace[index].copy(),
            speed_offset_mps=offset_trace[index].copy(),
            modes=tuple(MODE_ORDER[int(m)] for m in mode_trace[index]),
            initial_particle_index=int(indices[index]),
        )
        for index in range(count)
    )
    return ScenarioEnsemble(
        car_id=belief.car_id,
        trajectories=trajectories,
        step_s=step_s,
        horizon_s=steps * step_s,
        seed=seed,
        dropout_s=dropout_s,
        model_mismatch=model_mismatch,
        reachable_energy_step_j=reachable_energy_step_j(belief, step_s, widening),
    )


def _dropout_widening(belief: RivalParticleFilter) -> float:
    """Widening rate per second of dropout, derived from the likelihood manifest."""
    growth = belief.config.likelihood.dropout_variance_growth_per_s.value
    residual = belief.config.likelihood.model_residual_sigma_mps.value
    return growth / max(residual * residual, 1e-9)


def particles_from(belief: RivalParticleFilter) -> ParticleSet:
    """A detached copy of the belief's particles, for planners that reuse them."""
    return belief.particles.copy()


__all__ = [
    "ScenarioEnsemble",
    "ScenarioTrajectory",
    "particles_from",
    "reachable_energy_step_j",
    "sample_scenarios",
]
