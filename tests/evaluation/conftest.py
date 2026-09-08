"""Fixtures for the evaluation suite.

Imported relatively (``from .conftest import ...``) as decision D-03 in
``handoffs/decisions.md`` requires; a bare top-level ``conftest`` module would
shadow another worker's file under pytest's prepend import mode.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from afterlap_core.evaluation.independent_ledger import (
    RecordedTrajectory,
    record_trajectory,
)
from afterlap_core.simulation import Simulator, load_bundle
from afterlap_core.simulation.config import ScenarioBundle

RECORD_STEPS = 400
RECORD_DT_S = 0.02


@pytest.fixture(scope="session")
def oval_bundle() -> ScenarioBundle:
    """``test-oval`` fixture: the simulator splits almost no step here."""
    return load_bundle("oval-defend-hold")


@pytest.fixture(scope="session")
def loop_bundle() -> ScenarioBundle:
    """``test-loop`` fixture: the plan's example counterattack scenario."""
    return load_bundle("two-straight-counterattack")


def _record(bundle: ScenarioBundle, car_id: str, steps: int) -> RecordedTrajectory:
    simulator = Simulator()
    simulator.reset(bundle)
    return record_trajectory(simulator, car_id=car_id, dt_s=RECORD_DT_S, steps=steps)


@pytest.fixture(scope="session")
def oval_trajectory(oval_bundle: ScenarioBundle) -> RecordedTrajectory:
    return _record(oval_bundle, oval_bundle.scenario.ego_car_id, RECORD_STEPS)


@pytest.fixture(scope="session")
def loop_trajectory(loop_bundle: ScenarioBundle) -> RecordedTrajectory:
    return _record(loop_bundle, loop_bundle.scenario.ego_car_id, RECORD_STEPS)


@pytest.fixture(scope="session")
def harvesting_trajectory(oval_bundle: ScenarioBundle) -> RecordedTrajectory:
    """A run long enough to reach the oval's first corner and actually harvest.

    The short fixtures above never brake, so their CU-K ledger is exactly zero
    and a corruption of it would be a no-op. This one records 24 s, past the
    corner entry at s = 1544 m.
    """
    return _record(oval_bundle, oval_bundle.scenario.ego_car_id, 1200)


@pytest.fixture(scope="session")
def record_trajectory_for() -> Callable[[ScenarioBundle, str, int], RecordedTrajectory]:
    return _record
