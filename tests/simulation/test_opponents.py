"""Reactive opponents, pass labelling and contact geometry."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import build_bundle

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, Simulator, build_policy
from afterlap_core.simulation.track import footprints_overlap, geometry_for


def _run(actions: list[DriverAction], seed: int = 42, dt_s: float = 0.02) -> list[dict]:
    """Run the ego action stream and return the rivals' reactions."""
    bundle = build_bundle(reaction_delay_s=0.10)
    simulator = Simulator().reset(bundle, seed=seed)
    trace = []
    for action in actions:
        report = simulator.step({"own": action}, dt_s)
        trace.append({car_id: rival.as_dict() for car_id, rival in sorted(report.policy_actions.items())})
    return trace


class TestTreatmentSensitivity:
    def test_an_identical_treatment_pair_gives_equivalent_output(self) -> None:
        stream = [DriverAction(profile=DeploymentProfile.PUSH) for _ in range(120)]
        assert _run(list(stream)) == _run(list(stream))

    def test_a_different_treatment_changes_the_rival_action(self) -> None:
        """Same seed, same exogenous disturbances, different ego behaviour."""
        pushing = [DriverAction(profile=DeploymentProfile.OVERTAKE) for _ in range(200)]
        coasting = [
            DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=0.25) for _ in range(200)
        ]
        pushed = _run(pushing)
        coasted = _run(coasting)
        assert pushed != coasted

        pushed_labels = {step["rival"]["label"] for step in pushed}
        coasted_labels = {step["rival"]["label"] for step in coasted}
        assert pushed_labels != coasted_labels, (
            f"the rival's finite state never diverged: {pushed_labels} vs {coasted_labels}"
        )

    def test_the_rival_reacts_to_pressure_by_defending(self) -> None:
        pushed = _run([DriverAction(profile=DeploymentProfile.OVERTAKE) for _ in range(250)])
        labels = [step["rival"]["label"] for step in pushed]
        assert any(label.endswith("defending") for label in labels)


class TestPolicyIdentity:
    def test_every_policy_has_a_stable_hash(self) -> None:
        for kind in ("conserve", "normal", "attack", "defend"):
            first = build_policy(kind).policy_hash
            second = build_policy(kind).policy_hash
            assert first == second
            assert first.startswith("sha256:")

    def test_different_preferences_give_different_hashes(self) -> None:
        base = build_policy("attack").policy_hash
        keen = build_policy("attack", {"engage_gap_s": 1.5, "release_gap_s": 2.2}).policy_hash
        assert base != keen

    def test_an_unknown_parameter_is_rejected_rather_than_ignored(self) -> None:
        with pytest.raises(KeyError):
            build_policy("attack", {"recklessness": 1.0})
        with pytest.raises(KeyError):
            build_policy("kamikaze")

    def test_aggressiveness_cannot_exceed_the_envelope(self) -> None:
        """``pace_scale`` is a bounded preference, never a licence."""
        keen = build_policy("attack", {"pace_scale": 5.0})
        observation_free_action = keen.react(_observation_for("attack"), np.random.default_rng(0))
        assert observation_free_action.pace_scale <= 1.0
        with pytest.raises(ValueError, match="bounded preference range"):
            DriverAction(pace_scale=1.4)

    def test_a_policy_memory_round_trips(self) -> None:
        policy = build_policy("attack")
        policy.react(_observation_for("attack"), np.random.default_rng(0))
        captured = policy.capture()
        policy.memory["state"] = "corrupted"
        policy.restore(captured)
        assert policy.memory == captured


def _observation_for(_kind: str):
    simulator = Simulator().reset(build_bundle(), seed=1)
    for _ in range(20):
        simulator.step(None, 0.02)
    return simulator.observe(car_id="own")["own"]


