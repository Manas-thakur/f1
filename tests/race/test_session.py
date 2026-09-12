import math

import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.circuit import catalogue, circuit
from afterlap_core.simulation.policies import DriverAction


def test_all_circuits_have_periodic_metric_geometry():
    assert len(catalogue()) == 23
    for item in catalogue():
        track, artwork = circuit(item["id"])
        assert track.length == item["length_m"]
        assert not track.lateral_geometry_surveyed
        assert track.curvature_at(0) == track.curvature_at(track.length)
        assert all(math.isfinite(segment.curvature_inv_m.value) for segment in track.segments)
        assert len(artwork["source_sha256"]) == 64


def test_full_grid_randomization_and_observation_boundary():
    session = RaceSession()
    session.advance(0.2)
    observations = session.observations()
    assert len(observations) == 20
    assert len({car.mass_kg.value for car in session.bundle.car_configs.values()}) == 20
    assert session.failure is None
    for observation in observations.values():
        assert "battery_energy_j" in observation.channels
        assert all("battery_energy_j" not in rival for rival in observation.rivals)
    assert "world" not in session.frame()
    assert max(abs(error) for error in session.simulator.energy_close_errors().values()) < 1e-6


def test_restore_repeats_delayed_actions_and_sensor_noise():
    session = RaceSession(RaceSettings(cars=2))
    session.control("car-01", DriverAction(profile=DeploymentProfile.PUSH, low_drag=True))
    session.advance(0.1)
    snapshot = session.snapshot()
    session.advance(0.5)
    expected = session.frame()
    session.restore(snapshot)
    session.advance(0.5)
    assert session.frame() == expected


def test_time_limit_is_truncation_and_cannot_step_after_done():
    session = RaceSession(RaceSettings(cars=1, time_limit_s=1))
    session.advance(2)
    assert session.status == "truncated"
    assert session.finishes == {}
    elapsed = session.simulator.session_time_s
    session.advance(1)
    assert session.simulator.session_time_s == elapsed


def test_contact_ends_episode_without_a_pass_reward():
    session = RaceSession(RaceSettings(cars=2))
    a, b = session.simulator.world.cars.values()
    b.progress_m, b.s_m, b.lateral_d_m = a.progress_m, a.s_m, a.lateral_d_m
    session.advance(0.01)
    assert session.status == "failed"
    assert "contact" in session.failure
    assert session.finishes == {}


def test_finish_requires_crossing_the_shared_line():
    session = RaceSession(RaceSettings(cars=1, laps=1))
    car = session.simulator.world.cars["car-01"]
    car.progress_m = session.track.length - 0.01
    car.s_m = car.progress_m
    session.advance(0.01)
    assert session.status == "finished"
    assert 0 < session.finishes["car-01"] <= 0.01


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 20])
def test_invalid_advances_are_rejected(value):
    session = RaceSession(RaceSettings(cars=1))
    with pytest.raises(ValueError):
        session.advance(value)


def test_traffic_braking_cannot_weaken_corner_braking():
    session = RaceSession(RaceSettings(circuit="monza", cars=1))
    simulator = session.simulator
    position, speed = 3330, 56.5
    floor, _ = simulator._evaluate("car-01", position, speed, -2.5, DriverAction(brake_floor=0.1), 0.01, None)
    manual, _ = simulator._evaluate("car-01", position, speed, -2.5, DriverAction(brake=0.1), 0.01, None)
    assert floor.acceleration_mps2 < manual.acceleration_mps2 - 5
    assert floor.acceleration_mps2 < -10
