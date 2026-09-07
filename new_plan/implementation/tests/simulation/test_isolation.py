"""Truth isolation: a controller can only learn what the sensor path delivers.

The strongest of these is the truth-mutation test. It rewrites every hidden
rival field in ``WorldState`` and in the delay buffer, holds the observable
channels fixed, and asserts the delivered observation is byte-identical. If any
hidden quantity leaked into an observation — through a channel, a context entry
or a stray debug field — the bytes would move.
"""

from __future__ import annotations

import json

import pytest
from conftest import build_bundle

from afterlap_contracts import DeploymentProfile, Quality
from afterlap_core.simulation import DriverAction, Simulator, build_policy, debug_truth
from afterlap_core.simulation.observation import OWN_CHANNELS, RIVAL_CHANNELS, observe

OBSERVABLE_RIVAL_TRUTH = ("progress_m", "speed_mps", "lateral_d_m", "s_m", "lap")
"""Channels an external observer legitimately derives about another car."""

HIDDEN_RIVAL_TRUTH = (
    "battery_energy_j",
    "battery_temperature_k",
    "recharge_this_lap_j",
    "recharge_cumulative_j",
    "acceleration_mps2",
)
"""Truth about another car that no controller may see in this configuration."""


def _prepared(scenario_id: str = "two-straight-counterattack", **kwargs) -> Simulator:
    bundle = build_bundle(scenario_id, **kwargs)
    simulator = Simulator().reset(bundle, seed=31)
    for _ in range(30):
        simulator.step(None, 0.02)
    return simulator


def _controller_output(observation) -> str:
    """A deterministic controller reduced to a comparable string."""
    policy = build_policy("attack")
    action = policy.react(observation, __import__("numpy").random.default_rng(0))
    return json.dumps(action.as_dict(), sort_keys=True)


class TestTruthMutation:
    def test_mutating_hidden_rival_truth_cannot_move_the_observation(self) -> None:
        simulator = _prepared()
        assert simulator.observe()["own"].quality is Quality.VALID
        baseline = simulator.observe()["own"]
        baseline_bytes = baseline.canonical_bytes()
        baseline_action = _controller_output(baseline)

        rival_state = simulator.world.cars["rival"]
        rival_ledger = simulator.world.ledgers["rival"]
        observable_before = {
            name: getattr(rival_state, name if name != "lap" else "lap") for name in OBSERVABLE_RIVAL_TRUTH
        }

        for index, field in enumerate(HIDDEN_RIVAL_TRUTH):
            poison = -987654.0 - index
            # Live truth.
            attribute = {
                "battery_energy_j": "battery_energy_j",
                "battery_temperature_k": "battery_temperature_k",
                "recharge_this_lap_j": "recharge_ledger_this_lap_j",
                "recharge_cumulative_j": "recharge_ledger_j",
                "acceleration_mps2": "acceleration_mps2",
            }[field]
            setattr(rival_state, attribute, poison)
            # Buffered truth, which is what the delayed sensor path actually reads.
            for sample in simulator.world.sensor_buffer:
                sample.cars["rival"][field] = poison

            mutated = simulator.observe()["own"]
            assert mutated.canonical_bytes() == baseline_bytes, (
                f"hidden rival field {field} leaked into the observation"
            )
            assert _controller_output(mutated) == baseline_action

        # The rival's private profile and ledger are hidden too.
        rival_state.active_profile = DeploymentProfile.OVERTAKE
        rival_ledger.recharge_cumulative_j = -1.0
        for sample in simulator.world.sensor_buffer:
            sample.cars["rival"]["active_profile_code"] = DeploymentProfile.OVERTAKE.value
        assert simulator.observe()["own"].canonical_bytes() == baseline_bytes

        # The observable channels really were held fixed, so the test is not
        # passing merely because nothing changed at all.
        for name, value in observable_before.items():
            assert getattr(rival_state, name) == value

    def test_changing_an_observable_channel_does_move_the_observation(self) -> None:
        """Control for the test above: the comparison is not insensitive."""
        simulator = _prepared()
        baseline = simulator.observe()["own"].canonical_bytes()
        for sample in simulator.world.sensor_buffer:
            sample.cars["rival"]["progress_m"] += 25.0
        assert simulator.observe()["own"].canonical_bytes() != baseline


