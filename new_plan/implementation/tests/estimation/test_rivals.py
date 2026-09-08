"""The rival belief filter: isolation from truth, ambiguity, and recovery.

The first test here is the load-bearing one for the whole programme. If beliefs
change when hidden truth changes while the delivered observations do not, then
some path from the simulator into inference exists and every measured result is
contaminated.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from afterlap_contracts import Provenance, RivalIntention
from afterlap_core.estimation import (
    OwnCarConfig,
    OwnStateSummary,
    RivalConfig,
    RivalContext,
    RivalObservation,
    RivalParticleFilter,
    create_state,
    effective_sample_size,
    normalise_log_weights,
    systematic_resample,
    update,
)
from afterlap_core.estimation.config import MODE_ORDER

from .conftest import (
    OWN_CAR_ID,
    RIVAL_CAR_ID,
    SESSION_ID,
    SyntheticRun,
    make_context,
    make_run,
)


def _filter(rival_config: RivalConfig, seed: int = 99) -> RivalParticleFilter:
    return RivalParticleFilter(rival_config, car_id=RIVAL_CAR_ID, seed=seed)


def _own() -> OwnStateSummary:
    return OwnStateSummary(speed_mps=75.0, speed_variance=0.04, acceleration_mps2=0.0)


#: Gap resolution a well-instrumented source could declare. These unit tests
#: supply exact gaps, so declaring a small sigma is the honest description of the
#: data they feed; the default manifest figure covers a noisier public feed.
PRECISE_GAP_SIGMA_M = 0.05


def _drive(
    filter_: RivalParticleFilter,
    gap_rate_mps: float,
    *,
    steps: int,
    dt_s: float = 0.5,
    start_gap_m: float = 40.0,
    context: RivalContext | None = None,
    gap_sigma_m: float = PRECISE_GAP_SIGMA_M,
) -> None:
    """Feed a constant gap-rate observation sequence."""
    rival_context = context or RivalContext(is_ahead=True, pressure=0.0)
    gap = start_gap_m
    time_s = filter_.time_s
    for _ in range(steps):
        time_s += dt_s
        gap += gap_rate_mps * dt_s
        filter_.update(
            RivalObservation(session_time_s=time_s, gap_m=gap, rival_speed_mps=None, gap_sigma_m=gap_sigma_m),
            _own(),
            rival_context,
        )


# -- isolation from truth -------------------------------------------------


def test_replacing_every_hidden_rival_state_leaves_beliefs_identical(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Truth mutation: scramble the hidden state, hold the observations byte-identical.

    The observations are compared by canonical JSON before the estimator runs, so
    "byte-identical" is asserted rather than assumed, and the resulting estimates
    are compared the same way.
    """
    run = make_run(
        own_config,
        rival_config,
        scenario_id="truth-mutation",
        seed=61,
        duration_s=12.0,
        mode_schedule=((0.0, RivalIntention.NORMAL), (5.0, RivalIntention.ATTACK)),
        rival_energy_j=2_800_000.0,
    )

    # Replace every hidden rival state with unrelated values. Energy is inverted
    # across the window, the modes are permuted and the speeds are scrambled.
    mutated_rival = tuple(
        replace(
            truth,
            progress_m=truth.progress_m * -3.7 + 12_345.0,
            speed_mps=truth.speed_mps * 0.11 - 400.0,
            energy_j=4_000_000.0 - truth.energy_j,
            mode=MODE_ORDER[(MODE_ORDER.index(truth.mode) + 2) % len(MODE_ORDER)],
        )
        for truth in run.rival_truth
    )
    mutated_own = tuple(
        replace(truth, energy_j=4_000_000.0 - truth.energy_j, power_w=-truth.power_w)
        for truth in run.own_truth
    )
    mutated = SyntheticRun(
        scenario_id=run.scenario_id,
        own_truth=mutated_own,
        rival_truth=mutated_rival,
        events=run.events,  # the delivered observations do not move
        dt_s=run.dt_s,
        energy_channel=run.energy_channel,
    )

    assert [e.canonical_json() for e in run.events] == [e.canonical_json() for e in mutated.events]
    assert mutated.rival_truth != run.rival_truth
    assert mutated.own_truth != run.own_truth

    estimates = []
    for source in (run, mutated):
        state = create_state(
            session_id=SESSION_ID,
            car_id=OWN_CAR_ID,
            seed=13,
            own_config=own_config,
            rival_config=rival_config,
        )
        estimates.append(update(source.events, state, make_context(12.0)))

    assert estimates[0].canonical_json() == estimates[1].canonical_json()
    belief = estimates[0].rival_in_slot("ahead_1")
    assert belief is not None
    assert belief.energy_mean_j is not None
    assert belief.energy_mean_j.provenance is Provenance.ESTIMATED
    assert belief.energy_interval_j is not None
    assert belief.energy_interval_j.provenance is not Provenance.MEASURED
    assert belief.lateral_geometry_known is False


