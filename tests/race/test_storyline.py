import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.settings import StorylineSettings
from afterlap_core.race.tyres import TYRE_SPECS, TyreCompound, TyreState
from afterlap_core.simulation.policies import DriverAction


def test_qualification_order_and_seeded_compounds_are_reproducible():
    first = RaceSession(RaceSettings(seed=121, cars=20))
    second = RaceSession(RaceSettings(seed=121, cars=20))
    progress = [state.progress_m for state in first.simulator.world.cars.values()]
    assert progress == sorted(progress, reverse=True)
    assert [car["qualifying_position"] for car in first.frame()["cars"]] == list(range(1, 21))
    assert [state.compound for state in first.tyres.values()] == [
        state.compound for state in second.tyres.values()
    ]
    assert len({state.compound for state in first.tyres.values()}) == 3


def test_compounds_trade_grip_for_durability_and_wear_reaches_pit_threshold():
    assert TYRE_SPECS[TyreCompound.SOFT].grip > TYRE_SPECS[TyreCompound.MEDIUM].grip
    assert TYRE_SPECS[TyreCompound.MEDIUM].grip > TYRE_SPECS[TyreCompound.HARD].grip
    assert TYRE_SPECS[TyreCompound.SOFT].life_m < TYRE_SPECS[TyreCompound.MEDIUM].life_m
    assert TYRE_SPECS[TyreCompound.MEDIUM].life_m < TYRE_SPECS[TyreCompound.HARD].life_m
    state = TyreState(TyreCompound.SOFT, 1, 0.2, 0, TyreCompound.HARD)
    state.wear(TYRE_SPECS[TyreCompound.SOFT].life_m, 0.5, 1)
    assert state.condition <= state.change_threshold
    assert state.grip < TYRE_SPECS[TyreCompound.SOFT].grip


def test_tyre_grip_changes_the_physical_envelope():
    session = RaceSession(RaceSettings(cars=1))
    state = session.simulator.world.cars["car-01"]
    state.tyre_grip_multiplier = 0.8
    worn, _ = session.simulator._evaluate("car-01", 100, 30, 0, DriverAction(), 0.01, None)
    state.tyre_grip_multiplier = 1.03
    fresh, _ = session.simulator._evaluate("car-01", 100, 30, 0, DriverAction(), 0.01, None)
    assert fresh.diagnostics["traction_envelope_n"] > worn.diagnostics["traction_envelope_n"]
    assert fresh.diagnostics["envelope_speed_mps"] > worn.diagnostics["envelope_speed_mps"]


def test_pit_service_finishes_and_launches_the_car_within_four_seconds():
    session = RaceSession(RaceSettings(cars=1))
    tyre = session.tyres["car-01"]
    state = session.simulator.world.cars["car-01"]
    fitted = tyre.next_compound
    duration = tyre.service_duration_s
    tyre.phase = "service"
    tyre.service_remaining_s = duration
    state.speed_mps = 0
    start = state.progress_m
    session.advance(3.8)
    assert 2 <= duration <= 3
    assert tyre.stops == 1
    assert tyre.compound == fitted
    assert tyre.phase == "exit"
    assert tyre.release_waiting is False
    assert state.progress_m > start
    assert state.speed_mps > 0
    completed = next(event for event in session.events if event["kind"] == "pit_service_completed")
    assert completed["session_time_s"] <= duration + session.settings.dt_s


def test_pit_service_only_starts_at_the_assigned_box():
    session = RaceSession(RaceSettings(cars=1))
    tyre = session.tyres["car-01"]
    state = session.simulator.world.cars["car-01"]
    tyre.phase = "entry"
    tyre.box_progress_m = session._pit_box_s("car-01")
    state.progress_m = tyre.box_progress_m - 20
    state.s_m = state.progress_m
    state.speed_mps = 0
    session._update_tyres(0.1)
    assert tyre.phase == "entry"
    assert state.speed_mps == 1.5
    assert session.simulator.world.active_actions["car-01"].label == "pit_entry"
    state.progress_m = tyre.box_progress_m
    state.s_m = session._pit_box_s("car-01")
    state.speed_mps = 0
    session._update_tyres(0.1)
    assert tyre.phase == "service"
    assert state.progress_m == tyre.box_progress_m


def test_pit_boxes_are_unique_and_safe_releases_are_serialized():
    session = RaceSession(RaceSettings(cars=3))
    boxes = [session._pit_box_s(car_id) for car_id in session.tyres]
    assert len(set(boxes)) == 3
    assert all(box >= session._pit_lane_start_s for box in boxes)
    assert boxes[0] - boxes[1] == boxes[1] - boxes[2] == 9
    for car_id, tyre in session.tyres.items():
        state = session.simulator.world.cars[car_id]
        state.progress_m = session._pit_box_s(car_id)
        state.s_m = state.progress_m
        state.speed_mps = 0
        tyre.phase = "exit"
        tyre.release_waiting = True
    session._update_tyres(0.01)
    assert session.tyres["car-01"].release_waiting is False
    assert session.tyres["car-02"].release_waiting is True
    assert session.tyres["car-03"].release_waiting is True
    assert session.simulator.world.active_actions["car-01"].label == "pit_exit"
    assert session.simulator.world.cars["car-01"].speed_mps == 1.5
    assert session.simulator.world.active_actions["car-02"].label == ""


def test_storyline_randomizes_independent_actions_and_checkpoint_replay():
    settings = RaceSettings(
        cars=3,
        storyline=StorylineSettings(
            pit_stops=False,
            event_interval_min_s=1,
            event_interval_max_s=1,
            event_duration_min_s=1,
            event_duration_max_s=1,
        ),
    )
    session = RaceSession(settings)
    session.advance(1.3)
    assert any(beat.mode != "natural" for beat in session.storyline.beats.values())
    assert len({beat.mode for beat in session.storyline.beats.values()}) > 1
    saved = session.snapshot()
    session.advance(1)
    expected = session.frame()
    session.restore(saved)
    session.advance(1)
    assert session.frame() == expected
    matrix = session.frame()["boost_evaluation"]
    assert sum(matrix[key] for key in ("true_positive", "false_positive", "true_negative", "false_negative"))


def test_pit_stop_overrides_direct_boost_control():
    session = RaceSession(RaceSettings(cars=1))
    session.control("car-01", DriverAction(profile=DeploymentProfile.OVERTAKE))
    session.tyres["car-01"].phase = "service"
    action = session._requested_action(session.observations()["car-01"])
    assert action.label == "pit_service"
    assert action.profile == DeploymentProfile.HARVEST


@pytest.mark.parametrize("mode", ["attack", "push", "surge"])
def test_storyline_pace_never_overrides_collision_braking(mode):
    session = RaceSession(RaceSettings(cars=1))
    session.storyline.beats["car-01"].mode = mode
    action, _ = session.storyline.direct(
        "car-01",
        session.observations()["car-01"],
        DriverAction(acceleration_ceiling_mps2=-12),
    )
    assert action.acceleration_ceiling_mps2 == -12
