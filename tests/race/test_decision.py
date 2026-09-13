import numpy as np
from gymnasium.utils.env_checker import check_env

from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.decision import (
    DECISION_PROFILES,
    FEATURE_NAMES,
    OBSERVATION_SIZE,
    REWARD_VERSION,
    BoostDecisionEngine,
    BoostDecisionEnv,
    assess_boost,
    encode_decision,
    score_decision,
)


def test_decision_observation_uses_masks_and_hides_rival_energy():
    session = RaceSession(RaceSettings(cars=2, time_limit_s=3))
    observed = session.observations()["car-01"]
    encoded = encode_decision(session, observed)
    assert encoded.shape == (OBSERVATION_SIZE,)
    assert len(FEATURE_NAMES) * 2 == OBSERVATION_SIZE
    assert not encoded[len(FEATURE_NAMES) : len(FEATURE_NAMES) + 10].any()
    session.advance(0.2)
    observed = session.observations()["car-01"]
    expected = encode_decision(session, observed)
    session.simulator.world.cars["car-02"].battery_energy_j = 1e9
    np.testing.assert_array_equal(encode_decision(session, observed), expected)


def test_decision_environment_preserves_automatic_driver_authority():
    env = BoostDecisionEnv(RaceSettings(cars=2, time_limit_s=1))
    check_env(env, skip_render_check=True)
    env.reset(seed=7)
    action = DECISION_PROFILES.index(DeploymentProfile.PUSH)
    observation, reward, terminated, truncated, info = env.step(action)
    assert env.session is not None
    assert "car-01" not in env.session.overrides
    assert env.session.bms_profiles["car-01"] is DeploymentProfile.PUSH
    assert observation.shape == (OBSERVATION_SIZE,)
    assert np.isfinite(reward)
    assert terminated or truncated or env.session.simulator.session_time_s > 0
    assert info["profile"] == "push"


def test_rules_baseline_withholds_boost_until_telemetry_arrives():
    session = RaceSession(RaceSettings(cars=1, time_limit_s=3))
    missing = assess_boost(session, session.observations()["car-01"])
    assert missing.mode == "neutral"
    assert not missing.boost_available
    session.advance(0.2)
    recommendation = BoostDecisionEngine().recommend(session, session.observations()["car-01"])
    assert recommendation.source == "rules_baseline"
    assert recommendation.overtake_available is False
    assert "FIA 2026" in recommendation.regulation_basis
    assert 0 <= recommendation.risk_score <= 1
    assert 0 <= recommendation.reward_score <= 1


def test_rules_guard_withholds_a_latched_boost_after_energy_recovers():
    session = RaceSession(RaceSettings(cars=1, time_limit_s=3))
    state = session.simulator.world.cars["car-01"]
    state.boost_latched = 1
    state.active_profile = DeploymentProfile.HARVEST
    session.bms_profiles["car-01"] = DeploymentProfile.PUSH
    session.advance(0.2)
    recommendation = assess_boost(session, session.observations()["car-01"])
    assert not recommendation.boost_available
    assert recommendation.mode == "harvest"
    assert "released" in recommendation.reason


def test_decision_reward_credits_a_guarded_opportunity_boost():
    common = {
        "progress_delta": 20.0,
        "deployed_j": 80000.0,
        "positions_gained": 0,
        "positions_lost": 0,
        "new_passes": 0,
        "risk_score": 0.2,
        "reward_score": 0.6,
        "opportunity": True,
        "boost_available": True,
        "action_changed": False,
        "failed": False,
        "finished": False,
        "rank": 3,
    }
    assert score_decision(boosting=True, **common) > score_decision(boosting=False, **common)
    gained = {**common, "positions_gained": 1}
    assert score_decision(boosting=True, **gained) > score_decision(boosting=False, **gained)


def test_decision_reward_penalizes_unavailable_and_withheld_boosts():
    held = score_decision(
        progress_delta=10.0,
        deployed_j=0.0,
        positions_gained=0,
        positions_lost=0,
        new_passes=0,
        boosting=False,
        risk_score=0.3,
        reward_score=0.5,
        opportunity=True,
        boost_available=True,
        action_changed=False,
        failed=False,
        finished=False,
        rank=2,
    )
    unsafe = score_decision(
        progress_delta=10.0,
        deployed_j=0.0,
        positions_gained=0,
        positions_lost=0,
        new_passes=0,
        boosting=True,
        risk_score=0.3,
        reward_score=0.5,
        opportunity=True,
        boost_available=False,
        action_changed=False,
        failed=False,
        finished=False,
        rank=2,
    )
    assert unsafe < held
    assert REWARD_VERSION == "boost-risk-reward-v2"