def test_rival_energy_is_never_labelled_measured(rival_config: RivalConfig) -> None:
    """The belief the filter builds cannot claim a measured rival battery."""
    filter_ = _filter(rival_config)
    _drive(filter_, 0.5, steps=10)
    belief = filter_.to_belief(
        slot="ahead_1",
        is_ahead=True,
        now_s=filter_.time_s,
        gap_s=0.6,
        gap_m=45.0,
        relative_speed_mps=0.5,
        reference_speed_mps=75.0,
    )
    assert belief.energy_mean_j is not None
    assert belief.energy_mean_j.provenance is Provenance.ESTIMATED
    assert belief.energy_interval_j is not None
    assert belief.energy_interval_j.kind == "quantile"
    assert belief.energy_interval_j.coverage == pytest.approx(rival_config.quantiles.interval_coverage.value)


# -- ambiguity ------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 99, 4242, 20260908])
def test_observationally_similar_behaviours_stay_ambiguous(rival_config: RivalConfig, seed: int) -> None:
    """attack and defend produce the same pace, so both must keep the same weight.

    A sustained positive pace offset is evidence of *deploying*, not of a
    particular reason for deploying. At zero pressure the two modes have
    identical signatures, so the only honest posterior is one that separates them
    no further than the transition prior does.

    Parametrised over seeds on purpose: an earlier implementation that counted
    sampled modes passed at one seed and collapsed to a 47:1 split at another.
    Preserving ambiguity has to be a property of the filter, not of a lucky draw.
    """
    filter_ = _filter(rival_config, seed=seed)
    _drive(filter_, gap_rate_mps=1.55, steps=60, dt_s=0.5)
    weights = filter_.intention_weights()

    fast_modes = weights.attack + weights.defend
    assert fast_modes > 0.5, f"the fast modes should dominate, got {weights!r}"
    ratio = min(weights.attack, weights.defend) / max(weights.attack, weights.defend)
    assert ratio > 0.8, (
        "attack and defend are observationally degenerate on pace alone and must not "
        f"resolve; got attack={weights.attack:.4f} defend={weights.defend:.4f}"
    )


def test_context_pressure_does_not_manufacture_certainty(rival_config: RivalConfig) -> None:
    """Even the contextual term leaves attack and defend close together.

    Pressure is the only signal that separates them at all, and it separates them
    weakly: the per-particle pace bias -- tyre, aero and engine ambiguity -- can
    absorb most of a 0.3 m/s difference in predicted pace. So this asserts what is
    actually true rather than a directional claim the evidence cannot support:
    with a car right behind the rival, both fast modes still hold substantial,
    nearly equal weight.
    """
    unpressured = _filter(rival_config, seed=777)
    pressured = _filter(rival_config, seed=777)
    _drive(unpressured, gap_rate_mps=2.0, steps=40, context=RivalContext(is_ahead=True, pressure=0.0))
    _drive(pressured, gap_rate_mps=2.0, steps=40, context=RivalContext(is_ahead=True, pressure=1.0))

    flat = unpressured.intention_weights()
    leaning = pressured.intention_weights()
    assert abs(flat.attack - flat.defend) < 0.05, "at zero pressure the modes are degenerate"
    assert abs(leaning.attack - leaning.defend) < 0.2, (
        "pressure must not turn a weak contextual hint into a confident intention; "
        f"got attack={leaning.attack:.4f} defend={leaning.defend:.4f}"
    )
    assert min(leaning.attack, leaning.defend) > 0.2


