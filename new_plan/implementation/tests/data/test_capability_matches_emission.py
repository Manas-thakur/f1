"""A declared capability must match what the source actually emits.

Found during integration: ``simulator_capability()`` declared four channels the
simulator never produced — ``electrical_power_w``, ``lap_distance_m``,
``gap_ahead_s`` and ``gap_behind_s``. The estimator trusted the declaration,
found no power samples to integrate, and its energy belief drifted on the
correction term alone.

This is the same failure mode the ``SourceCapability`` contract already guards
against in one direction: it refuses to call a channel *measured* unless it is
also *supported*. Nothing checked the other direction — that a supported
channel actually arrives — because only a running source can answer it.

A consumer that trusts the declaration and receives nothing cannot tell a
channel that was never emitted from a feed that has failed. That distinction is
the whole basis of the quality signalling downstream, so this test exists to
keep the two in step.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import CHANNELS_BY_NAME, DeploymentProfile, is_registered
from afterlap_core.data import simulator_capability, simulator_mapping
from afterlap_core.simulation import DriverAction, Simulator, load_bundle

SCENARIO = "two-straight-counterattack"


@pytest.fixture(scope="module")
def emitted_channels() -> frozenset[str]:
    """Channels the simulator actually puts on an own-car observation."""
    bundle = load_bundle(SCENARIO)
    simulator = Simulator()
    simulator.reset(bundle, seed=42)
    # Run past the observation delay so a real sample exists rather than the
    # explicit missing state the simulator reports before its buffer fills.
    for _ in range(100):
        simulator.step({"own": DriverAction(profile=DeploymentProfile.PUSH)}, 0.02)
    return frozenset(dict(simulator.observe(car_id="own")["own"].channels))


@pytest.fixture(scope="module")
def emitted_canonical_channels(emitted_channels) -> frozenset[str]:
    """The emitted vendor fields translated to canonical channel names.

    The capability declares canonical names while the simulator emits its own
    field names, so the two can be compared only through the mapping that
    exists to translate them. Comparing the raw names worked while every
    mapping entry was an identity pair, which is exactly how the drift between
    ``s_m`` and ``lap_distance_m`` stayed invisible.
    """
    mapping = simulator_mapping()
    return frozenset(
        entry.channel
        for field_name in emitted_channels
        if (entry := mapping.get(field_name)) is not None
    )


def test_every_declared_channel_is_actually_emitted(emitted_canonical_channels):
    declared = frozenset(simulator_capability().supported_channels)
    missing = declared - emitted_canonical_channels
    assert missing == frozenset(), (
        "simulator_capability declares channels the simulator never emits: "
        f"{sorted(missing)}. A consumer trusting this list cannot distinguish "
        "a channel that was never produced from a feed that has failed."
    )


def test_every_declared_channel_is_also_declared_measured(emitted_channels):
    """A simulator observes everything it supplies; nothing is merely configured."""
    capability = simulator_capability()
    assert frozenset(capability.measured_channels) == frozenset(capability.supported_channels)


def test_electrical_power_is_emitted_and_signed_by_the_registry_convention():
    """The estimator integrates this channel; without it energy belief drifts.

    The registry documents the convention: positive deploys to the wheels,
    negative harvests. A PUSH profile must therefore report positive power.
    """
    assert is_registered("electrical_power_w")
    spec = CHANNELS_BY_NAME["electrical_power_w"]
    assert spec.unit == "W"
    assert "positive deploys" in (spec.note or "")

    bundle = load_bundle(SCENARIO)
    simulator = Simulator()
    simulator.reset(bundle, seed=42)
    for _ in range(100):
        simulator.step({"own": DriverAction(profile=DeploymentProfile.PUSH)}, 0.02)
    pushing = dict(simulator.observe(car_id="own")["own"].channels)["electrical_power_w"]
    assert pushing > 0.0, "deploying under PUSH must report positive DC-bus power"

    for _ in range(200):
        simulator.step({"own": DriverAction(profile=DeploymentProfile.HARVEST, brake=1.0)}, 0.02)
    harvesting = dict(simulator.observe(car_id="own")["own"].channels)["electrical_power_w"]
    assert harvesting < pushing, "harvesting must report less DC-bus power than deploying"


def test_declared_channels_are_all_in_the_canonical_registry():
    """A capability cannot advertise a name no consumer can interpret."""
    unregistered = [c for c in simulator_capability().supported_channels if not is_registered(c)]
    # No exceptions. Simulator-frame names such as `s_m` and `lap` used to be
    # tolerated here because the capability published them directly; the
    # mapping now translates `s_m` to the registered `lap_distance_m` and
    # leaves `lap` unpublished, so every declared name resolves.
    assert unregistered == [], f"unregistered channels declared: {unregistered}"
