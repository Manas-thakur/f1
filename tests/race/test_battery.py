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


def test_bms_profile_applies_over_a_direct_driver_control():
    session = RaceSession(RaceSettings(cars=1))
    session.control("car-01", DriverAction(profile=DeploymentProfile.CONSERVE, throttle=1, brake=0))
    session.bms_profiles["car-01"] = DeploymentProfile.OVERTAKE
    session.advance(0.5)
    assert session.simulator.world.cars["car-01"].active_profile is DeploymentProfile.OVERTAKE


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