def test_battery_uncertainty_does_not_collapse_because_acceleration_is_observed(
    rival_config: RivalConfig,
) -> None:
    """Watching a rival deploy identifies 'not nearly empty' and nothing more.

    The pace gain saturates above ``deploy_reference_energy_j``, so a long run of
    fast observations must leave the upper part of the energy posterior almost
    untouched.
    """
    filter_ = _filter(rival_config)
    prior_lower, prior_upper = filter_.energy_quantiles()
    prior_width = prior_upper - prior_lower

    _drive(filter_, gap_rate_mps=1.6, steps=6, dt_s=0.5)

    lower, upper = filter_.energy_quantiles()
    width = upper - lower
    reference = rival_config.dynamics.deploy_reference_energy_j.value
    assert width > 0.5 * prior_width, (
        f"energy posterior collapsed from {prior_width:.0f} J to {width:.0f} J on pace evidence alone"
    )
    assert upper > 2.0 * reference, "the saturated upper range must remain supported"


def test_pace_ambiguity_is_absorbed_by_the_pace_bias_not_by_energy(rival_config: RivalConfig) -> None:
    """A rival that is simply fast should move the pace bias, not empty its battery."""
    filter_ = _filter(rival_config)
    _, prior_sigma = filter_.energy_mean()
    _drive(filter_, gap_rate_mps=0.6, steps=30, dt_s=0.5)
    pace_mean, _ = filter_.pace_bias()
    _, sigma = filter_.energy_mean()
    assert pace_mean > 0.0, "sustained closing pace must shift the pace bias positive"
    assert sigma > 0.4 * prior_sigma


# -- resampling -----------------------------------------------------------


def test_effective_sample_size_matches_its_definition() -> None:
    uniform = np.full(8, 1.0 / 8.0)
    assert effective_sample_size(uniform) == pytest.approx(8.0)
    degenerate = np.zeros(8)
    degenerate[0] = 1.0
    assert effective_sample_size(degenerate) == pytest.approx(1.0)
    half = np.array([0.5, 0.5, 0.0, 0.0])
    assert effective_sample_size(half) == pytest.approx(2.0)


def test_log_sum_exp_normalisation_is_stable_at_extreme_log_weights() -> None:
    log_weights = np.array([-10_000.0, -10_001.0, -10_002.0, -20_000.0])
    weights = normalise_log_weights(log_weights)
    assert weights.sum() == pytest.approx(1.0)
    assert np.all(np.isfinite(weights))
    expected = np.exp(np.array([0.0, -1.0, -2.0, -10_000.0]))
    assert weights == pytest.approx(expected / expected.sum(), rel=1e-9)


def test_systematic_resampling_selects_proportionally() -> None:
    weights = np.array([0.1, 0.6, 0.3])
    indices = systematic_resample(weights, 0.5)
    counts = np.bincount(indices, minlength=3)
    assert counts.sum() == 3
    assert counts[1] >= counts[2] >= counts[0]


def test_resampling_fires_exactly_at_the_documented_ess_threshold(rival_config: RivalConfig) -> None:
    """``last_resampled`` is True on exactly the updates where ESS < fraction * N."""
    filter_ = _filter(rival_config)
    threshold = rival_config.filter.ess_resample_fraction.value * filter_.particles.size
    assert threshold == pytest.approx(64.0)

    observed = []
    gap = 40.0
    time_s = 0.0
    for step in range(30):
        time_s += 0.5
        # Alternate between mild and very informative observations so both
        # branches of the threshold are exercised in one run.
        gap += (2.4 if step % 5 == 0 else 0.2) * 0.5
        filter_.update(
            RivalObservation(session_time_s=time_s, gap_m=gap, gap_sigma_m=PRECISE_GAP_SIGMA_M),
            _own(),
            RivalContext(is_ahead=True),
        )
        observed.append((filter_.diagnostics.last_ess, filter_.diagnostics.last_resampled))

    assert any(resampled for _, resampled in observed), "the run must actually trigger resampling"
    assert any(not resampled for _, resampled in observed), "the run must also leave it untriggered"
    for ess, resampled in observed:
        assert resampled == (ess < threshold), f"ESS {ess:.4f} vs threshold {threshold}"


def test_resampling_preserves_the_legal_energy_range(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config)
    _drive(filter_, gap_rate_mps=2.0, steps=80, dt_s=0.5)
    energies = filter_.particles.energy_j
    assert float(np.min(energies)) >= rival_config.dynamics.energy_min_j.value
    assert float(np.max(energies)) <= rival_config.dynamics.energy_max_j.value
    assert filter_.diagnostics.resamples > 0


# -- the support floor ----------------------------------------------------


