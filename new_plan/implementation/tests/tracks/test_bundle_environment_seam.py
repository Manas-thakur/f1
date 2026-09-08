"""A scenario names its conditions; the bundle carries the resolved environment.

The session factory resolves ``scenario.conditions_id`` into an
``EnvironmentField`` and stores it on the bundle. The engine then uses it
without every caller having to thread an ``environment`` argument through.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from afterlap_core.simulation import Simulator
from afterlap_core.simulation.config import ScenarioBundle, load_bundle, load_scenario
from afterlap_core.simulation.track_source import DEFAULT_ENVIRONMENT, StaticEnvironment


def test_scenario_conditions_and_event_ids_default_to_none_and_are_validated():
    scenario = load_scenario("two-straight-counterattack")
    assert scenario.conditions_id is None and scenario.event_id is None
    with pytest.raises(ValidationError):
        scenario.model_copy(update={"conditions_id": "Not Valid"}).model_validate(
            scenario.model_copy(update={"conditions_id": "Not Valid"}).model_dump()
        )


def test_bundle_environment_reaches_the_world_when_no_override_is_given():
    shipped = load_bundle("two-straight-counterattack")
    marker = StaticEnvironment()
    bundle = ScenarioBundle(
        scenario=shipped.scenario,
        track=shipped.track,
        car_configs=shipped.car_configs,
        environment=marker,
        environment_hash="a" * 64,
    )
    sim = Simulator().reset(bundle, seed=1)
    assert sim.world.environment is marker
    assert Simulator().reset(shipped, seed=1).world.environment is DEFAULT_ENVIRONMENT


def test_an_explicit_environment_argument_still_wins():
    shipped = load_bundle("two-straight-counterattack")
    bundle = shipped.model_copy(update={"environment": StaticEnvironment()})
    override = StaticEnvironment()
    assert Simulator().reset(bundle, seed=1, environment=override).world.environment is override


def test_the_conditions_hash_is_part_of_the_bundle_identity():
    shipped = load_bundle("two-straight-counterattack")
    with_tape = shipped.model_copy(update={"environment_hash": "b" * 64})
    assert with_tape.bundle_hash != shipped.bundle_hash
