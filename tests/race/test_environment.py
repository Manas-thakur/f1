import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSettings
from afterlap_core.race.control import DriverControl
from afterlap_core.race.environment import (
    ACTION_FIELDS,
    PROFILES,
    RaceEnv,
    decode_action,
    encode,
    encode_control,
)


def test_environment_contract_and_seeded_transitions():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=3))
    check_env(env, skip_render_check=True)


def test_unknown_masks_and_hidden_rival_energy():
    env = RaceEnv(RaceSettings(cars=2))
    observation, _ = env.reset(seed=12)
    assert not observation[20:].any()
    observation, _, _, _, _ = env.step(encode_control(DriverControl(mode="automatic")))
    assert observation.shape == (40,)
    expected = encode(env.session)
    env.session.simulator.world.cars["car-02"].battery_energy_j = 1e9
    np.testing.assert_array_equal(encode(env.session), expected)
    assert np.isfinite(observation).all()


def test_terminal_and_timeout_are_distinct():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=1))
    env.reset()
    _, reward, terminated, truncated, info = env.step(encode_control(DriverControl(mode="automatic")))
    assert truncated and not terminated
    assert info["finish_position"] is None
    assert reward < 0
    assert len(PROFILES) == 5


def test_every_live_driver_control_round_trips_through_rl_action():
    configured = DriverControl(
        mode="direct",
        profile=DeploymentProfile.OVERTAKE,
        pace_scale=0.82,
        target_lateral_d_m=2.5,
        low_drag=True,
        throttle=0.75,
        brake=0.25,
    )
    decoded = decode_action(encode_control(configured))
    assert decoded.mode == configured.mode
    assert decoded.profile == configured.profile
    assert decoded.pace_scale == pytest.approx(configured.pace_scale)
    assert decoded.target_lateral_d_m == pytest.approx(configured.target_lateral_d_m)
    assert decoded.low_drag == configured.low_drag
    assert decoded.throttle == pytest.approx(configured.throttle)
    assert decoded.brake == pytest.approx(configured.brake)
    assert len(ACTION_FIELDS) == 8


def test_direct_and_automatic_driver_authority_are_scriptable():
    env = RaceEnv(RaceSettings(cars=1, time_limit_s=3))
    env.reset()
    direct = DriverControl(mode="direct", target_lateral_d_m=2, low_drag=True)
    _, _, _, _, info = env.step(encode_control(direct))
    assert env.session.overrides["car-01"].target_lateral_d_m == pytest.approx(2)
    assert info["requested_control"]["mode"] == "direct"
    automatic = DriverControl(mode="automatic", profile=DeploymentProfile.CONSERVE)
    env.step(encode_control(automatic))
    assert "car-01" not in env.session.overrides
    assert env.session.bms_profiles["car-01"] == DeploymentProfile.CONSERVE
