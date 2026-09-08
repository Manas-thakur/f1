"""Battery observability gates energy capability.

The rule under test is the one that decides whether this software may give
precise energy advice at all. It is not a display nicety: a fabricated point
value here becomes an energy recommendation downstream.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import (
    IntervalValue,
    Quality,
    ScalarValue,
    SessionMode,
    SourceCapability,
    StateEstimate,
)
from afterlap_core.estimation import (
    OwnCarConfig,
    RivalConfig,
    create_state,
    update,
)

from .conftest import (
    OWN_CAR_ID,
    SESSION_ID,
    SYNTHETIC_NOTICE,
    make_context,
    make_run,
)


def _partial_capability() -> SourceCapability:
    """A source that measures DC-bus power but cannot see battery state.

    This is the realistic partial case: the power trace exists, the absolute
    state of charge does not, and no amount of integration recovers the constant
    of integration.
    """
    channels = ("speed_mps", "progress_m", "electrical_power_w")
    return SourceCapability(
        source_id="partial-source",
        mode=SessionMode.SIMULATION,
        supported_channels=channels,
        measured_channels=channels,
        update_rates_hz=dict.fromkeys(channels, 20.0),
        clock_error_s=0.0,
        limitations=(
            SYNTHETIC_NOTICE,
            "no battery-energy channel; absolute state of charge is unobservable",
        ),
    )


def _scalars(estimate: StateEstimate) -> list[tuple[str, ScalarValue]]:
    found: list[tuple[str, ScalarValue]] = []
    own = estimate.own_car
    for name in (
        "progress_m",
        "lap_distance_m",
        "speed_mps",
        "acceleration_mps2",
        "battery_energy_j",
        "battery_temperature_k",
        "electrical_power_w",
        "recharge_spent_this_lap_j",
    ):
        found.append((f"own_car.{name}", getattr(own, name)))
    found.append(("race_context.remaining_distance_m", estimate.race_context.remaining_distance_m))
    for belief in estimate.rival_beliefs:
        for name in ("gap_s", "gap_m", "relative_speed_mps", "energy_mean_j", "pace_bias_s_per_lap"):
            value = getattr(belief, name)
            if value is not None:
                found.append((f"{belief.slot}.{name}", value))
    return found


def test_no_energy_channel_closes_capability_and_reports_an_explicit_gap(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Missing energy: null value, missing quality, physical bounds, capability False."""
    run = make_run(
        own_config, rival_config, scenario_id="no-energy", seed=31, duration_s=6.0, energy_channel=False
    )
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=2, own_config=own_config, rival_config=rival_config
    )
    estimate = update(run.events, state, make_context(6.0, with_energy=False))

    energy = estimate.own_car.battery_energy_j
    assert energy.value is None
    assert energy.quality is Quality.MISSING

    interval = estimate.own_car.battery_energy_interval
    assert isinstance(interval, IntervalValue)
    assert interval.kind == "physical_bounds"
    assert interval.coverage is None, "a support range must never claim statistical coverage"
    assert interval.lower == pytest.approx(own_config.energy.physical_min_j.value)
    assert interval.upper == pytest.approx(own_config.energy.physical_max_j.value)

    assert estimate.quality.own_energy_capability is False
    assert estimate.own_car.has_energy_capability is False
    assert any("own_energy_capability is False" in note for note in estimate.quality.notes)


