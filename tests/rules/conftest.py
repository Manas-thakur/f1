"""Builders for the rules tests.

Every expected value in these tests is computed arithmetically in the test
itself. These helpers only assemble contract objects; they never compute a
limit, a margin or an energy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CandidatePlan,
    CheckStatus,
    ObjectiveTerms,
    ProfileSegment,
    fixtures,
)
from afterlap_core.rules import CheckerState, SpeedProfile, SpeedSample, load_rule_pack

if TYPE_CHECKING:
    from collections.abc import Sequence

TRACK_LENGTH_M = 5_000.0
"""Synthetic track length used by every rules test."""


def objective_terms() -> ObjectiveTerms:
    return ObjectiveTerms(
        objective_version="objective-v1",
        expected_utility=0.0,
        tail_alpha=0.9,
        cvar_loss=0.0,
        lambda_tail=0.0,
        switch_count=0,
        lambda_switch=0.0,
        final_score=0.0,
    )


def make_plan(
    segments: Sequence[ProfileSegment],
    *,
    plan_id: str = "plan-under-test",
    intention: ActionCode = ActionCode.ATTACK,
    declared_status: CheckStatus = CheckStatus.PASS,
) -> CandidatePlan:
    """Assemble a candidate plan.

    ``declared_status`` is the verdict the *plan* carries. The independent
    checker must ignore it entirely; several tests rely on that.
    """
    return CandidatePlan(
        schema_version=SCHEMA_VERSION,
        id=plan_id,
        state_revision=1,
        intention=intention,
        profile_segments=tuple(segments),
        objective=objective_terms(),
        constraint_result=fixtures.constraint_result(status=declared_status),
        objective_version="objective-v1",
        solver_status="converged",
    )


def constant_speed(speed_mps: float) -> SpeedProfile:
    return SpeedProfile(samples=(SpeedSample(progress_m=0.0, speed_mps=speed_mps),))


def two_phase_speed(first_speed_mps: float, break_progress_m: float, second_speed_mps: float) -> SpeedProfile:
    """A speed profile that steps from one constant speed to another."""
    return SpeedProfile(
        samples=(
            SpeedSample(progress_m=0.0, speed_mps=first_speed_mps),
            SpeedSample(progress_m=break_progress_m, speed_mps=second_speed_mps),
        ),
        step=True,
    )


def checker_state(
    *,
    session_time_s: float,
    progress_m: float,
    battery_energy_j: float,
    speed_profile: SpeedProfile,
    current_power_w: float = 0.0,
    recharge_used_this_lap_j: float = 0.0,
    driver_reaction_time_s: float = 0.6,
    charge_bus_efficiency: float = 1.0,
    discharge_efficiency: float = 1.0,
) -> CheckerState:
    return CheckerState(
        session_time_s=session_time_s,
        progress_m=progress_m,
        battery_energy_j=battery_energy_j,
        speed_profile=speed_profile,
        track_length_m=TRACK_LENGTH_M,
        current_power_w=current_power_w,
        recharge_used_this_lap_j=recharge_used_this_lap_j,
        driver_reaction_time_s=driver_reaction_time_s,
        charge_bus_efficiency=charge_bus_efficiency,
        discharge_efficiency=discharge_efficiency,
    )


def checks_by_id(result) -> dict[str, object]:
    return {check.check_id: check for check in result.checks}


@pytest.fixture(scope="session")
def pack_v1():
    return load_rule_pack("synthetic-pack-v1")


@pytest.fixture(scope="session")
def pack_v2():
    return load_rule_pack("synthetic-pack-v2-strict")


@pytest.fixture(scope="session")
def pack_unknown():
    return load_rule_pack("synthetic-pack-unknown")
