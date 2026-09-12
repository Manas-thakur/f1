import math
from dataclasses import asdict, replace
from types import MappingProxyType

import pytest

from afterlap_contracts import DeploymentProfile, Provenance, Quality
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.control import DriverControl
from afterlap_core.race.environment import encode_control
from afterlap_core.race.racecraft import Racecraft
from afterlap_core.race.variability import DriverTraits, RaceWeather, Variability
from afterlap_core.rng import StreamRegistry
from afterlap_core.simulation.observation import Observation
from afterlap_core.simulation.policies import DriverAction


class Straight:
    length = 1000.0

    def width_at(self, s):
        return 12.0

    def curvature_at(self, s):
        return 0.0


class Corner(Straight):
    def curvature_at(self, s):
        return 0.02 if s > 140 else 0.0


def sensed(t=1, gap=30, relative=-4, lateral=0, extra=(), energy=2e6):
    return Observation(
        car_id="car-01",
        observed_at_s=t - 0.1,
        delivered_at_s=t,
        channels=MappingProxyType(
            {
                "speed_mps": 30,
                "progress_m": 100,
                "lateral_d_m": lateral,
                "grip_multiplier": 1,
                "battery_energy_j": energy,
            }
        ),
        rivals=tuple(
            MappingProxyType(rival)
            for rival in (
                {
                    "car_id": "car-02",
                    "relative_progress_m": gap,
                    "relative_speed_mps": relative,
                    "lateral_d_m": 0,
                    "speed_mps": 30 + relative,
                },
                *extra,
            )
        ),
        context=MappingProxyType({}),
        provenance=Provenance.SIMULATED,
        quality=Quality.VALID,
    )


def test_commitment_overlap_completion_return_and_repass():
    driver = Racecraft(DriverTraits(), 0)
    driver.react(sensed(), Straight())
    assert driver.state == "committed"
    goal = driver.goal
    driver.react(sensed(t=1.1, relative=0.1), Straight())
    assert driver.state == "committed"
    assert driver.goal == goal
    driver.react(sensed(t=2, gap=1, lateral=goal), Corner())
    assert driver.state == "alongside"
    assert driver.goal == goal
    driver.react(sensed(t=3, gap=-20, lateral=goal), Straight())
    assert driver.state == "returning"
    driver.react(sensed(t=4, gap=-40), Straight())
    assert driver.state == "free"
    driver.react(sensed(t=5), Straight())
    assert driver.state == "committed"


def test_braking_zone_and_blocked_sides_prevent_commitment():
    driver = Racecraft(DriverTraits(), 0)
    driver.react(sensed(), Corner())
    assert driver.state == "following"
    blockers = tuple(
        {
            "car_id": str(side),
            "relative_progress_m": 0,
            "relative_speed_mps": 0,
            "lateral_d_m": side * 3,
            "speed_mps": 30,
        }
        for side in (-1, 1)
    )
    driver.react(sensed(t=2, extra=blockers), Straight())
    assert driver.state == "following"
    assert driver.lane == 0


def test_overlap_mode_allows_seeded_corner_overtakes_through_occupied_space():
    driver = Racecraft(DriverTraits(), 0, ignore_collisions=True, overtake_in_corners=True)
    blockers = tuple(
        {
            "car_id": str(side),
            "relative_progress_m": 0,
            "relative_speed_mps": 0,
            "lateral_d_m": side * 3,
            "speed_mps": 30,
        }
        for side in (-1, 1)
    )
    driver.react(sensed(extra=blockers), Corner())
    assert driver.state == "committed"
    assert driver.goal != 0


def test_lost_opportunity_aborts_without_cutting_through_rival():
    driver = Racecraft(DriverTraits(), 0)
    driver.react(sensed(), Straight())
    goal = driver.goal
    driver.react(sensed(t=4, gap=20, relative=3, lateral=goal), Straight())
    assert driver.state == "aborting"
    blocker = {
        "car_id": "third",
        "relative_progress_m": 0,
        "relative_speed_mps": 0,
        "lateral_d_m": 0,
        "speed_mps": 30,
    }
    driver.goal = goal
    driver.react(sensed(t=4.1, gap=20, relative=3, lateral=goal, extra=(blocker,)), Straight())
    assert driver.goal == goal


def test_lapped_traffic_and_lap_boundary_have_same_decisions():
    a, b = Racecraft(DriverTraits(), 0), Racecraft(DriverTraits(), 0)
    assert a.react(sensed(gap=30), Straight()) == b.react(sensed(gap=1030), Straight())


def test_missing_observation_holds_lane_without_fabricating_measurements():
    driver = Racecraft(DriverTraits(), -2)
    action = driver.react(replace(sensed(), channels=MappingProxyType({}), rivals=()), Straight())
    assert action.target_lateral_d_m == -2
    assert action.acceleration_ceiling_mps2 == 0
    assert action.label == "unobserved"