def test_the_weight_floor_prevents_irreversible_mode_collapse(rival_config: RivalConfig) -> None:
    """Drive hard toward one mode, then contradict it, and require recovery.

    Without the floor, a long run of one-sided evidence drives a mode's weight to
    numerical zero, resampling deletes its particles, and no later evidence can
    bring it back. This test is the reason both floors exist.
    """
    filter_ = _filter(rival_config)
    floor = rival_config.filter.mode_weight_floor.value

    # Phase 1: a long, strongly attacking rival.
    _drive(filter_, gap_rate_mps=1.7, steps=40, dt_s=0.5)
    after_attack = filter_.intention_weights()
    assert after_attack.attack + after_attack.defend > 0.6
    assert after_attack.conserve >= floor * 0.999, (
        f"conserve was driven below the declared floor: {after_attack.conserve:.6f}"
    )
    counts = np.bincount(filter_.particles.mode, minlength=len(MODE_ORDER))
    assert int(np.min(counts)) >= rival_config.filter.min_per_mode

    # Phase 2: the rival abruptly starts conserving.
    _drive(filter_, gap_rate_mps=-1.2, steps=40, dt_s=0.5)
    after_conserve = filter_.intention_weights()
    assert after_conserve.conserve > after_attack.conserve * 5.0
    assert after_conserve.conserve > 0.5, (
        f"the filter failed to recover the contradicted mode: {after_conserve!r}"
    )


def test_every_mode_keeps_nonzero_support_throughout_a_long_run(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config)
    minimum_seen = 1.0
    for block in range(8):
        _drive(filter_, gap_rate_mps=1.8 if block % 2 == 0 else -1.4, steps=20, dt_s=0.5)
        weights = filter_.intention_weights()
        minimum_seen = min(minimum_seen, weights.conserve, weights.normal, weights.attack, weights.defend)
    floor = rival_config.filter.mode_weight_floor.value
    assert minimum_seen >= floor * 0.999, f"a mode fell to {minimum_seen:.8f}"


# -- snapshot and restore -------------------------------------------------


def test_snapshot_then_restore_reproduces_the_exact_particle_sequence(rival_config: RivalConfig) -> None:
    """The restored filter must produce the identical subsequent particle arrays.

    Not statistically identical: bit-for-bit, including the RNG stream that drives
    resampling, so a replay from a checkpoint is the same run.
    """
    filter_ = _filter(rival_config, seed=1234)
    _drive(filter_, gap_rate_mps=1.1, steps=15, dt_s=0.4)
    snapshot = filter_.snapshot()

    def continue_run(target: RivalParticleFilter) -> list[np.ndarray]:
        trace: list[np.ndarray] = []
        gap = 60.0
        time_s = target.time_s
        for step in range(25):
            time_s += 0.4
            gap += (1.3 if step % 3 else -0.9) * 0.4
            target.update(
                RivalObservation(session_time_s=time_s, gap_m=gap, rival_speed_mps=76.0),
                _own(),
                RivalContext(is_ahead=True, pressure=0.2),
            )
            trace.append(
                np.concatenate(
                    [
                        target.particles.energy_j,
                        target.particles.pace_bias_mps,
                        target.particles.mode.astype(np.float64),
                        target.particles.mode_age_s,
                        target.particles.log_weight,
                    ]
                )
            )
        return trace

    original = continue_run(filter_)

    restored = RivalParticleFilter(rival_config, car_id=RIVAL_CAR_ID, seed=1234)
    restored.restore(snapshot)
    replayed = continue_run(restored)

    assert len(original) == len(replayed)
    for index, (left, right) in enumerate(zip(original, replayed, strict=True)):
        assert np.array_equal(left, right), f"particle state diverged at step {index}"
    assert restored.observation_history == filter_.observation_history
    assert restored.diagnostics.resamples == filter_.diagnostics.resamples


def test_the_whole_estimator_state_round_trips(own_config: OwnCarConfig, rival_config: RivalConfig) -> None:
    run = make_run(own_config, rival_config, scenario_id="round-trip", seed=71, duration_s=8.0)
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=17, own_config=own_config, rival_config=rival_config
    )
    first = update(run.events_until(4.0), state, make_context(4.0))
    snapshot = state.snapshot()

    tail = tuple(e for e in run.events if 4.0 < e.source_time_s <= 8.0)
    direct = update(tail, state, make_context(8.0))

    restored = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=17, own_config=own_config, rival_config=rival_config
    )
    restored.restore(snapshot)
    replayed = update(tail, restored, make_context(8.0))

    assert first.revision == 1
    assert direct.canonical_json() == replayed.canonical_json()


