import numpy as np
import pytest

from afterlap_core.race import RaceSession, RaceSettings, TrainingDiversity
from afterlap_core.race.diversity import episode_race_settings, next_episode_seed
from afterlap_core.race.factory import race_bundle
from afterlap_core.race.variability import Variability


def _start_progress(settings: RaceSettings) -> dict[str, float]:
    return {
        car_id: float(state.progress_m.value)
        for car_id, state in race_bundle(settings).scenario.initial_states.items()
    }


def _start_energy(settings: RaceSettings) -> dict[str, float]:
    return {
        car_id: float(state.energy_j.value)
        for car_id, state in race_bundle(settings).scenario.initial_states.items()
    }


def test_live_start_states_stay_fixed_when_diversity_is_off():
    first = RaceSettings(cars=5, seed=11)
    second = RaceSettings(cars=5, seed=91)
    assert _start_energy(first) == _start_energy(second)
    assert set(_start_energy(first).values()) == {3_100_000}
    assert _start_progress(first) == {f"car-{index + 1:02d}": 200 - index * 10 for index in range(5)}
    assert _start_progress(first) == _start_progress(second)


def test_training_diversity_varies_grid_energy_and_conditions_by_seed():
    first = episode_race_settings(
        RaceSettings(cars=6, seed=0, training_diversity=TrainingDiversity(enabled=True)),
        21,
    )
    second = episode_race_settings(
        RaceSettings(cars=6, seed=0, training_diversity=TrainingDiversity(enabled=True)),
        22,
    )
    replay = episode_race_settings(
        RaceSettings(cars=6, seed=0, training_diversity=TrainingDiversity(enabled=True)),
        21,
    )
    assert first.seed == 21
    assert first.model_dump() == replay.model_dump()
    assert first.model_dump() != second.model_dump()
    assert _start_progress(first) != _start_progress(second)
    assert _start_energy(first) != _start_energy(second)
    assert _start_progress(first) == _start_progress(replay)
    assert _start_energy(first) == _start_energy(replay)
    assert min(_start_energy(first).values()) >= 200_000
    assert max(_start_energy(first).values()) <= 3_950_000


def test_training_diversity_places_the_controlled_car_off_pole():
    ranks = []
    for seed in range(30, 50):
        settings = episode_race_settings(
            RaceSettings(cars=6, seed=0, training_diversity=TrainingDiversity(enabled=True)),
            seed,
        )
        progress = _start_progress(settings)
        ranks.append(1 + sum(value > progress["car-01"] for value in progress.values()))
    assert min(ranks) > 1 or max(ranks) > 1
    assert len(set(ranks)) > 1


def test_training_diversity_rejects_unknown_circuits():
    with pytest.raises(ValueError):
        TrainingDiversity(circuits=("not-a-circuit",))


def test_episode_seed_stream_is_reproducible_and_advances_without_an_explicit_seed():
    first = np.random.default_rng(9)
    second = np.random.default_rng(9)
    assert next_episode_seed(first, 4) == 4
    assert next_episode_seed(first, None) == next_episode_seed(second, None)
    later = next_episode_seed(first, None)
    assert later != next_episode_seed(np.random.default_rng(9), None)
    assert 0 <= later < 2**31


def test_same_seed_still_replays_a_full_session_with_diversity():
    settings = episode_race_settings(
        RaceSettings(
            cars=3,
            time_limit_s=2,
            variability=Variability(preset="training"),
            training_diversity=TrainingDiversity(enabled=True),
        ),
        77,
    )
    first = RaceSession(settings)
    second = RaceSession(settings)
    first.advance(0.3)
    second.advance(0.3)
    assert first.simulator.world.cars["car-01"].progress_m == second.simulator.world.cars["car-01"].progress_m
    assert (
        first.simulator.world.cars["car-01"].battery_energy_j
        == second.simulator.world.cars["car-01"].battery_energy_j
    )
