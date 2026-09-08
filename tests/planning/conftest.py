"""Shared fixtures for the planning tests.

Everything here is synthetic and deterministic. Nothing is a measurement.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    DeploymentProfile,
    EligibilityState,
    IntervalValue,
    Provenance,
    Quality,
    RivalIntention,
    RuleContext,
    RuleManifest,
    ScalarValue,
    StateEstimate,
    fixtures,
)
from afterlap_core.planning import (
    FrameSegment,
    ObjectiveManifest,
    PlanFrame,
    PlannerConfig,
    PlanningWorld,
    PlanScenario,
    load_objective,
    load_planner_config,
)

TRACK_LENGTH_M = 5_200.0
"""``configs/tracks/test-loop.yaml``. Synthetic sketch, not a surveyed circuit."""


@pytest.fixture(scope="session")
def config() -> PlannerConfig:
    return load_planner_config()


@pytest.fixture(scope="session")
def objective() -> ObjectiveManifest:
    return load_objective()


@pytest.fixture(scope="session")
def manifest() -> RuleManifest:
    return fixtures.rule_manifest()


@pytest.fixture(scope="session")
def world() -> PlanningWorld:
    return PlanningWorld.from_scenario("two-straight-counterattack", seed=20260908)


@pytest.fixture
def estimate() -> StateEstimate:
    return fixtures.state_estimate()


@pytest.fixture
def context() -> RuleContext:
    return fixtures.rule_context()


def solo_estimate(*, remaining_distance_m: float = 16_000.0) -> StateEstimate:
    """An estimate with **no rival in contention**.

    The hand-computed allocation test needs the position term to be genuinely
    absent, not merely small: with nobody to pass or defend against there is no
    position to win or lose inside the horizon, and the loss reduces to the
    time/energy trade whose stationary point can be written down in closed form.
    """
    base = fixtures.state_estimate(with_rivals=False)
    race = base.race_context.model_copy(
        update={
            "remaining_distance_m": ScalarValue(
                value=remaining_distance_m, unit="m", provenance=Provenance.CONFIGURED
            )
        }
    )
    return base.model_copy(update={"race_context": race})


def estimate_with(
    *,
    energy_j: float | None = 2_400_000.0,
    speed_mps: float = 75.0,
    progress_m: float = 1_950.0,
    active_profile: str | None = DeploymentProfile.NEUTRAL.value,
    rival_energy_known: bool = True,
    electrical_power_w: float = 120_000.0,
    recharge_spent_this_lap_j: float = 2_400_000.0,
) -> StateEstimate:
    """A synthetic estimate with the fields the planning tests vary."""
    base = fixtures.state_estimate(energy_j=energy_j)
    own = base.own_car.model_copy(
        update={
            "speed_mps": base.own_car.speed_mps.model_copy(update={"value": speed_mps}),
            "progress_m": base.own_car.progress_m.model_copy(update={"value": progress_m}),
            "lap_distance_m": base.own_car.lap_distance_m.model_copy(update={"value": progress_m}),
            "active_profile_id": active_profile,
            "electrical_power_w": base.own_car.electrical_power_w.model_copy(
                update={"value": electrical_power_w}
            ),
            "recharge_spent_this_lap_j": base.own_car.recharge_spent_this_lap_j.model_copy(
                update={"value": recharge_spent_this_lap_j}
            ),
        }
    )
    rivals = base.rival_beliefs
    if not rival_energy_known:
        rivals = tuple(
            rival.model_copy(update={"energy_mean_j": None, "energy_interval_j": None}) for rival in rivals
        )
    return base.model_copy(update={"own_car": own, "rival_beliefs": rivals})


def context_with(
    *,
    eligibility: EligibilityState = EligibilityState.ELIGIBLE_DETECTED,
    unknown_conditions: tuple[str, ...] = (),
    admissible: tuple[DeploymentProfile, ...] | None = None,
    thermal_derate_factor: float | None = 1.0,
    deployment_ceiling_w: float | None = 350_000.0,
    ruleset_hash: str | None = None,
) -> RuleContext:
    """A resolved rule context with the fields the planning tests vary."""
    base = fixtures.rule_context(eligibility=eligibility, unknown_conditions=unknown_conditions)
    limits = base.applicable_limits.model_copy(
        update={
            "thermal_derate_factor": thermal_derate_factor,
            "deployment_ceiling_w": deployment_ceiling_w,
        }
    )
    update: dict[str, object] = {"applicable_limits": limits}
    if admissible is not None:
        update["admissible_profiles"] = admissible
    if ruleset_hash is not None:
        update["ruleset_hash"] = ruleset_hash
    return base.model_copy(update=update)


def single_segment_frame(
    config: PlannerConfig,
    *,
    length_m: float = 300.0,
    speed_mps: float = 75.0,
    profile: DeploymentProfile = DeploymentProfile.NEUTRAL,
    initial_energy_j: float = 2_400_000.0,
    max_deploy_j: float = 700_000.0,
    max_harvest_j: float = 0.0,
    continuation_availability: float = 0.8,
    terminal_target_energy_j: float | None = None,
    start_progress_m: float = 2_000.0,
) -> PlanFrame:
    """One instruction slot with a hand-chosen feasible box.

    Built directly rather than through :func:`build_frame` so the arithmetic in
    the hand-computed test has nothing hidden in it: the segment length, the
    held speed and the drag constant are all visible in the test.
    """
    drag = config.surrogate.drag_constant_kg_per_m
    duration_s = length_m / speed_mps
    segment = FrameSegment(
        index=0,
        start_progress_m=start_progress_m,
        end_progress_m=start_progress_m + length_m,
        profile=profile,
        speed_mps=speed_mps,
        duration_s=duration_s,
        execution_window_s=min(duration_s, float(config.execution.instruction_execution_window_s.value)),
        lap_index=int(start_progress_m // TRACK_LENGTH_M),
        regulatory_ceiling_w=350_000.0,
        derated_ceiling_w=350_000.0,
        max_deploy_j=max_deploy_j,
        max_harvest_j=max_harvest_j,
        beta=speed_mps / (drag * length_m),
    )
    return PlanFrame(
        segments=(segment,),
        start_progress_m=start_progress_m,
        end_progress_m=start_progress_m + length_m,
        lead_time_s=float(config.execution.instruction_lead_time_s.value),
        horizon_s=duration_s,
        speed_mps=speed_mps,
        initial_energy_j=initial_energy_j,
        energy_floor_j=0.0,
        energy_ceiling_j=4_000_000.0,
        terminal_target_energy_j=terminal_target_energy_j,
        charge_efficiency=float(config.surrogate.charge_efficiency.value),
        recharge_allowance_per_lap_j=8_500_000.0,
        recharge_used_this_lap_j=0.0,
        max_power_ramp_w_per_s=700_000.0,
        current_power_w=0.0,
        min_speed_mps=float(config.surrogate.min_speed_mps.value),
        drivetrain_efficiency=float(config.surrogate.drivetrain_efficiency.value),
        harvest_opportunity_coefficient=float(config.surrogate.harvest_opportunity_coefficient.value),
        continuation_availability=continuation_availability,
        checkpoint_progress_m=(),
    )


def scenario(
    scenario_id: str,
    *,
    weight: float = 1.0,
    reserve_j: float = 0.0,
    pace_gain_s: float = 0.0,
    intention: RivalIntention = RivalIntention.NORMAL,
    energy_known: bool = True,
) -> PlanScenario:
    return PlanScenario(
        scenario_id=scenario_id,
        weight=weight,
        rival_reserve_j=reserve_j,
        rival_pace_gain_s=pace_gain_s,
        intention=intention,
        energy_known=energy_known,
        source="test",
    )


def interval_only_estimate() -> StateEstimate:
    """A rival whose energy is a nominal 90 % quantile interval with no mean.

    This is the shape A05's filter publishes, and A05 measures its empirical
    coverage at 0.7885 against that 90 % label.
    """
    base = fixtures.state_estimate()
    rivals = tuple(rival.model_copy(update={"energy_mean_j": None}) for rival in base.rival_beliefs)
    return base.model_copy(update={"rival_beliefs": rivals})


def no_energy_capability_estimate() -> StateEstimate:
    """A session that declares it cannot observe own battery energy.

    ``battery_energy_j.value`` is ``None`` and the interval is a physical bound,
    exactly as A05's handoff describes the degraded case.
    """
    base = fixtures.state_estimate(energy_j=None)
    assert base.quality.own_energy_capability is False
    return base


def wide_energy_estimate() -> StateEstimate:
    """A rival whose stored energy is only bounded, never identified."""
    base = fixtures.state_estimate()
    rivals = tuple(
        rival.model_copy(
            update={
                "energy_mean_j": None,
                "energy_interval_j": IntervalValue(
                    lower=0.0,
                    upper=4_000_000.0,
                    unit="J",
                    kind="physical_bounds",
                    provenance=Provenance.CONFIGURED,
                    quality=Quality.DEGRADED,
                ),
            }
        )
        for rival in base.rival_beliefs
    )
    return base.model_copy(update={"rival_beliefs": rivals})


__all__ = [
    "SCHEMA_VERSION",
    "TRACK_LENGTH_M",
    "context_with",
    "estimate_with",
    "interval_only_estimate",
    "no_energy_capability_estimate",
    "scenario",
    "single_segment_frame",
    "solo_estimate",
    "wide_energy_estimate",
]
