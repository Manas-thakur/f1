from afterlap_core.race import RaceSession, RaceSettings, StorylineSettings
from afterlap_core.race.regulations import RaceRegulations2026
from afterlap_core.race.tyres import TyreCompound


def test_2026_points_scales_and_classification_threshold():
    rules = RaceRegulations2026()
    assert rules.pit_lane_speed_limit_mps == 80 / 3.6
    assert rules.points(1, 0.2, 2) == 6
    assert rules.points(2, 0.3, 2) == 10
    assert rules.points(3, 0.6, 2) == 12
    assert rules.points(10, 1, 2) == 1
    assert rules.points(1, 1, 1) == 0
    assert rules.distance_is_classified(8, 10) is False
    assert rules.distance_is_classified(9, 10) is True


def test_automatic_strategy_requests_a_second_dry_compound():
    session = RaceSession(
        RaceSettings(
            cars=1,
            laps=2,
            storyline=StorylineSettings(enabled=False, tyre_wear_scale=0),
        )
    )
    state = session.simulator.world.cars["car-01"]
    state.progress_m = session.track.length * 0.91
    state.s_m = state.progress_m % session.track.length
    session.advance(0.01)
    assert session.tyres["car-01"].requested is True


def test_pit_lane_limiter_and_dry_compound_classification():
    session = RaceSession(RaceSettings(cars=1, laps=2))
    state = session.simulator.world.cars["car-01"]
    tyre = session.tyres["car-01"]
    tyre.phase = "entry"
    state.s_m = session._pit_lane_start_s + 1
    state.progress_m = state.s_m
    state.speed_mps = 40
    session.advance(0.01)
    assert state.speed_mps <= session.regulations.pit_lane_speed_limit_mps

    session.status = "finished"
    session.finishes["car-01"] = session.simulator.session_time_s
    state.progress_m = 2 * session.track.length
    frame = session.frame()["cars"][0]
    assert frame["classified"] is False
    assert frame["points"] == 0
    tyre.used_compounds.append(
        TyreCompound.MEDIUM if tyre.compound != TyreCompound.MEDIUM else TyreCompound.HARD
    )
    frame = session.frame()["cars"][0]
    assert frame["classified"] is True
    assert frame["points"] == 25


def test_two_stationary_pit_cars_keep_rival_observations_valid():
    session = RaceSession(RaceSettings(cars=2, laps=1))
    for car_id, state in session.simulator.world.cars.items():
        state.speed_mps = 0
        session.tyres[car_id].phase = "service"
        session.tyres[car_id].service_remaining_s = 1
    session.advance(0.2)
    assert session.status == "paused"
    assert all(observation.rivals for observation in session.observations().values())
