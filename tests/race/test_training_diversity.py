import numpy as np
import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings, TrainingDiversity
from afterlap_core.race.decision import DECISION_PROFILES, BoostDecisionEnv
from afterlap_core.race.diversity import apply_command_diversity, episode_race_settings, next_episode_seed
from afterlap_core.race.environment import RaceEnv
from afterlap_core.race.factory import race_bundle
from afterlap_core.race.training import evaluate_decision_policy
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


def test_training_diversity_rejects_out_of_range_spans():
    with pytest.raises(ValueError):
        TrainingDiversity(progress_span_m=5)
    with pytest.raises(ValueError):
        TrainingDiversity(energy_span_j=-1)


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


def test_apply_command_diversity_defaults_on_only_for_training():
    settings = RaceSettings()
    assert apply_command_diversity(settings, None, default_enabled=False).training_diversity.enabled is False
    assert apply_command_diversity(settings, None, default_enabled=True).training_diversity.enabled is True
    assert apply_command_diversity(settings, False, default_enabled=True).training_diversity.enabled is False
    assert apply_command_diversity(settings, True, default_enabled=False).training_diversity.enabled is True


def test_decision_env_leaves_the_fixed_seed_loop_and_replays_explicit_seeds():
    settings = RaceSettings(
        cars=4,
        time_limit_s=2,
        variability=Variability(preset="training"),
        training_diversity=TrainingDiversity(enabled=True),
    )
    env = BoostDecisionEnv(settings)
    first_obs, first_info = env.reset(seed=11)
    first_energy = env.session.bundle.scenario.initial_states["car-01"].energy_j.value
    first_progress = env.session.bundle.scenario.initial_states["car-01"].progress_m.value
    _, second_info = env.reset()
    replay_obs, replay_info = env.reset(seed=11)
    assert first_info["episode_seed"] == 11
    assert second_info["episode_seed"] != 11
    assert replay_info["episode_seed"] == 11
    np.testing.assert_array_equal(replay_obs, first_obs)
    assert env.session.bundle.scenario.initial_states["car-01"].energy_j.value == first_energy
    assert env.session.bundle.scenario.initial_states["car-01"].progress_m.value == first_progress


def test_decision_env_varies_episode_seed_even_when_start_states_stay_fixed():
    env = BoostDecisionEnv(RaceSettings(cars=2, time_limit_s=2, variability=Variability(preset="training")))
    _, first = env.reset(seed=5)
    second_obs, second = env.reset()
    third_obs, third = BoostDecisionEnv(
        RaceSettings(cars=2, time_limit_s=2, variability=Variability(preset="training"))
    ).reset(seed=second["episode_seed"])
    assert first["episode_seed"] == 5
    assert second["episode_seed"] != 5
    assert third["episode_seed"] == second["episode_seed"]
    np.testing.assert_array_equal(third_obs, second_obs)


def test_held_out_decision_seeds_match_for_baseline_and_policy_comparison():
    settings = RaceSettings(cars=3, time_limit_s=2, training_diversity=TrainingDiversity(enabled=True))
    first = BoostDecisionEnv(settings)
    second = BoostDecisionEnv(settings)
    obs_a, info_a = first.reset(seed=10003)
    obs_b, info_b = second.reset(seed=10003)
    action = DECISION_PROFILES.index(DeploymentProfile.NEUTRAL)
    next_a, reward_a, _, _, _ = first.step(action)
    next_b, reward_b, _, _, _ = second.step(action)
    assert info_a["episode_seed"] == info_b["episode_seed"] == 10003
    np.testing.assert_array_equal(obs_a, obs_b)
    np.testing.assert_array_equal(next_a, next_b)
    assert reward_a == reward_b


def test_race_env_reset_without_seed_advances_the_episode_stream():
    env = RaceEnv(RaceSettings(cars=2, time_limit_s=2, training_diversity=TrainingDiversity(enabled=True)))
    _, first = env.reset(seed=8)
    _, second = env.reset()
    assert first["episode_seed"] == 8
    assert second["episode_seed"] != 8
    assert env.session.settings.seed == second["episode_seed"]


def test_training_diversity_can_rotate_circuits_from_a_seeded_list():
    settings = episode_race_settings(
        RaceSettings(
            circuit="monza",
            training_diversity=TrainingDiversity(enabled=True, circuits=("monza", "silverstone", "spa")),
        ),
        14,
    )
    other = episode_race_settings(
        RaceSettings(
            circuit="monza",
            training_diversity=TrainingDiversity(enabled=True, circuits=("monza", "silverstone", "spa")),
        ),
        15,
    )
    replay = episode_race_settings(
        RaceSettings(
            circuit="monza",
            training_diversity=TrainingDiversity(enabled=True, circuits=("monza", "silverstone", "spa")),
        ),
        14,
    )
    assert settings.circuit == replay.circuit
    assert settings.circuit in {"monza", "silverstone", "spa"}
    assert {settings.circuit, other.circuit} <= {"monza", "silverstone", "spa"}


def test_rules_baseline_evaluation_covers_diverse_held_out_seeds():
    metrics = evaluate_decision_policy(
        None,
        RaceSettings(
            circuit="monza",
            cars=2,
            time_limit_s=2,
            training_diversity=TrainingDiversity(enabled=True),
        ),
        episodes=2,
        seed_offset=10000,
    )
    assert metrics["episodes"] == 2
    assert metrics["failure_rate"] == 0.0
    assert np.isfinite(metrics["mean_reward"])
    assert np.isfinite(metrics["mean_finish_position"])
