"""Scenario sampling: temporal correlation, reachability and honest widening.

A planner rolls these trajectories out. If a sampled opponent's battery could
jump between ticks the planner would learn that energy is free, so the
correlation and reachability properties here are load-bearing, not decorative.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from afterlap_contracts import RivalIntention
from afterlap_core.estimation import (
    OwnStateSummary,
    RivalConfig,
    RivalContext,
    RivalObservation,
    RivalParticleFilter,
    reachable_energy_step_j,
    sample_scenarios,
)

from .conftest import RIVAL_CAR_ID


def _prepared(rival_config: RivalConfig, *, seed: int = 21, steps: int = 20) -> RivalParticleFilter:
    filter_ = RivalParticleFilter(rival_config, car_id=RIVAL_CAR_ID, seed=seed)
    gap = 40.0
    time_s = 0.0
    own = OwnStateSummary(speed_mps=75.0, speed_variance=0.04)
    for step in range(steps):
        time_s += 0.5
        gap += (1.2 if step % 4 else -0.4) * 0.5
        filter_.update(
            RivalObservation(session_time_s=time_s, gap_m=gap, gap_sigma_m=0.05),
            own,
            RivalContext(is_ahead=True),
        )
    return filter_


def test_sampled_energy_is_temporally_correlated(rival_config: RivalConfig) -> None:
    """Lag-1 autocorrelation of each trajectory must be high.

    Each scenario is one particle rolled continuously forward, so consecutive
    energies differ only by a step of the process model.

    The per-trajectory threshold is a median rather than a minimum on purpose: a
    particle that has actually run flat sits on the empty-battery clip and its
    remaining trace is clipped process noise, so its *relative* autocorrelation is
    legitimately low while its absolute movement stays tiny. The cross-sectional
    check and the per-step bound below cover that case directly. A shuffled
    control is included so the numbers mean something: destroying the time
    ordering must destroy the correlation.
    """
    filter_ = _prepared(rival_config)
    ensemble = sample_scenarios(filter_, 64, seed=5, horizon_s=20.0, step_s=0.5)
    window = rival_config.dynamics.energy_max_j.value - rival_config.dynamics.energy_min_j.value

    live = [
        trajectory
        for trajectory in ensemble.trajectories
        if np.isfinite(trajectory.energy_lag1_autocorrelation())
    ]
    assert len(live) > 32, "most trajectories must have a varying energy trace"
    autocorrelations = [t.energy_lag1_autocorrelation() for t in live]
    # Measured over four preparation seeds: mean 0.84, median 0.88, 10th
    # percentile 0.69. The low tail is entirely trajectories pinned against the
    # empty-battery clip, whose absolute movement is bounded below.
    assert float(np.median(autocorrelations)) > 0.8, (
        f"median lag-1 autocorrelation was only {float(np.median(autocorrelations)):.4f}"
    )
    assert float(np.mean(autocorrelations)) > 0.75, (
        f"mean lag-1 autocorrelation was only {float(np.mean(autocorrelations)):.4f}"
    )

    # The statement that actually matters -- "one sampled opponent cannot jump
    # from empty to full between ticks" -- is a *cross-sectional* one: which
    # scenario is which must persist from step to step. That is immune to the
    # clipped noise a trajectory sitting on the empty-battery floor shows.
    for step in range(ensemble.trajectories[0].energy_j.size - 1):
        now = ensemble.energy_at(step)
        later = ensemble.energy_at(step + 1)
        if float(np.std(now)) == 0.0 or float(np.std(later)) == 0.0:  # pragma: no cover
            continue
        assert float(np.corrcoef(now, later)[0, 1]) > 0.97, f"scenario identity broke at step {step}"

    worst_step = max(t.max_absolute_energy_step_j() for t in ensemble.trajectories)
    # 8 % of the window per half-second step. The reachable bound checked in the
    # next test is the physical statement; this one is the coarser "an opponent
    # cannot go from empty to full between two ticks" claim.
    assert worst_step < 0.08 * window, (
        f"a single step moved {worst_step:.0f} J, {worst_step / window:.1%} of the battery window"
    )

    rng = np.random.default_rng(0)
    shuffled = []
    for trajectory in live:
        series = trajectory.energy_j.copy()
        rng.shuffle(series)
        centred = series - series.mean()
        shuffled.append(float(np.dot(centred[:-1], centred[1:]) / np.dot(centred, centred)))
    assert float(np.mean(shuffled)) < 0.3, (
        "the control must lose the correlation, otherwise the measurement above is vacuous"
    )


def test_no_single_step_changes_energy_by_more_than_is_reachable(rival_config: RivalConfig) -> None:
    """A sampled battery cannot teleport: bound the per-step change physically.

    The bound is deployment at the configured ceiling for one step plus the
    clipped process noise. It is computed from the manifest, not fitted to the
    observed maximum.
    """
    filter_ = _prepared(rival_config)
    step_s = 0.5
    ensemble = sample_scenarios(filter_, 48, seed=9, horizon_s=15.0, step_s=step_s)
    bound = reachable_energy_step_j(filter_, step_s, ensemble.model_mismatch)
    assert ensemble.reachable_energy_step_j == pytest.approx(bound)

    worst = max(t.max_absolute_energy_step_j() for t in ensemble.trajectories)
    assert worst <= bound, f"a step moved {worst:.0f} J against a reachable bound of {bound:.0f} J"
    # And the bound is not vacuous: it is far below the whole window.
    window = rival_config.dynamics.energy_max_j.value - rival_config.dynamics.energy_min_j.value
    assert bound < 0.1 * window


def test_uncertainty_widens_under_a_dropout(rival_config: RivalConfig) -> None:
    """A belief that has not been observed for a while must fan out faster.

    The widening is read off the sampled pace offset, not off energy. Energy is
    clipped to the legal window, so once part of the ensemble has run flat its
    spread saturates and stops responding -- measuring widening there would give a
    number that moves for the wrong reason. The reachable per-step energy bound is
    checked separately and does grow.
    """
    filter_ = _prepared(rival_config)
    fresh = sample_scenarios(filter_, 96, seed=3, horizon_s=15.0, step_s=0.5, dropout_s=0.0)
    stale = sample_scenarios(filter_, 96, seed=3, horizon_s=15.0, step_s=0.5, dropout_s=6.0)

    assert stale.offset_spread_at(-1) > fresh.offset_spread_at(-1)
    assert stale.reachable_energy_step_j > fresh.reachable_energy_step_j

    # And the widening is monotone in the dropout, not a one-off.
    spreads = [
        sample_scenarios(filter_, 96, seed=3, horizon_s=15.0, step_s=0.5, dropout_s=dropout).offset_spread_at(
            -1
        )
        for dropout in (0.0, 2.0, 4.0, 8.0)
    ]
    assert spreads == sorted(spreads), spreads
    assert spreads[-1] > 2.0 * spreads[0], f"a 8 s dropout barely widened anything: {spreads}"


def test_model_mismatch_widens_scenarios_and_can_never_narrow_them(rival_config: RivalConfig) -> None:
    filter_ = _prepared(rival_config)
    spreads = [
        sample_scenarios(
            filter_, 96, seed=11, horizon_s=12.0, step_s=0.5, model_mismatch=mismatch
        ).offset_spread_at(-1)
        for mismatch in (1.0, 1.5, 2.5, 4.0)
    ]
    assert spreads == sorted(spreads), spreads
    assert spreads[-1] > spreads[0]
    with pytest.raises(ValueError, match="never narrow"):
        sample_scenarios(filter_, 8, seed=1, horizon_s=5.0, step_s=0.5, model_mismatch=0.5)


def test_sampling_is_reproducible_and_leaves_the_belief_untouched(rival_config: RivalConfig) -> None:
    """Repeated planning at the same tick must see the same opponents."""
    filter_ = _prepared(rival_config)
    before = filter_.snapshot()

    first = sample_scenarios(filter_, 32, seed=17, horizon_s=10.0, step_s=0.5)
    second = sample_scenarios(filter_, 32, seed=17, horizon_s=10.0, step_s=0.5)
    different = sample_scenarios(filter_, 32, seed=18, horizon_s=10.0, step_s=0.5)

    for left, right in zip(first.trajectories, second.trajectories, strict=True):
        assert np.array_equal(left.energy_j, right.energy_j)
        assert left.modes == right.modes
        assert left.weight == right.weight
    assert not np.array_equal(first.trajectories[0].energy_j, different.trajectories[0].energy_j)

    after = filter_.snapshot()
    assert after["particles"] == before["particles"]
    assert after["rng"] == before["rng"]


def test_scenarios_reuse_the_belief_particles_with_their_weights(rival_config: RivalConfig) -> None:
    """Scenarios are drawn from the live particles, not resampled from a prior."""
    filter_ = _prepared(rival_config)
    ensemble = sample_scenarios(filter_, 40, seed=23, horizon_s=8.0, step_s=0.5)
    for trajectory in ensemble.trajectories:
        assert 0 <= trajectory.initial_particle_index < filter_.particles.size
        assert trajectory.energy_j[0] == pytest.approx(
            float(filter_.particles.energy_j[trajectory.initial_particle_index])
        )
    assert sum(t.weight for t in ensemble.trajectories) == pytest.approx(1.0)


def test_scenario_energy_stays_inside_the_legal_window(rival_config: RivalConfig) -> None:
    filter_ = _prepared(rival_config)
    ensemble = sample_scenarios(filter_, 64, seed=29, horizon_s=40.0, step_s=0.5, model_mismatch=2.0)
    minimum = rival_config.dynamics.energy_min_j.value
    maximum = rival_config.dynamics.energy_max_j.value
    for trajectory in ensemble.trajectories:
        assert float(np.min(trajectory.energy_j)) >= minimum
        assert float(np.max(trajectory.energy_j)) <= maximum


def test_scenario_modes_persist_rather_than_flickering(rival_config: RivalConfig) -> None:
    """A sampled opponent must not change intention every half second."""
    filter_ = _prepared(rival_config)
    ensemble = sample_scenarios(filter_, 64, seed=31, horizon_s=20.0, step_s=0.5)
    switch_rates = []
    for trajectory in ensemble.trajectories:
        modes = trajectory.modes
        switches = sum(1 for a, b in pairwise(modes) if a != b)
        switch_rates.append(switches / (len(modes) - 1))
    mean_rate = float(np.mean(switch_rates))
    # lam = 1 - exp(-0.5 / 6) is about 0.08, and the prior's off-diagonal mass is
    # small, so a switch every other step would mean the mode memory did nothing.
    assert mean_rate < 0.15, f"modes flickered at {mean_rate:.3f} switches per step"
    assert all(mode in set(RivalIntention) for t in ensemble.trajectories for mode in t.modes)


def test_the_ensemble_renders_as_a_weighted_sample_contract(rival_config: RivalConfig) -> None:
    filter_ = _prepared(rival_config)
    ensemble = sample_scenarios(filter_, 24, seed=37, horizon_s=6.0, step_s=0.5)
    belief = ensemble.as_ensemble_belief()
    assert len(belief.samples) == 24
    assert belief.unit == "J"
    assert belief.effective_sample_size is not None
    assert 1.0 <= belief.effective_sample_size <= 24.0
    assert all(sample.weight >= 0.0 for sample in belief.samples)


@pytest.mark.parametrize(
    ("count", "horizon_s", "step_s"),
    [(0, 10.0, 0.5), (4, 10.0, 0.0), (4, 0.2, 0.5)],
)
def test_invalid_scenario_requests_are_refused(
    rival_config: RivalConfig, count: int, horizon_s: float, step_s: float
) -> None:
    filter_ = _prepared(rival_config, steps=4)
    with pytest.raises(ValueError):
        sample_scenarios(filter_, count, seed=1, horizon_s=horizon_s, step_s=step_s)