class TestContactGeometry:
    def test_footprints_overlap_only_when_they_really_do(self) -> None:
        geometry = geometry_for(build_bundle().track)
        assert footprints_overlap(geometry, 100.0, 0.0, 0.30, 5.6, 2.0, 94.35, 0.6, -0.30, 5.6, 2.0)
        assert not footprints_overlap(geometry, 100.0, 0.0, 0.0, 5.6, 2.0, 94.35, 0.6, 0.0, 5.6, 2.0)
        assert not footprints_overlap(geometry, 100.0, 0.0, 0.30, 5.6, 2.0, 80.0, 0.6, -0.30, 5.6, 2.0)

    def test_no_pass_is_recorded_while_the_footprints_overlap(self) -> None:
        simulator = Simulator().reset(build_bundle(), seed=8)
        for _ in range(20):
            simulator.step(None, 0.02)

        own = simulator.world.cars["own"]
        rival = simulator.world.cars["rival"]
        pair = simulator.world.pairs[("own", "rival")]
        pair.label = "contesting"
        pair.armed = True
        pair.attempted = True

        rival.progress_m = 500.0
        rival.s_m = 500.0
        rival.lateral_d_m = 0.6
        rival.heading_error_rad = -0.30
        own.progress_m = 505.65
        own.s_m = 505.65
        own.lateral_d_m = 0.0
        own.heading_error_rad = 0.30

        assert simulator._overlapping("own", "rival") is True
        records = simulator.detect_geometry_events()
        kinds = [record.kind for record in records]
        assert "completed_pass" not in kinds, "a pass was rewarded while the cars were in contact"
        assert "blocked_by_contact" in kinds
        assert simulator.world.pairs[("own", "rival")].label != "ahead"

        own.lateral_d_m = 3.0
        own.heading_error_rad = 0.0
        rival.heading_error_rad = 0.0
        assert simulator._overlapping("own", "rival") is False
        assert "completed_pass" in [record.kind for record in simulator.detect_geometry_events()]


class TestPassHysteresis:
    def test_labels_do_not_flap_around_the_clearance_boundary(self) -> None:
        simulator = Simulator().reset(build_bundle(), seed=8)
        for _ in range(20):
            simulator.step(None, 0.02)

        own = simulator.world.cars["own"]
        rival = simulator.world.cars["rival"]
        for state, progress in ((rival, 500.0), (own, 480.0)):
            state.progress_m = progress
            state.s_m = progress
            state.lateral_d_m = 0.0
            state.heading_error_rad = 0.0
        own.lateral_d_m = 3.0
        simulator.world.pairs[("own", "rival")].label = "behind"
        simulator.world.pairs[("own", "rival")].armed = True
        simulator.world.pairs[("rival", "own")].label = "ahead"

        clearance = 0.5 * (
            float(simulator.world.car_configs["own"].length_m.value)
            + float(simulator.world.car_configs["rival"].length_m.value)
        )

        own.progress_m = own.s_m = rival.progress_m + clearance + 0.4
        opening = [record.kind for record in simulator.detect_geometry_events()]
        assert opening.count("attempted_pass") == 1
        assert opening.count("completed_pass") == 1
        assert simulator.world.pairs[("own", "rival")].label == "ahead"

        extra = []
        for index in range(60):
            own.progress_m = own.s_m = rival.progress_m + clearance + 0.4 + 0.9 * (-1) ** index
            extra.extend(record.kind for record in simulator.detect_geometry_events())

        assert extra == [], f"the pass label flapped inside the hysteresis band: {extra}"
        assert simulator.world.pairs[("own", "rival")].label == "ahead"

    def test_a_genuine_repass_is_recorded_once_in_each_direction(self) -> None:
        simulator = Simulator().reset(build_bundle(), seed=8)
        for _ in range(20):
            simulator.step(None, 0.02)
        own = simulator.world.cars["own"]
        rival = simulator.world.cars["rival"]
        rival.progress_m = rival.s_m = 500.0
        rival.lateral_d_m = 0.0
        rival.heading_error_rad = 0.0
        own.lateral_d_m = 3.0
        own.heading_error_rad = 0.0
        simulator.world.pairs[("own", "rival")].label = "behind"
        simulator.world.pairs[("rival", "own")].label = "ahead"

        events: list[str] = []
        for offset in (-30.0, -6.0, 12.0, 30.0, 12.0, -6.0, -30.0, -6.0, 12.0, 30.0):
            own.progress_m = own.s_m = rival.progress_m + offset
            events.extend(
                f"{record.kind}:{record.overtaking_car_id}" for record in simulator.detect_geometry_events()
            )

        assert events.count("completed_pass:own") == 2
        assert events.count("completed_pass:rival") == 1