def test_driver_sampling_is_bounded_named_and_correlated():
    variability = Variability(preset="stress")
    streams = StreamRegistry(8)
    expected = variability.sample_driver(streams, "car-01")
    other = StreamRegistry(8)
    other.stream("cosmetic").normal(size=100)
    variability.sample_driver(other, "car-02")
    assert variability.sample_driver(other, "car-01") == expected
    assert (expected.headway_s - 0.8) * (expected.pace - 0.93) <= 0
    assert Variability(preset="baseline").sample_driver(StreamRegistry(123), "any") == DriverTraits()


def test_grip_evolves_bounded_and_periodic_without_query_order_randomness():
    weather = RaceWeather(300, 3, 0, 1000, Variability(preset="stress", wetness_target=1), 42)
    assert weather.grip_multiplier(100, 200) < weather.grip_multiplier(100, 0)
    assert weather.grip_multiplier(0, 30) == weather.grip_multiplier(1000, 30)
    expected = weather.headwind_mps(0, 0, 5)
    for time in (10, 1000, 1, 0):
        for position in (0, 200, 600, 1000):
            assert 0.484 <= weather.grip_multiplier(position, time) <= 1
            assert weather.preview_grip(position, time) <= weather.grip_multiplier(
                position, max(0, time - 0.1)
            )
    assert weather.headwind_mps(0, 0, 5) == expected
    assert weather.headwind_mps(0, math.pi, 5) == pytest.approx(-expected)
    dry = RaceWeather(300, 0, 0, 1000, Variability(preset="baseline"), 17)
    assert dry.grip_multiplier(0, 1000) == 1
    assert dry.headwind_mps(300, 0, 52) == 0


def test_checkpoint_replays_driver_weather_and_sensor_state():
    session = RaceSession(RaceSettings(cars=2, variability=Variability(preset="stress", wetness_target=0.9)))
    session.advance(0.37)
    saved = session.snapshot()
    session.advance(0.83)
    expected = session.frame()
    decisions = {car: asdict(driver) for car, driver in session.drivers.items()}
    session.restore(saved)
    for _ in range(4):
        session.frame()
    session.advance(0.83)
    assert session.frame() == expected
    assert {car: asdict(driver) for car, driver in session.drivers.items()} == decisions
    assert session.manifest()["weather"]["wetness_target"] == 0.9
    assert "weather" not in session.observations()["car-01"].context
    saved["model_version"] = "old"
    with pytest.raises(ValueError, match="incompatible"):
        session.restore(saved)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2])
def test_invalid_variability_rejected(value):
    with pytest.raises(ValueError):
        Variability(surface_scale=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corner_strength", -0.1),
        ("randomness", 1.1),
        ("wander_m", float("nan")),
        ("lookahead_m", 201),
        ("smoothing_m", 4),
    ],
)
def test_invalid_racing_line_settings_are_rejected(field, value):
    from afterlap_core.race import RacingLineSettings

    with pytest.raises(ValueError):
        RacingLineSettings(**{field: value})


def test_wetter_conditions_reduce_force_envelope_and_corner_speed():
    dry = RaceSession(RaceSettings(cars=1, variability=Variability(preset="baseline")))
    wet = RaceSession(RaceSettings(cars=1, wetness=1, variability=Variability(preset="baseline")))
    dry_trial, _ = dry.simulator._evaluate("car-01", 100, 30, 0, DriverAction(), 0.01, None)
    wet_trial, _ = wet.simulator._evaluate("car-01", 100, 30, 0, DriverAction(), 0.01, None)
    assert wet_trial.diagnostics["traction_envelope_n"] < dry_trial.diagnostics["traction_envelope_n"]
    assert wet_trial.diagnostics["envelope_speed_mps"] < dry_trial.diagnostics["envelope_speed_mps"]


def test_profile_hysteresis_and_acceleration_request_slew():
    driver = Racecraft(DriverTraits(), 0)
    action = driver.react(sensed(energy=600000), Straight())
    assert action.profile == DeploymentProfile.HARVEST
    action = driver.react(sensed(t=1.1, energy=700000), Straight())
    assert action.profile == DeploymentProfile.HARVEST
    prior = action.acceleration_ceiling_mps2
    action = driver.react(sensed(t=1.2, energy=900000, gap=20, relative=0), Straight())
    assert action.profile != DeploymentProfile.HARVEST
    assert abs(action.acceleration_ceiling_mps2 - prior) <= 0.5 + 1e-9


def test_pass_events_ignore_equal_progress_noise_and_allow_repass():
    session = RaceSession(RaceSettings(cars=2))
    sim = session.simulator
    a, b = sim.world.cars.values()
    a.lateral_d_m, b.lateral_d_m = -2.5, 2.5
    for delta in (-21, -20, -10, -1, 0.1, -0.1, 0.2, 1, 7):
        a.progress_m = b.progress_m + delta
        a.s_m = a.progress_m % session.track.length
        sim.detect_geometry_events()
    records = [r for r in sim.world.passes if r.overtaking_car_id == a.car_id]
    assert [r.kind for r in records] == ["attempted_pass", "longitudinal_overlap", "completed_pass"]
    for delta in (1, -0.1, 0.1, -7, -20, -10, 7):
        a.progress_m = b.progress_m + delta
        a.s_m = a.progress_m % session.track.length
        sim.detect_geometry_events()
    assert (
        len([r for r in sim.world.passes if r.kind == "completed_pass" and r.overtaking_car_id == a.car_id])
        == 2
    )


