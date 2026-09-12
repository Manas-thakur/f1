import numpy as np
import pytest

from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.circuit import catalogue
from afterlap_core.race.driver_names import CHAMPION_NAMES, driver_names
from afterlap_core.race.environment import RaceEnv, encode
from afterlap_core.race.variability import Variability


@pytest.mark.parametrize("circuit_id", [item["id"] for item in catalogue()])
def test_varied_full_fields_start_clear_and_inside_each_circuit(circuit_id):
    for seed in (1, 42, 303):
        session = RaceSession(
            RaceSettings(circuit=circuit_id, cars=20, seed=seed, variability=Variability(preset="stress"))
        )
        session._check_contacts()
        assert session.failure is None
        positions = sorted(car.progress_m for car in session.simulator.world.cars.values())
        assert len(set(np.round(np.diff(positions), 6))) > 10
        lateral = [car.lateral_d_m for car in session.simulator.world.cars.values()]
        assert len(set(np.round(lateral, 6))) == 20
        for car_id, state in session.simulator.world.cars.items():
            width = session.bundle.car_configs[car_id].width_m.value
            assert abs(state.lateral_d_m) + width / 2 < session.track.width_at(state.s_m) / 2
            assert 0 <= state.progress_m < session.track.length


def test_grid_and_traits_vary_by_seed_and_replay_exactly():
    settings = RaceSettings(cars=4, seed=12, variability=Variability(preset="training"))
    a, b = RaceSession(settings), RaceSession(settings)
    c = RaceSession(settings.model_copy(update={"seed": 13}))
    assert a.manifest()["initial_states"] == b.manifest()["initial_states"]
    assert a.manifest()["initial_states"] != c.manifest()["initial_states"]
    assert a.manifest()["drivers"] != c.manifest()["drivers"]
    a.advance(0.4)
    b.advance(0.4)
    assert a.frame() == b.frame()


def test_automatic_episodes_vary_but_seeded_sequence_replays():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=1, seed=70))
    sequences = []
    for _ in range(2):
        seeds, trajectories = [], []
        for index in range(4):
            _, info = env.reset(seed=70 if index == 0 else None)
            seeds.append(info["episode_seed"])
            observation, _, _, _, step_info = env.step(0)
            assert step_info["episode_seed"] == info["episode_seed"]
            trajectories.append(observation)
        assert len(set(seeds)) == 4
        sequences.append((seeds, trajectories))
    assert sequences[0][0] == sequences[1][0]
    np.testing.assert_array_equal(sequences[0][1], sequences[1][1])
    assert not np.array_equal(sequences[0][1][0], sequences[0][1][1])


def test_first_unseeded_reset_uses_configured_seed():
    env = RaceEnv(RaceSettings(cars=1, seed=500))
    _, info = env.reset()
    assert info["episode_seed"] == 500
    _, info = env.reset()
    assert info["episode_seed"] != 500


def test_cosmetic_labels_are_unique_and_cannot_change_simulation(monkeypatch):
    settings = RaceSettings(cars=3, seed=91)
    a = RaceSession(settings)
    first = a.driver_names.copy()
    monkeypatch.setattr("afterlap_core.race.driver_names.CHAMPION_NAMES", tuple(reversed(CHAMPION_NAMES)))
    b = RaceSession(settings)
    assert b.driver_names != first
    assert a.bundle.bundle_hash == b.bundle.bundle_hash
    a.advance(0.3)
    b.advance(0.3)
    np.testing.assert_array_equal(encode(a), encode(b))
    assert a.simulator.world.cars == b.simulator.world.cars
    assert a.manifest() == b.manifest()
    labels = driver_names(12, tuple(f"car-{index + 1:02d}" for index in range(20)))
    assert len(set(labels.values())) == 20
    assert set(labels.values()) <= set(CHAMPION_NAMES)
    assert all(car["driver_name"] == a.driver_names[car["id"]] for car in a.frame()["cars"])


def test_automatic_profile_baseline_preserves_driver_authority():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=3), automatic_profiles=True)
    env.reset(seed=4)
    env.step(0)
    _, reward, _, _, info = env.step(4)
    assert env.session.bms_profiles == {}
    assert reward == pytest.approx(-1)
    assert info["requested_profile"] == "automatic"


@pytest.mark.parametrize("seed", [-1, 2**32])
def test_episode_seed_bounds_are_validated(seed):
    with pytest.raises(ValueError, match="32-bit"):
        RaceEnv(RaceSettings(cars=1)).reset(seed=seed)


@pytest.mark.parametrize(("circuit_id", "seed"), [("monza", 42), ("silverstone", 303), ("monaco", 1)])
def test_varied_twenty_car_field_advances_without_contact(circuit_id, seed):
    session = RaceSession(
        RaceSettings(
            circuit=circuit_id,
            seed=seed,
            cars=20,
            time_limit_s=2,
            variability=Variability(preset="training"),
        )
    )
    session.advance(2)
    assert session.status == "truncated"
    assert session.failure is None
    assert len(session.frame()["cars"]) == 20
    assert max(abs(error) for error in session.simulator.energy_close_errors().values()) < 1e-6


def test_grid_variation_can_be_disabled_without_disabling_vehicle_variation():
    settings = RaceSettings(cars=4, seed=11, variability=Variability(preset="training", grid_scale=0))
    a = RaceSession(settings)
    b = RaceSession(settings.model_copy(update={"seed": 23}))
    assert [
        (state.progress_m.value, state.lateral_d_m.value)
        for state in a.bundle.scenario.initial_states.values()
    ] == [
        (state.progress_m.value, state.lateral_d_m.value)
        for state in b.bundle.scenario.initial_states.values()
    ]
    assert a.bundle.car_configs["car-01"].mass_kg != b.bundle.car_configs["car-01"].mass_kg
    assert all(state.lateral_d_m.value == 0 for state in a.bundle.scenario.initial_states.values())


@pytest.mark.parametrize("scale", [-0.1, 1.1, float("nan")])
def test_grid_scale_bounds_reject_invalid_values(scale):
    with pytest.raises(ValueError):
        Variability(grid_scale=scale)
