"""Reproducibility of the simulator: same inputs, same trajectory.

The plan's promise is scoped: reproducibility is checked on a fixed platform and
build, and these tests assert *bit-identical* state sequences on that platform.
Cross-platform equivalence would need a tolerance, which is a separate claim.
"""

from __future__ import annotations

import pytest
from conftest import build_bundle

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, Simulator


def _action_stream(count: int) -> list[DriverAction]:
    """A varied but deterministic action stream."""
    profiles = [
        DeploymentProfile.NEUTRAL,
        DeploymentProfile.PUSH,
        DeploymentProfile.OVERTAKE,
        DeploymentProfile.HARVEST,
        DeploymentProfile.CONSERVE,
    ]
    return [
        DriverAction(
            profile=profiles[index % len(profiles)],
            pace_scale=1.0 - 0.02 * (index % 4),
            target_lateral_d_m=1.5 * ((index % 7) - 3) / 3.0,
            label=f"step-{index}",
        )
        for index in range(count)
    ]


def _trajectory(simulator: Simulator, actions: list[DriverAction], dt_s: float) -> list[tuple]:
    rows = []
    for action in actions:
        simulator.step({"own": action}, dt_s)
        rows.append(
            tuple(
                (
                    car_id,
                    state.progress_m,
                    state.speed_mps,
                    state.lateral_d_m,
                    state.heading_error_rad,
                    state.battery_energy_j,
                    state.battery_temperature_k,
                    state.recharge_ledger_j,
                    state.recharge_ledger_this_lap_j,
                    state.active_profile.value,
                )
                for car_id, state in sorted(simulator.world.cars.items())
            )
        )
    return rows


class TestRepeatedRuns:
    def test_the_same_seed_and_action_stream_reproduce_the_state_sequence(self) -> None:
        bundle = build_bundle(reaction_delay_s=0.12)
        actions = _action_stream(220)

        first = _trajectory(Simulator().reset(bundle, seed=99), actions, 0.02)
        second = _trajectory(Simulator().reset(bundle, seed=99), actions, 0.02)
        assert first == second

    def test_a_different_seed_changes_the_stochastic_path(self) -> None:
        """Sensor noise is seeded, so a different seed must be observable."""
        bundle = build_bundle(reaction_delay_s=0.12)
        one = Simulator().reset(bundle, seed=1)
        two = Simulator().reset(bundle, seed=2)
        for _ in range(30):
            one.step(None, 0.02)
            two.step(None, 0.02)
        assert one.observe()["own"].canonical_bytes() != two.observe()["own"].canonical_bytes()


class TestRestore:
    def test_restore_reproduces_the_trajectory_exactly(self) -> None:
        bundle = build_bundle(reaction_delay_s=0.12)
        actions = _action_stream(160)

        simulator = Simulator().reset(bundle, seed=99)
        _trajectory(simulator, actions[:40], 0.02)
        snapshot = simulator.snapshot()
        reference = _trajectory(simulator, actions[40:], 0.02)

        restored = Simulator().reset(bundle, seed=99)
        restored.restore(snapshot)
        replayed = _trajectory(restored, actions[40:], 0.02)
        assert replayed == reference

    def test_restore_reproduces_a_driver_action_queued_at_snapshot_time(self) -> None:
        """A snapshot taken mid-reaction must replay the pending action's timing."""
        bundle = build_bundle(reaction_delay_s=0.30)
        simulator = Simulator().reset(bundle, seed=17)
        for _ in range(15):
            simulator.step(None, 0.02)

        # Issue an action whose reaction delay has not elapsed, then snapshot.
        pending = DriverAction(profile=DeploymentProfile.OVERTAKE, label="queued")
        simulator.step({"own": pending}, 0.02)
        snapshot = simulator.snapshot()
        assert snapshot["action_queues"]["own"], "the action must still be waiting out its delay"
        queued_at = snapshot["action_queues"]["own"][0]["apply_time_s"]
        assert queued_at > snapshot["race"]["session_time_s"]

        def run(sim: Simulator) -> list[tuple[float, str]]:
            trace = []
            for _ in range(40):
                sim.step(None, 0.02)
                trace.append((sim.session_time_s, sim.world.cars["own"].active_profile.value))
            return trace

        reference = run(simulator)
        restored = Simulator().reset(bundle, seed=17)
        restored.restore(snapshot)
        assert run(restored) == reference
        assert any(profile == DeploymentProfile.OVERTAKE.value for _, profile in reference), (
            "the queued action must actually take effect during the replay"
        )

    def test_sensor_delay_buffers_restore_exactly(self) -> None:
        bundle = build_bundle(reaction_delay_s=0.0, observation_delay_s=0.25)
        simulator = Simulator().reset(bundle, seed=5)
        for _ in range(40):
            simulator.step(None, 0.02)
        snapshot = simulator.snapshot()

        restored = Simulator().reset(bundle, seed=5)
        restored.restore(snapshot)

        assert [sample.session_time_s for sample in restored.world.sensor_buffer] == [
            sample.session_time_s for sample in simulator.world.sensor_buffer
        ]
        assert restored.observe()["own"].canonical_bytes() == simulator.observe()["own"].canonical_bytes()

        before = [simulator.observe()["own"].canonical_bytes() for _ in range(1)]
        for _ in range(20):
            simulator.step(None, 0.02)
            restored.step(None, 0.02)
            assert restored.observe()["own"].canonical_bytes() == simulator.observe()["own"].canonical_bytes()
        assert before

    def test_a_snapshot_from_another_bundle_is_refused(self) -> None:
        """Restoring across scenarios would silently change the physics."""
        loop = Simulator().reset(build_bundle("two-straight-counterattack"))
        oval = Simulator().reset(build_bundle("oval-defend-hold"))
        with pytest.raises(ValueError, match="different scenario bundle"):
            oval.restore(loop.snapshot())


class TestSnapshotCompleteness:
    def test_the_snapshot_carries_every_documented_component(self) -> None:
        simulator = Simulator().reset(build_bundle())
        for _ in range(25):
            simulator.step(None, 0.02)
        snapshot = simulator.snapshot()
        for key in (
            "cars",
            "ledgers",
            "race",
            "clock",
            "events",
            "streams",
            "keyed",
            "policies",
            "action_queues",
            "active_actions",
            "next_thresholds",
            "sensor_buffer",
            "pairs",
            "passes",
            "checkpoint_records",
            "integrator",
        ):
            assert key in snapshot, f"snapshot is missing {key}"
        assert snapshot["integrator"] == "explicit_midpoint"

    def test_the_snapshot_is_a_deep_copy(self) -> None:
        simulator = Simulator().reset(build_bundle())
        simulator.step(None, 0.02)
        snapshot = simulator.snapshot()
        snapshot["cars"]["own"]["speed_mps"] = -1234.0
        assert simulator.world.cars["own"].speed_mps != -1234.0

    def test_the_policy_identity_is_pinned_by_the_snapshot(self) -> None:
        from afterlap_core.simulation import build_policy

        simulator = Simulator().reset(build_bundle())
        simulator.step(None, 0.02)
        snapshot = simulator.snapshot()
        simulator.world.policies["rival"] = build_policy("attack")
        with pytest.raises(ValueError, match="policy hash"):
            simulator.restore(snapshot)