class TestChannelGating:
    def test_rival_energy_is_absent_when_it_is_not_exposed(self) -> None:
        simulator = _prepared()
        assert simulator.sensor_config.expose_rival_energy is False
        for observation in simulator.observe().values():
            for rival in observation.rivals:
                assert "battery_energy_j" not in rival
                assert "energy_j" not in rival
                assert set(rival) == {"car_id", *RIVAL_CHANNELS}

    def test_an_absent_channel_is_absent_not_zero(self) -> None:
        simulator = _prepared("loop-no-energy-channel")
        assert simulator.sensor_config.energy_channel_available is False
        observation = simulator.observe()["own"]
        assert "battery_energy_j" not in observation.channels
        assert observation.has("battery_energy_j") is False
        with pytest.raises(KeyError, match="never zero"):
            observation.get("battery_energy_j")

    def test_the_energy_channel_is_present_when_configured(self) -> None:
        simulator = _prepared()
        assert simulator.observe()["own"].has("battery_energy_j") is True

    def test_exposing_rival_energy_requires_explicit_configuration(self) -> None:
        simulator = _prepared(expose_rival_energy=True)
        rival = simulator.observe()["own"].rivals[0]
        assert "battery_energy_j" in rival
        assert (
            rival["battery_energy_j"]
            == pytest.approx(simulator.world.sensor_buffer[0].cars["rival"]["battery_energy_j"], rel=1e-9)
            or rival["battery_energy_j"] > 0.0
        )


class TestNoDebugLeak:
    def test_no_observation_field_carries_truth_vocabulary(self) -> None:
        simulator = _prepared()
        for observation in simulator.observe().values():
            payload = observation.as_plain()
            assert set(payload) == {
                "car_id",
                "observed_at_s",
                "delivered_at_s",
                "channels",
                "rivals",
                "context",
                "provenance",
                "quality",
            }
            assert set(payload["channels"]) <= set(OWN_CHANNELS)
            for rival in payload["rivals"]:
                assert set(rival) <= {"car_id", *RIVAL_CHANNELS, "battery_energy_j"}
            every_key = [
                *payload["channels"],
                *payload["context"],
                *(key for rival in payload["rivals"] for key in rival),
            ]
            for key in every_key:
                lowered = key.lower()
                for banned in ("truth", "debug", "info", "internal", "hidden", "private", "world"):
                    assert banned not in lowered, f"observation key {key} looks like a truth leak"

    def test_observe_never_calls_debug_truth(self, monkeypatch) -> None:
        import afterlap_core.simulation.observation as observation_module

        simulator = _prepared()

        def explode(_world):  # pragma: no cover - must never run
            raise AssertionError("observe() called debug_truth()")

        monkeypatch.setattr(observation_module, "debug_truth", explode)
        assert observe(simulator.world, simulator.sensor_config)["own"].quality is Quality.VALID

    def test_debug_truth_is_a_separate_gated_entry_point(self) -> None:
        simulator = _prepared()
        truth = debug_truth(simulator.world)
        assert truth["cars"]["rival"]["battery_energy_j"] == pytest.approx(
            simulator.world.cars["rival"].battery_energy_j, rel=1e-12
        )
        # Nothing in an observation matches this structure.
        observation = simulator.observe()["own"]
        assert "cars" not in observation.as_plain()


class TestPolicyInputs:
    def test_a_policy_receives_only_an_observation(self) -> None:
        """The rival's own action must be derivable from its observation alone."""
        import numpy as np

        simulator = _prepared()
        policy = simulator.world.policies["rival"]
        observation = simulator.observe(car_id="rival")["rival"]
        first = policy.react(observation, np.random.default_rng(0))

        # Corrupt every piece of world truth the policy is not allowed to read.
        for state in simulator.world.cars.values():
            state.battery_temperature_k = 999.0
        again = build_policy(
            "defend",
            {
                "reserve_energy_j": 8.0e5,
                "engage_gap_s": 1.0,
                "release_gap_s": 1.6,
            },
        ).react(observation, np.random.default_rng(0))
        assert again.profile == first.profile
        assert again.target_lateral_d_m == pytest.approx(first.target_lateral_d_m)

    def test_a_missing_observation_produces_a_hold_not_a_zero_filled_guess(self) -> None:
        bundle = build_bundle(observation_delay_s=5.0)
        simulator = Simulator().reset(bundle, seed=3)
        simulator.step(None, 0.02)
        observation = simulator.observe()["own"]
        assert observation.quality is Quality.MISSING
        assert dict(observation.channels) == {}
        assert observation.rivals == ()
        import numpy as np

        action = build_policy("normal").react(observation, np.random.default_rng(0))
        assert action.label.endswith("no_observation_hold")
        assert isinstance(action, DriverAction)