# -- own-state uncertainty ------------------------------------------------


def test_own_state_uncertainty_widens_the_rival_likelihood(rival_config: RivalConfig) -> None:
    """A poorly observed own car must make rival beliefs wider, not falsely sharp."""
    context = RivalContext(is_ahead=True)
    confident = RivalParticleFilter(rival_config, car_id=RIVAL_CAR_ID, seed=5)
    unsure = RivalParticleFilter(rival_config, car_id=RIVAL_CAR_ID, seed=5)

    sharp_own = OwnStateSummary(speed_mps=75.0, speed_variance=0.01)
    vague_own = OwnStateSummary(speed_mps=75.0, speed_variance=4.0)

    assert unsure.observation_variance(0.3, vague_own, context) > confident.observation_variance(
        0.3, sharp_own, context
    )

    gap = 40.0
    time_s = 0.0
    for _ in range(20):
        time_s += 0.5
        gap += 1.4 * 0.5
        observation = RivalObservation(session_time_s=time_s, gap_m=gap, gap_sigma_m=PRECISE_GAP_SIGMA_M)
        confident.update(observation, sharp_own, context)
        unsure.update(observation, vague_own, context)

    confident_weights = confident.intention_weights()
    unsure_weights = unsure.intention_weights()
    confident_peak = max(
        confident_weights.conserve,
        confident_weights.normal,
        confident_weights.attack,
        confident_weights.defend,
    )
    unsure_peak = max(
        unsure_weights.conserve, unsure_weights.normal, unsure_weights.attack, unsure_weights.defend
    )
    assert unsure_peak < confident_peak


def test_a_dropout_widens_the_likelihood_variance(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config)
    own = _own()
    quiet = filter_.observation_variance(0.3, own, RivalContext(dropout_s=0.0))
    lost = filter_.observation_variance(0.3, own, RivalContext(dropout_s=3.0))
    growth = rival_config.likelihood.dropout_variance_growth_per_s.value
    assert lost - quiet == pytest.approx(3.0 * growth, rel=1e-12)


def test_the_transition_matrix_declares_a_hand_authored_prior(rival_config: RivalConfig) -> None:
    """The manifest must say the matrix is a prior, not something that was fitted."""
    assert rival_config.transition_matrix_authorship == "hand_authored_prior"
    assert rival_config.is_hand_authored is True
    assert "No data was fitted" in rival_config.transition_matrix_note
    matrix = rival_config.unit_transition
    assert matrix.shape == (4, 4)
    assert np.allclose(matrix.sum(axis=1), 1.0)
    for dt in (0.0, 0.1, 6.0, 600.0):
        stepped = rival_config.step_transition(dt)
        assert np.allclose(stepped.sum(axis=1), 1.0)
        assert float(np.min(stepped)) >= 0.0
    assert np.allclose(rival_config.step_transition(0.0), np.eye(4))


def test_mode_memory_resets_only_when_the_mode_changes(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config, seed=808)
    before_mode = filter_.particles.mode.copy()
    before_age = filter_.particles.mode_age_s.copy()
    filter_.propagate(0.4, RivalContext())
    changed = filter_.particles.mode != before_mode
    assert bool(np.any(changed)), "some particle should change mode over 0.4 s"
    assert np.allclose(filter_.particles.mode_age_s[changed], 0.0)
    assert np.allclose(filter_.particles.mode_age_s[~changed], before_age[~changed] + 0.4)


def test_the_filter_refuses_an_observation_before_its_own_state_time(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config)
    _drive(filter_, 0.5, steps=4)
    with pytest.raises(ValueError, match="earlier than the filter state"):
        filter_.update(RivalObservation(session_time_s=0.1, gap_m=10.0), _own(), RivalContext())


def test_energy_quantile_interval_brackets_the_weighted_mean(rival_config: RivalConfig) -> None:
    filter_ = _filter(rival_config)
    _drive(filter_, 0.9, steps=25)
    lower, upper = filter_.energy_quantiles()
    mean, sigma = filter_.energy_mean()
    assert lower < mean < upper
    assert sigma > 0.0
    assert math.isfinite(sigma)