def test_retention_checkpoint_is_distinct_and_emitted_once():
    from afterlap_core.simulation.engine import StepReport

    session = RaceSession(RaceSettings(cars=2))
    sim = session.simulator
    a, b = sim.world.cars.values()
    pair = sim.world.pairs[(a.car_id, b.car_id)]
    pair.completed_at_s = 1
    a.progress_m = b.progress_m + 20
    a.s_m = a.progress_m % session.track.length
    report = StepReport(2, 0.01, 1)
    checkpoint = session.bundle.scenario.retention_checkpoint_id
    sim._evaluate_retention(a.car_id, checkpoint, 2, report)
    sim._evaluate_retention(a.car_id, checkpoint, 3, report)
    assert [event.kind for event in report.passes] == ["retained_pass"]


def test_wake_uses_lapped_inline_car_and_is_continuous_at_overlap():
    session = RaceSession(RaceSettings(cars=3))
    sim = session.simulator
    a, b, c = sim.world.cars.values()
    for car in (a, b, c):
        car.speed_mps = 40
        car.lateral_d_m = 0
    b.progress_m = a.progress_m + session.track.length + 20
    c.progress_m = a.progress_m + 10
    c.lateral_d_m = 5
    effect = sim._wake_effect_for(a.car_id, a.progress_m, 0, 40)
    assert effect.leader_car_id == b.car_id
    c.progress_m = a.progress_m - 500
    b.progress_m = a.progress_m + 1e-6
    assert sim._wake_effect_for(a.car_id, a.progress_m, 0, 40).shielding < 1e-10


def test_arbitrary_supported_steps_hold_one_second_and_decision_cadence():
    from afterlap_core.race.environment import RaceEnv

    progress = []
    for dt in (0.005, 0.007, 0.01, 0.02):
        env = RaceEnv(RaceSettings(cars=1, dt_s=dt, variability=Variability(preset="baseline")))
        env.reset(seed=4)
        env.step(encode_control(DriverControl(mode="automatic")))
        assert env.session.simulator.session_time_s == pytest.approx(1)
        assert env.session.next_decision_s == pytest.approx(1)
        progress.append(env.session.simulator.world.cars["car-01"].progress_m)
    assert max(progress) - min(progress) < 0.02


def test_incompatible_policy_manifest_fails_before_loading_weights(tmp_path):
    import json

    from afterlap_core.race.policy import load_policy, policy_manifest

    session = RaceSession(RaceSettings(cars=1))
    manifest = policy_manifest(session)
    manifest["environment_version"] = "race-driving-v0"
    path = tmp_path / "policy.zip"
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="incompatible saved policy environment_version"):
        load_policy(path, session)


@pytest.mark.parametrize("seed", [101, 202, 303])
def test_live_pass_and_abort_on_held_out_seeds(seed):
    from race_experiments import experiment

    completed = experiment(seed, "pass", 10)
    aborted = experiment(seed, "abort", 10)
    assert completed["failure"] is None
    assert completed["events"].get("completed_pass") == 1
    assert completed["events"].get("aborted_attempt", 0) == 0
    assert completed["jerk_rms_mps3"] < 10
    assert aborted["failure"] is None
    assert aborted["events"].get("completed_pass", 0) == 0
    assert aborted["events"].get("aborted_attempt") == 1


def test_leader_holds_line_under_pressure_and_follower_keeps_clear_side():
    leader = Racecraft(DriverTraits(), -2.5)
    leader.react(sensed(gap=-10, relative=3, lateral=-2.5), Straight())
    assert leader.lane == -2.5
    follower = Racecraft(DriverTraits(), 3)
    follower.react(sensed(gap=30, lateral=3), Straight())
    assert follower.goal == 3


def test_close_grid_does_not_merge_into_approaching_car():
    session = RaceSession(
        RaceSettings(circuit="monza", cars=2, seed=303, variability=Variability(preset="training"))
    )
    session.advance(3)
    assert session.failure is None


def test_initially_close_pair_records_overlap_without_prior_attempt_band_entry():
    session = RaceSession(RaceSettings(cars=2))
    sim = session.simulator
    a, b = sim.world.cars.values()
    b.progress_m = a.progress_m - 2
    b.s_m = b.progress_m % session.track.length
    events = sim.detect_geometry_events()
    overlap = [event for event in events if event.kind == "longitudinal_overlap"]
    assert len(overlap) == 1
    assert overlap[0].overtaking_car_id == b.car_id
    assert sim.detect_geometry_events() == []