def test_partial_energy_information_yields_an_interval_and_never_a_point_value(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Integrated power narrows the reachable set from one side and stops there.

    Deployment only drains, so the top of the window becomes unreachable while
    the bottom does not move. That is a real narrowing and it is still not a
    point value.
    """
    run = make_run(own_config, rival_config, scenario_id="partial-energy", seed=37, duration_s=8.0)
    # The battery-state samples exist in the feed but the source does not declare
    # the channel measured, so they must not open capability.
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=3, own_config=own_config, rival_config=rival_config
    )
    context = make_context(8.0, source_capability=_partial_capability())
    estimate = update(run.events, state, context)

    energy = estimate.own_car.battery_energy_j
    assert energy.value is None
    assert energy.quality is Quality.MISSING
    assert estimate.quality.own_energy_capability is False

    interval = estimate.own_car.battery_energy_interval
    assert interval is not None
    assert interval.kind == "physical_bounds"
    window = own_config.energy.physical_max_j.value - own_config.energy.physical_min_j.value
    assert interval.width is not None
    assert interval.width < window, "integrated power must narrow the reachable set"
    assert interval.width > 0.25 * window, "a reachable set must not masquerade as a point value"
    assert state.own.state.energy.integrated_seconds > 0.0
    assert any("reachable set" in note for note in estimate.quality.notes)


def test_a_battery_channel_the_source_does_not_measure_cannot_open_capability(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Supported is not measured; only a measured channel gates the claim."""
    run = make_run(own_config, rival_config, scenario_id="supported-only", seed=41, duration_s=4.0)
    channels = ("speed_mps", "progress_m", "electrical_power_w", "battery_energy_j")
    declared = SourceCapability(
        source_id="modelled-energy",
        mode=SessionMode.SIMULATION,
        supported_channels=channels,
        measured_channels=("speed_mps", "progress_m", "electrical_power_w"),
        update_rates_hz=dict.fromkeys(channels, 20.0),
        clock_error_s=0.0,
        limitations=(SYNTHETIC_NOTICE, "battery_energy_j is modelled, not measured"),
    )
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=4, own_config=own_config, rival_config=rival_config
    )
    estimate = update(run.events, state, make_context(4.0, source_capability=declared))
    assert estimate.quality.own_energy_capability is False
    assert estimate.own_car.battery_energy_j.value is None
    assert any("does not declare measured" in note for note in estimate.quality.notes)


def test_a_measured_energy_channel_opens_capability(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """The positive control: the same code path does report capability when it should."""
    run = make_run(own_config, rival_config, scenario_id="with-energy", seed=43, duration_s=6.0)
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=5, own_config=own_config, rival_config=rival_config
    )
    estimate = update(run.events, state, make_context(6.0))
    assert estimate.quality.own_energy_capability is True
    assert estimate.own_car.battery_energy_j.value is not None
    assert estimate.own_car.battery_energy_interval is None
    assert estimate.own_car.has_energy_capability is True


@pytest.mark.parametrize(
    ("scenario", "energy_channel", "partial"),
    [
        ("full", True, False),
        ("none", False, False),
        ("partial", True, True),
    ],
)
def test_no_unknown_quantity_is_ever_reported_valid(
    own_config: OwnCarConfig,
    rival_config: RivalConfig,
    scenario: str,
    energy_channel: bool,
    partial: bool,
) -> None:
    """No ``ScalarValue`` in a published estimate has a null value and quality=valid.

    The contract refuses that combination. This asserts the estimator never even
    tries: the code is checked, not the exception.
    """
    run = make_run(
        own_config,
        rival_config,
        scenario_id=f"quality-{scenario}",
        seed=47,
        duration_s=6.0,
        energy_channel=energy_channel,
    )
    context = (
        make_context(6.0, source_capability=_partial_capability())
        if partial
        else make_context(6.0, with_energy=energy_channel)
    )
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=6, own_config=own_config, rival_config=rival_config
    )
    estimate = update(run.events, state, context)

    for name, value in _scalars(estimate):
        if value.value is None:
            assert value.quality in (Quality.MISSING, Quality.INVALID), name
        else:
            assert value.quality is not Quality.MISSING, name

    interval = estimate.own_car.battery_energy_interval
    if interval is not None:
        assert interval.kind == "physical_bounds"
        assert interval.coverage is None
    for belief in estimate.rival_beliefs:
        assert belief.energy_interval_j is not None
        assert belief.energy_interval_j.kind == "quantile"
        assert belief.energy_interval_j.coverage == pytest.approx(
            rival_config.quantiles.interval_coverage.value
        )


def test_energy_capability_survives_a_snapshot_and_restore(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """A replayed session must not silently regain or lose energy capability."""
    run = make_run(
        own_config, rival_config, scenario_id="restore", seed=53, duration_s=5.0, energy_channel=False
    )
    state = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=7, own_config=own_config, rival_config=rival_config
    )
    first = update(run.events, state, make_context(5.0, with_energy=False))
    snapshot = state.snapshot()

    restored = create_state(
        session_id=SESSION_ID, car_id=OWN_CAR_ID, seed=7, own_config=own_config, rival_config=rival_config
    )
    restored.restore(snapshot)
    assert restored.own.state.energy.initialised is False
    second = update((), restored, make_context(5.0, with_energy=False))
    assert second.quality.own_energy_capability is first.quality.own_energy_capability
    assert second.own_car.battery_energy_j.value is None
