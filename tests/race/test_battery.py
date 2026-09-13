import json

import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.simulation.energy_limits import ElectricalLimits, EventEnergyLimits
from afterlap_core.simulation.policies import DriverAction


def test_2026_standard_curve_and_recharge_budget():
    session = RaceSession(RaceSettings(cars=1))
    car = session.bundle.car_configs["car-01"]
    limits = ElectricalLimits(car, EventEnergyLimits.race_2026(), 300, 1)
    for speed, expected in [(0, 350000), (290, 350000), (320, 200000), (340, 100000), (345, 0), (360, 0)]:
        assert limits.deploy_ceiling_dc_w(speed / 3.6) == pytest.approx(expected)
    assert limits.recharge_allowance_j() == 8500000


def test_boost_consumes_energy_and_replay_preserves_observed_duration():
    session = RaceSession(RaceSettings(cars=1))
    session.control("car-01", DriverAction(profile=DeploymentProfile.PUSH, throttle=1))
    initial = session.simulator.world.ledgers["car-01"].energy_j
    session.advance(2)
    snapshot = session.snapshot()
    session.advance(1)
    expected = session.frame()
    ch = expected["cars"][0]["channels"]
    assert ch["boost_active"] == 1
    assert 0 < ch["boost_elapsed_s"] <= expected["time_s"]
    assert ch["battery_energy_j"] < initial
    assert ch["deployed_cumulative_j"] > 0
    session.restore(snapshot)
    session.advance(1)
    assert session.frame() == expected
    json.loads(session.observations()["car-01"].canonical_bytes())
    assert abs(session.simulator.energy_close_errors()["car-01"]) < 1e-6


def test_recharge_stops_at_remaining_lap_allowance_and_never_adds_free_energy():
    session = RaceSession(RaceSettings(cars=1))
    ledger = session.simulator.world.ledgers["car-01"]
    ledger.recharge_this_lap_j = 8500000 - 50
    initial_harvest = ledger.harvested_dc_j
    session.control("car-01", DriverAction(profile=DeploymentProfile.HARVEST, throttle=0, brake=0.5))
    session.advance(0.5)
    assert ledger.harvested_dc_j - initial_harvest == pytest.approx(50)
    assert ledger.recharge_this_lap_j == pytest.approx(8500000)
    assert abs(ledger.close_error()) < 1e-6


def test_missing_and_delayed_boost_channels_do_not_expose_current_truth():
    session = RaceSession(RaceSettings(cars=2))
    assert "boost_active" not in session.frame()["cars"][0]["channels"]
    session.advance(0.2)
    observation = session.observations()["car-01"]
    previous = observation.get("boost_total_s")
    session.simulator.world.cars["car-01"].boost_total_s = 999
    assert session.observations()["car-01"].get("boost_total_s") == previous
    assert all("boost_total_s" not in rival for rival in observation.rivals)


def test_lap_accounting_resets_without_refilling_battery():
    session = RaceSession(RaceSettings(cars=1, laps=3))
    state = session.simulator.world.cars["car-01"]
    state.progress_m = session.track.length - 0.01
    state.s_m = state.progress_m
    state.deployed_this_lap_j = 12345
    state.boost_this_lap_s = 2
    initial = state.battery_energy_j
    session.advance(0.2)
    laps = session.frame()["cars"][0]["energy_laps"]
    assert len(laps) == 1
    assert laps[0]["lap"] == 1
    assert laps[0]["deployed_j"] >= 12345
    assert laps[0]["boost_s"] >= 2
    assert state.boost_this_lap_s < 0.2
    assert state.battery_energy_j <= initial


def test_automatic_multi_lap_boost_recovers_and_resumes():
    session = RaceSession(RaceSettings(cars=1, laps=3, circuit="monza"))
    while not session.done:
        session.advance(10)
    assert session.status == "finished"
    state = session.simulator.world.cars["car-01"]
    assert len(state.energy_laps) == 3
    assert all(lap["boost_s"] > 0 for lap in state.energy_laps)
    assert all(0 < lap["recharged_j"] <= 8500000 for lap in state.energy_laps)
    assert 0 <= state.battery_energy_j <= 4000000
    assert abs(session.simulator.energy_close_errors()["car-01"]) < 1e-5


def test_held_boost_stays_cut_after_depletion_until_the_driver_rearms_it():
    session = RaceSession(RaceSettings(cars=1))
    state = session.simulator.world.cars["car-01"]
    ledger = session.simulator.world.ledgers["car-01"]
    state.speed_mps = 40
    state.battery_energy_j = 80_000
    ledger.energy_j = 80_000
    ledger.initial_energy_j = 80_000
    boost = DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1, brake=0)
    session.control("car-01", boost)

    session.advance(1)
    assert ledger.energy_j == 0
    assert state.boost_latched == 1
    assert state.active_profile is DeploymentProfile.HARVEST
    assert state.deploy_power_dc_w == 0

    held_while_braking = DriverAction(
        profile=DeploymentProfile.OVERTAKE,
        throttle=0,
        brake=1,
    )
    session.control("car-01", held_while_braking)
    session.advance(0.5)
    recovered = ledger.energy_j
    assert recovered > 0
    assert state.boost_latched == 1
    assert state.active_profile is DeploymentProfile.HARVEST

    session.control("car-01", boost)
    session.advance(0.3)
    assert state.deploy_power_dc_w == 0
    assert state.boost_active == 0

    session.control(
        "car-01",
        DriverAction(profile=DeploymentProfile.HARVEST, throttle=0, brake=0),
    )
    session.advance(0.3)
    session.control("car-01", boost)
    session.advance(0.3)
    assert state.boost_latched == 0
    assert state.active_profile is DeploymentProfile.OVERTAKE
    assert state.deploy_power_dc_w > 0


def test_harder_braking_recovers_more_energy_until_the_generator_limit():
    def recovered(brake: float) -> float:
        session = RaceSession(RaceSettings(cars=1, variability={"preset": "baseline"}))
        state = session.simulator.world.cars["car-01"]
        ledger = session.simulator.world.ledgers["car-01"]
        state.speed_mps = 40
        state.battery_energy_j = 1_000_000
        ledger.energy_j = 1_000_000
        ledger.initial_energy_j = 1_000_000
        session.control(
            "car-01",
            DriverAction(profile=DeploymentProfile.HARVEST, throttle=0, brake=brake),
        )
        before = ledger.harvested_dc_j
        session.advance(0.5)
        return ledger.harvested_dc_j - before

    light = recovered(0.1)
    medium = recovered(0.3)
    hard = recovered(1.0)
    assert 0 < light < medium < hard
    assert hard <= 350_000 * 0.5


def test_standstill_boost_does_not_consume_propulsion_energy():
    session = RaceSession(RaceSettings(cars=1, variability={"preset": "baseline"}))
    state = session.simulator.world.cars["car-01"]
    ledger = session.simulator.world.ledgers["car-01"]
    state.speed_mps = 0
    session.control(
        "car-01",
        DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1, brake=0),
    )
    session.advance(0.5)
    assert state.deploy_power_dc_w == 0
    assert ledger.deployed_dc_j == 0
    assert ledger.auxiliary_j > 0


def test_race_start_charge_is_a_fixed_operating_target_not_vehicle_variability():
    first = RaceSession(RaceSettings(cars=5, seed=11))
    second = RaceSession(RaceSettings(cars=5, seed=91))
    first_energy = {state.energy_j.value for state in first.bundle.scenario.initial_states.values()}
    second_energy = {state.energy_j.value for state in second.bundle.scenario.initial_states.values()}
    assert first_energy == second_energy == {3_100_000}
