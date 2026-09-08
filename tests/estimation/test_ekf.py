"""Numerical validation of the own-car extended Kalman filter.

The Jacobian test is the one that actually validates the linearisation: an EKF
whose Jacobian disagrees with its own transition function propagates a covariance
that means nothing, and no downstream interval built on it can be trusted.
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest

from afterlap_contracts import SCHEMA_VERSION, Provenance, Quality, TelemetryEvent
from afterlap_core.estimation import (
    STATE_ACCELERATION,
    STATE_ENERGY,
    STATE_PROGRESS,
    STATE_SPEED,
    MotionModel,
    OwnCarConfig,
    OwnCarFilter,
    create_state,
    update,
)

from .conftest import OWN_CAR_ID, SESSION_ID, SyntheticRun, make_context


def _event(sequence: int, channel: str, value: float, unit: str, source_time_s: float) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"hand-{channel}-{sequence:04d}",
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        sequence=sequence,
        source_time_s=source_time_s,
        received_time_s=source_time_s + 0.01,
        channel=channel,
        value=value,
        unit=unit,
        provenance=Provenance.SIMULATED,
        quality=Quality.VALID,
    )


# -- the linearisation ----------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        (0.0, 75.0, 0.0, 2_400_000.0),
        (1_950.0, 62.5, -4.2, 1_100_000.0),
        (12_300.0, 88.0, 6.5, 3_900_000.0),
        (400.0, 5.0, -12.0, 100_000.0),
        (0.0, 0.0, 0.0, 0.0),
    ],
)
@pytest.mark.parametrize("dt_s", [0.01, 0.05, 0.25])
def test_hand_written_jacobian_matches_central_difference(
    own_config: OwnCarConfig, state: tuple[float, ...], dt_s: float
) -> None:
    """The analytic Jacobian must equal a central finite difference.

    The tolerance is stated rather than tuned to pass: a central difference has
    error O(h^2 * f''') and the states span the full speed range, so 1e-6
    absolute on entries of order 1 is a genuine agreement claim.
    """
    model = MotionModel(
        acceleration_time_constant_s=own_config.motion.acceleration_time_constant_s.value,
        drag_per_m=own_config.motion.drag_per_m.value,
    )
    x = np.array(state, dtype=np.float64)
    analytic = model.jacobian(x, dt_s)

    numeric = np.zeros_like(analytic)
    for column in range(x.size):
        # Scaled step: a 1e-4 absolute step on a 12000 m progress value would be
        # swallowed by float64 round-off, so the step follows the magnitude.
        step = 1e-5 * max(1.0, abs(float(x[column])))
        forward = x.copy()
        backward = x.copy()
        forward[column] += step
        backward[column] -= step
        numeric[:, column] = (model.step(forward, dt_s) - model.step(backward, dt_s)) / (2.0 * step)

    assert np.allclose(analytic, numeric, rtol=1e-6, atol=1e-6), (
        f"analytic\n{analytic}\nnumeric\n{numeric}\ndifference\n{analytic - numeric}"
    )


def test_jacobian_captures_the_drag_nonlinearity(own_config: OwnCarConfig) -> None:
    """The off-diagonal acceleration/speed entry is the nonlinearity itself."""
    model = MotionModel(
        acceleration_time_constant_s=own_config.motion.acceleration_time_constant_s.value,
        drag_per_m=own_config.motion.drag_per_m.value,
    )
    slow = model.jacobian(np.array([0.0, 10.0, 0.0, 0.0]), 0.05)
    fast = model.jacobian(np.array([0.0, 90.0, 0.0, 0.0]), 0.05)
    assert slow[STATE_ACCELERATION, STATE_SPEED] < 0.0
    assert fast[STATE_ACCELERATION, STATE_SPEED] < slow[STATE_ACCELERATION, STATE_SPEED]
    # d a'/d v is exactly -2 k v (1 - alpha); check the ratio, which removes alpha.
    assert fast[STATE_ACCELERATION, STATE_SPEED] / slow[STATE_ACCELERATION, STATE_SPEED] == pytest.approx(
        9.0, rel=1e-12
    )


# -- covariance behaviour -------------------------------------------------


def test_covariance_grows_monotonically_under_pure_prediction(own_config: OwnCarConfig) -> None:
    """With no measurements every state variance must increase, step after step."""
    filter_ = OwnCarFilter(own_config)
    filter_.state.mean = np.array([0.0, 75.0, 0.0, 2_400_000.0], dtype=np.float64)
    filter_.state.covariance = np.diag(np.array([1.0, 0.04, 0.05, 1.0e6], dtype=np.float64))
    filter_.state.started = True
    filter_.state.energy.initialised = True

    diagonals = [filter_.state.covariance.diagonal().copy()]
    traces = [float(np.trace(filter_.state.covariance))]
    for step in range(1, 41):
        filter_.predict_to(step * 0.1, clock_uncertainty_s=0.0, power_w=0.0)
        diagonals.append(filter_.state.covariance.diagonal().copy())
        traces.append(float(np.trace(filter_.state.covariance)))

    for index, name in (
        (STATE_PROGRESS, "progress"),
        (STATE_SPEED, "speed"),
        (STATE_ACCELERATION, "acceleration"),
        (STATE_ENERGY, "energy"),
    ):
        series = [float(d[index]) for d in diagonals]
        for previous, current in pairwise(series):
            assert current > previous, f"{name} variance did not grow: {previous} -> {current}"
    for previous, current in pairwise(traces):
        assert current > previous


def test_prediction_covariance_grows_with_clock_uncertainty(own_config: OwnCarConfig) -> None:
    """An uncertain elapsed time is an uncertain distance travelled."""
    variances = []
    for clock_sigma in (0.0, 0.02, 0.10):
        filter_ = OwnCarFilter(own_config)
        filter_.state.mean = np.array([0.0, 75.0, 3.0, 2_400_000.0], dtype=np.float64)
        filter_.state.covariance = np.diag(np.array([1.0, 0.04, 0.05, 1.0e6], dtype=np.float64))
        filter_.state.started = True
        filter_.predict_to(1.0, clock_uncertainty_s=clock_sigma, power_w=0.0)
        variances.append(
            (
                float(filter_.state.covariance[STATE_PROGRESS, STATE_PROGRESS]),
                float(filter_.state.covariance[STATE_SPEED, STATE_SPEED]),
            )
        )
    assert variances[0][0] < variances[1][0] < variances[2][0]
    assert variances[0][1] < variances[1][1] < variances[2][1]


def test_a_measurement_reduces_the_corresponding_variance(own_config: OwnCarConfig) -> None:
    """Fusing a channel must shrink that channel's variance and nothing must blow up."""
    filter_ = OwnCarFilter(own_config)
    filter_.state.mean = np.array([100.0, 75.0, 0.5, 2_400_000.0], dtype=np.float64)
    filter_.state.covariance = np.diag(np.array([9.0, 4.0, 0.25, 1.0e8], dtype=np.float64))
    filter_.state.started = True
    filter_.state.energy.initialised = True
    context = make_context(1.0)

    before = filter_.state.covariance.diagonal().copy()
    observations = [
        ("speed_mps", 74.6, "m/s", STATE_SPEED),
        ("progress_m", 100.4, "m", STATE_PROGRESS),
        ("battery_energy_j", 2_390_000.0, "J", STATE_ENERGY),
    ]
    for channel, value, unit, index in observations:
        variance_before = float(filter_.state.covariance[index, index])
        filter_._apply(  # exercising one correction in isolation
            _observation(channel, value, unit, 1.0),
            context,
            0.0,
        )
        variance_after = float(filter_.state.covariance[index, index])
        assert variance_after < variance_before, channel

    after = filter_.state.covariance.diagonal()
    assert np.all(after <= before + 1e-9)
    eigenvalues = np.linalg.eigvalsh(filter_.state.covariance)
    assert float(np.min(eigenvalues)) >= -1e-6, "Joseph form must keep the covariance PSD"


def _observation(channel: str, value: float, unit: str, session_time_s: float):
    from afterlap_core.estimation import Observation

    return Observation(
        event_id=f"unit-{channel}",
        car_id=OWN_CAR_ID,
        channel=channel,
        value=value,
        unit=unit,
        session_time_s=session_time_s,
        source_time_s=session_time_s,
        provenance=Provenance.SIMULATED,
        quality=Quality.VALID,
    )


def test_clock_uncertainty_inflates_the_effective_measurement_noise(own_config: OwnCarConfig) -> None:
    """R grows with sigma_c, and it grows by the amount the model claims."""
    filter_ = OwnCarFilter(own_config)
    filter_.state.mean = np.array([0.0, 75.0, 3.0, 2_400_000.0], dtype=np.float64)

    base_progress = filter_.measurement_variance("progress_m", clock_uncertainty_s=0.0)
    inflated_progress = filter_.measurement_variance("progress_m", clock_uncertainty_s=0.02)
    assert inflated_progress > base_progress
    assert inflated_progress - base_progress == pytest.approx((75.0 * 0.02) ** 2, rel=1e-12)

    base_speed = filter_.measurement_variance("speed_mps", clock_uncertainty_s=0.0)
    inflated_speed = filter_.measurement_variance("speed_mps", clock_uncertainty_s=0.02)
    assert inflated_speed - base_speed == pytest.approx((3.0 * 0.02) ** 2, rel=1e-12)

    # And the inflation is monotone in sigma_c, never a narrowing.
    previous = base_progress
    for sigma in (0.01, 0.05, 0.2):
        current = filter_.measurement_variance("progress_m", clock_uncertainty_s=sigma)
        assert current > previous
        previous = current


def test_clock_uncertainty_leaves_a_wider_posterior(own_config: OwnCarConfig) -> None:
    """A noisier clock must leave the filter less certain after the same update."""
    posteriors = []
    for sigma in (0.0, 0.05):
        filter_ = OwnCarFilter(own_config)
        filter_.state.mean = np.array([100.0, 75.0, 3.0, 2_400_000.0], dtype=np.float64)
        filter_.state.covariance = np.diag(np.array([9.0, 4.0, 0.25, 1.0e8], dtype=np.float64))
        filter_.state.started = True
        filter_._apply(_observation("progress_m", 100.5, "m", 1.0), make_context(1.0), sigma)
        posteriors.append(float(filter_.state.covariance[STATE_PROGRESS, STATE_PROGRESS]))
    assert posteriors[1] > posteriors[0]


# -- causality ------------------------------------------------------------


def test_an_observation_after_the_cutoff_is_rejected_and_changes_nothing(
    matched_run: SyntheticRun, own_config, rival_config
) -> None:
    """A late-timestamped event must not alter the published estimate at all.

    Not "must not alter it much": the estimate is compared by canonical JSON, so
    a single differing digit or a differing note fails.
    """
    cutoff_s = 8.0
    on_time = matched_run.events_until(cutoff_s)
    future = tuple(event for event in matched_run.events if event.source_time_s > cutoff_s)
    assert future, "the fixture must actually contain post-cutoff events"

    clean_state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=5, own_config=own_config, rival_config=rival_config
    )
    contaminated_state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=5, own_config=own_config, rival_config=rival_config
    )
    context = make_context(cutoff_s)

    clean = update(on_time, clean_state, context)
    contaminated = update(on_time + future, contaminated_state, context)

    assert contaminated.canonical_json() == clean.canonical_json()
    assert clean_state.rejected == []
    assert len(contaminated_state.rejected) == len(future)
    assert all("later than the decision cutoff" in r.reason for r in contaminated_state.rejected)
    rejected_ids = {r.event_id for r in contaminated_state.rejected}
    assert rejected_ids.isdisjoint(set(contaminated.contributing_event_ids))


def test_ingesting_an_observation_past_the_cutoff_raises(own_config: OwnCarConfig) -> None:
    """The filter itself refuses a future observation, so there is no second path in."""
    filter_ = OwnCarFilter(own_config)
    filter_.state.started = True
    filter_.state.time_s = 0.0
    with pytest.raises(ValueError, match="after the cutoff"):
        filter_.ingest([_observation("speed_mps", 70.0, "m/s", 5.0)], make_context(1.0))


def test_the_filter_never_predicts_backwards(own_config: OwnCarConfig) -> None:
    filter_ = OwnCarFilter(own_config)
    filter_.state.time_s = 5.0
    with pytest.raises(ValueError, match="predict backwards"):
        filter_.predict_to(4.0)


# -- energy integration ---------------------------------------------------


def test_energy_integrates_measured_power_over_a_hand_computed_interval(
    own_config: OwnCarConfig, rival_config
) -> None:
    """100 kW deployed for 2.0 s must take exactly 200 kJ out of a 2.4 MJ battery.

    Hand computation: dE = -P * dt = -100000 W * 2.0 s = -200000 J, so
    2400000 - 200000 = 2200000 J. The filter subdivides the interval into eight
    250 ms linearisation steps; the sum must still be the analytic value.
    """
    events = [
        _event(1, "battery_energy_j", 2_400_000.0, "J", 0.0),
        _event(2, "electrical_power_w", 100_000.0, "W", 0.0),
        _event(3, "speed_mps", 75.0, "m/s", 0.0),
        _event(4, "progress_m", 0.0, "m", 0.0),
    ]
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=1, own_config=own_config, rival_config=rival_config
    )
    estimate = update(events, state, make_context(2.0, rival_car_ids=()))
    assert estimate.own_car.battery_energy_j.value == pytest.approx(2_200_000.0, abs=1e-6)
    assert state.own.state.energy.delta_j == pytest.approx(-200_000.0, abs=1e-6)


def test_harvesting_energy_credits_the_battery_at_the_declared_efficiency(
    own_config: OwnCarConfig, rival_config
) -> None:
    """Harvest is not the mirror of deployment: only eta of the bus energy lands.

    Hand computation: -100 kW for 2.0 s is 200 kJ off the DC bus, and at
    eta = 0.92 the battery gains 184000 J, reaching 2584000 J.
    """
    eta = own_config.energy.harvest_efficiency.value
    assert eta == pytest.approx(0.92)
    events = [
        _event(1, "battery_energy_j", 2_400_000.0, "J", 0.0),
        _event(2, "electrical_power_w", -100_000.0, "W", 0.0),
        _event(3, "speed_mps", 75.0, "m/s", 0.0),
    ]
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=1, own_config=own_config, rival_config=rival_config
    )
    estimate = update(events, state, make_context(2.0, rival_car_ids=()))
    assert estimate.own_car.battery_energy_j.value == pytest.approx(2_584_000.0, abs=1e-6)


def test_a_battery_measurement_corrects_the_integrated_energy(own_config: OwnCarConfig, rival_config) -> None:
    """A later battery reading pulls the integral back and shrinks its variance."""
    events = [
        _event(1, "battery_energy_j", 2_400_000.0, "J", 0.0),
        _event(2, "electrical_power_w", 100_000.0, "W", 0.0),
        _event(3, "speed_mps", 75.0, "m/s", 0.0),
        _event(4, "battery_energy_j", 2_150_000.0, "J", 2.0),
    ]
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=1, own_config=own_config, rival_config=rival_config
    )
    estimate = update(events, state, make_context(2.0, rival_car_ids=()))
    value = estimate.own_car.battery_energy_j.value
    assert value is not None
    # The integral said 2200000, the measurement says 2150000; the posterior sits
    # strictly between the two and closer to whichever is more certain.
    assert 2_150_000.0 < value < 2_200_000.0
    assert state.own.state.energy.corrections == 1
    assert estimate.own_car.battery_energy_j.standard_deviation is not None
    assert estimate.own_car.battery_energy_j.standard_deviation < own_config.measurement.energy_sigma_j.value


def test_an_unobserved_integration_gap_widens_energy_uncertainty(
    own_config: OwnCarConfig, rival_config
) -> None:
    """A power-channel dropout must widen energy, not integrate as zero power."""
    events = [
        _event(1, "battery_energy_j", 2_400_000.0, "J", 0.0),
        _event(2, "electrical_power_w", 100_000.0, "W", 0.0),
        _event(3, "speed_mps", 75.0, "m/s", 0.0),
    ]
    sigmas = []
    for gap_s in (0.0, 1.5):
        state = create_state(
            session_id=SESSION_ID,
            car_id=OWN_CAR_ID,
            seed=1,
            own_config=own_config,
            rival_config=rival_config,
        )
        estimate = update(events, state, make_context(2.0, rival_car_ids=(), integration_gap_s=gap_s))
        sigma = estimate.own_car.battery_energy_j.standard_deviation
        assert sigma is not None
        sigmas.append(sigma)
    expected_extra = own_config.energy.unobserved_gap_sigma_w.value * 1.5
    assert sigmas[1] > sigmas[0]
    assert math.sqrt(sigmas[1] ** 2 - sigmas[0] ** 2) == pytest.approx(expected_extra, rel=1e-9)


def test_process_noise_is_positive_semi_definite(own_config: OwnCarConfig) -> None:
    filter_ = OwnCarFilter(own_config)
    state = np.array([1000.0, 75.0, 2.0, 2_400_000.0], dtype=np.float64)
    for dt in (0.001, 0.05, 0.25, 1.0):
        noise = filter_.process_noise(state, dt, clock_uncertainty_s=0.03, integration_gap_s=0.2)
        assert np.allclose(noise, noise.T)
        assert float(np.min(np.linalg.eigvalsh(noise))) >= -1e-12
