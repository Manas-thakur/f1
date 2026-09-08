"""TapeEnvironment satisfies the seam and moves the real simulator in the physical direction."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from afterlap_core.conditions import loader as conditions_loader
from afterlap_core.conditions.field import TapeEnvironment
from afterlap_core.conditions.tape import ConditionsSample, ConditionsTape, GustSpec
from afterlap_core.simulation import Simulator
from afterlap_core.simulation.config import load_bundle
from afterlap_core.simulation.policies import DriverAction
from afterlap_core.simulation.track_source import EnvironmentField, StaticEnvironment

from .conftest import simple_tape, synthetic_provenance

CONDITIONS_PACKAGE = Path(conditions_loader.__file__).parent


def test_tape_environment_is_an_environment_field():
    env = TapeEnvironment(simple_tape())
    assert isinstance(env, EnvironmentField)
    assert isinstance(StaticEnvironment(), EnvironmentField)


def test_describes_carries_the_tape_hash_and_source():
    tape = simple_tape()
    env = TapeEnvironment(tape)
    assert tape.content_hash[:19] in env.describes
    assert "synthetic" in env.describes
    assert "gust=off" in env.describes


def test_density_comes_from_the_tape_and_falls_back_only_when_unknown():
    env = TapeEnvironment(simple_tape())
    rho = env.air_density_kgpm3(0.0, 30.0, fallback=1.2)
    assert 1.15 < rho < 1.25 and rho != 1.2
    assert env.density_fallback_queries == 0
    unknown = ConditionsTape("no-p", [ConditionsSample(0.0, air_temperature_k=290.0)], synthetic_provenance())
    env2 = TapeEnvironment(unknown)
    assert env2.air_density_kgpm3(0.0, 0.0, fallback=1.2) == 1.2
    assert env2.density_fallback_queries == 1


def test_headwind_follows_the_wind_convention_and_the_heading_offset():
    # Wind from the east (90 deg), 5 m/s.
    tape = simple_tape(wind_dir_rad=(math.pi / 2,) * 3)
    env = TapeEnvironment(tape, heading_offset_rad=0.0)
    assert env.headwind_mps(0.0, 0.0, 10.0) == pytest.approx(5.0)  # heading east: headwind
    assert env.headwind_mps(0.0, math.pi, 10.0) == pytest.approx(-5.0)  # heading west: tailwind
    # The same relative heading of zero, but the start straight actually points west.
    rotated = TapeEnvironment(tape, heading_offset_rad=math.pi)
    assert rotated.headwind_mps(0.0, 0.0, 10.0) == pytest.approx(-5.0)
    # No wind information at all: still air, not an invented breeze.
    silent = TapeEnvironment(simple_tape(wind_speed=None, wind_dir_rad=None))
    assert silent.headwind_mps(0.0, 0.0, 10.0) == 0.0


def test_grip_multiplier_is_dry_reference_and_lower_in_rain():
    dry = TapeEnvironment(simple_tape())
    wet = TapeEnvironment(simple_tape(rainfall=(True, True, True)))
    assert dry.grip_multiplier(0.0, 30.0) == 1.0
    assert wet.grip_multiplier(0.0, 30.0) < 1.0


def _gusty_tape(seed_label: str = "g") -> ConditionsTape:
    base = simple_tape(tape_id=seed_label, wind_dir_rad=(math.pi / 2,) * 3)
    return ConditionsTape(
        base.tape_id,
        base.samples,
        base.provenance,
        gust=GustSpec(enabled=True, sigma_mps=2.0, bin_width_s=1.0),
    )


def test_gusts_are_keyed_deterministic_per_seed_and_off_by_default():
    assert GustSpec().enabled is False
    a = TapeEnvironment(_gusty_tape(), seed=11)
    b = TapeEnvironment(_gusty_tape(), seed=11)
    c = TapeEnvironment(_gusty_tape(), seed=12)
    times = [0.5 * k for k in range(40)]
    series_a = [a.headwind_mps(0.0, 0.0, t) for t in times]
    series_b = [b.headwind_mps(0.0, 0.0, t) for t in times]
    series_c = [c.headwind_mps(0.0, 0.0, t) for t in times]
    assert series_a == series_b
    assert series_a != series_c
    assert any(abs(v - 5.0) > 1e-9 for v in series_a), "gusts actually perturb the wind"
    calm = TapeEnvironment(simple_tape(wind_dir_rad=(math.pi / 2,) * 3), seed=11)
    assert all(calm.headwind_mps(0.0, 0.0, t) == pytest.approx(5.0) for t in times)


def _run(environment, steps: int = 150) -> list[tuple[float, float]]:
    bundle = load_bundle("two-straight-counterattack")
    sim = Simulator().reset(bundle, seed=7, environment=environment)
    action = DriverAction(throttle=1.0, brake=0.0)
    out = []
    for _ in range(steps):
        sim.step({bundle.scenario.ego_car_id: action}, 0.02)
        ego = sim.world.cars[bundle.scenario.ego_car_id]
        out.append((ego.progress_m, ego.speed_mps))
    return out


def test_wet_gusty_conditions_slow_the_real_simulator_relative_to_static():
    tape = conditions_loader.load_conditions("synthetic-wet-gusty")
    bundle = load_bundle("two-straight-counterattack")
    wet = conditions_loader.environment_for(tape, bundle.track, seed=7)
    assert isinstance(wet, EnvironmentField)
    still = _run(StaticEnvironment())
    gusty = _run(wet)
    assert gusty != still
    assert gusty[-1][1] < still[-1][1], "rain, denser cool air and a wind must not make the car faster"
    assert gusty[-1][0] < still[-1][0]
    assert _run(conditions_loader.environment_for(tape, bundle.track, seed=7)) == gusty, (
        "replay is deterministic"
    )


def test_static_reference_tape_barely_differs_from_the_static_environment():
    tape = conditions_loader.load_conditions("static-reference")
    env = TapeEnvironment(tape)
    reference = _run(StaticEnvironment())
    isa = _run(env)
    # Same grip and wind; only density differs (1.225 ISA vs the car sketch's 1.2).
    assert env.grip_multiplier(0.0, 0.0) == 1.0
    assert env.headwind_mps(0.0, 1.0, 0.0) == 0.0
    assert isa[-1][1] < reference[-1][1]
    assert isa[-1][1] > 0.97 * reference[-1][1]


def test_conditions_package_does_not_import_learning_or_reward_code():
    for path in CONDITIONS_PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in (
            "afterlap_core.learning",
            "from ..learning",
            "from ..planning",
            "objective",
            "torch",
        ):
            assert forbidden not in text, f"{path.name} touches {forbidden}"
