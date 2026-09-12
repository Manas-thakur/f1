import numpy as np
from gymnasium.utils.env_checker import check_env

from afterlap_core.race import RaceSettings
from afterlap_core.race.environment import PROFILES, RaceEnv, encode


def test_environment_contract_and_seeded_transitions():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=3))
    check_env(env, skip_render_check=True)


def test_unknown_masks_and_hidden_rival_energy():
    env = RaceEnv(RaceSettings(cars=2))
    observation, _ = env.reset(seed=12)
    assert not observation[20:].any()
    observation, _, _, _, _ = env.step(0)
    assert observation.shape == (40,)
    expected = encode(env.session)
    env.session.simulator.world.cars["car-02"].battery_energy_j = 1e9
    np.testing.assert_array_equal(encode(env.session), expected)
    assert np.isfinite(observation).all()


def test_terminal_and_timeout_are_distinct():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=1))
    env.reset()
    _, reward, terminated, truncated, info = env.step(0)
    assert truncated and not terminated
    assert info["finish_position"] is None
    assert reward < 0
    assert len(PROFILES) == 5
