"""Typed fixture factories.

Every fixture is deterministic and explicitly synthetic. Workers develop
against these while dependencies are under construction; nothing here is a
measurement, and nothing here may be presented as one.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Final

from .base import SCHEMA_VERSION
from .enums import (
    ActionCode,
    CalibrationStatus,
    CheckStatus,
    CoverageStatus,
    DeploymentProfile,
    EligibilityState,
    ExecutionMatch,
    FlagState,
    OperatorAction,
    Provenance,
    Quality,
    RecommendationStatus,
    SessionMode,
)
from .estimate import (
    EstimateQuality,
    IntentionWeights,
    OwnCarEstimate,
    RaceContext,
    RivalBelief,
    StateEstimate,
)
from .lifecycle import (
    CheckpointDefinition,
    ControlLease,
    ExecutionEvent,
    OperatorEvent,
    OutcomeRecord,
)
from .models import (
    FeatureField,
    FeatureManifest,
    RewardManifest,
)
from .planning import (
    CandidatePlan,
    CheckpointOutcome,
    ObjectiveTerms,
    PlanningResult,
    ProfileSegment,
    Recommendation,
    ScenarioOutcome,
    Trigger,
)
from .quantities import IntervalValue, ProbabilityStatement, ScalarValue
from .rules import (
    ApplicableLimits,
    ConstraintCheck,
    ConstraintResult,
    CoverageEntry,
    DetectionLine,
    PowerCurve,
    PowerCurvePoint,
    RuleContext,
    RuleManifest,
    RuleReference,
)
from .session import RuntimeCapabilities, SessionManifest, SessionSnapshot
from .telemetry import ChannelQuality, SourceCapability, TelemetryEvent


def fixture_hash(label: str) -> str:
    """A correctly shaped digest of a fixture label.

    Fixtures need digests that are stable, readable in a failure message and
    the right shape for :data:`~afterlap_contracts.ContentHash`. Hashing the
    label gives all three; a literal like ``sha256:test-loop`` gave only the
    second.
    """
    return f"sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


FIXTURE_SESSION_ID: Final[str] = "synthetic-battle-001"
FIXTURE_CAR_ID: Final[str] = "car-01"
FIXTURE_RIVAL_ID: Final[str] = "car-07"
FIXTURE_RULESET_HASH: Final[str] = fixture_hash("synthetic-pack-v1")
FIXTURE_CREATED_AT: Final[datetime] = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
SYNTHETIC_NOTICE: Final[str] = (
    "Synthetic fixture. Not measured telemetry, not a calibrated car, not evidence of performance."
)


def source_capability(
    *,
    source_id: str = "synthetic-simulator",
    mode: SessionMode = SessionMode.SIMULATION,
    with_energy: bool = True,
) -> SourceCapability:
    """Simulator observation capability.

    ``with_energy=False`` reproduces a public-feed-shaped source that supports
    pace and position but cannot observe battery state.
    """
    channels = ["speed_mps", "progress_m", "lap_distance_m", "gap_ahead_s", "gap_behind_s"]
    limitations = [SYNTHETIC_NOTICE]
    if with_energy:
        channels += ["battery_energy_j", "electrical_power_w", "battery_temperature_k"]
    else:
        limitations.append("no battery-energy channel; precise energy advice is unsupported")
        limitations.append("lateral placement not resolvable from this source")
    return SourceCapability(
        source_id=source_id,
        mode=mode,
        supported_channels=tuple(channels),
        measured_channels=tuple(channels),
        update_rates_hz=dict.fromkeys(channels, 20.0),
        clock_error_s=0.02,
        limitations=tuple(limitations),
    )


def telemetry_event(
    *,
    sequence: int = 1,
    channel: str = "battery_energy_j",
    value: float | None = 2_400_000.0,
    unit: str = "J",
    source_time_s: float = 12.0,
    received_time_s: float = 12.02,
    quality: Quality = Quality.VALID,
) -> TelemetryEvent:
    """Matches ``contracts/schemas/telemetry-event.example.json``."""
    return TelemetryEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"fixture-{sequence:03d}",
        session_id=FIXTURE_SESSION_ID,
        car_id=FIXTURE_CAR_ID,
        sequence=sequence,
        source_time_s=source_time_s,
        received_time_s=received_time_s,
        channel=channel,
        value=value,
        unit=unit,
        provenance=Provenance.SIMULATED,
        quality=quality,
    )


def rule_manifest(*, unknown_conditions: tuple[str, ...] = ()) -> RuleManifest:
    """Synthetic, illustrative rule pack. ``synthetic=True`` is mandatory."""
    reference = RuleReference(
        article="C5.2.7",
        source_id="R02",
        source_url="https://www.fia.com/regulation/category/2182",
        note="Illustrative transcription for testing; not a reviewed machine rule pack.",
    )
    return RuleManifest(
        schema_version=SCHEMA_VERSION,
        ruleset_id="synthetic-pack-v1",
        season_revision="synthetic-2026-r0",
        synthetic=True,
        reviewed=False,
        references=(reference,),
        coverage=(
            CoverageEntry(
                concern="Electrical DC ceiling",
                status=CoverageStatus.IMPLEMENTED_AND_TESTED,
                references=(reference,),
                test_ids=("rules-ceiling-threshold",),
            ),
            CoverageEntry(
                concern="Unknown referenced documents",
                status=CoverageStatus.UNSUPPORTED,
                note="Event supporting documents are not available to this synthetic pack.",
            ),
        ),
        absolute_power_ceiling_w=350_000.0,
        power_curves=(
            PowerCurve(
                curve_id="baseline-speed-curve",
                measurement_bus="ers_k_dc",
                points=(
                    PowerCurvePoint(speed_mps=0.0, max_power_w=350_000.0),
                    PowerCurvePoint(speed_mps=80.0, max_power_w=350_000.0),
                    PowerCurvePoint(speed_mps=95.0, max_power_w=150_000.0),
                    PowerCurvePoint(speed_mps=110.0, max_power_w=0.0),
                ),
            ),
        ),
        battery_energy_min_j=0.0,
        battery_energy_max_j=4_000_000.0,
        recharge_allowance_per_lap_j=8_500_000.0,
        recharge_measurement_bus="cu_k_dc",
        max_power_ramp_w_per_s=700_000.0,
        overtake_profile_extra_power_w=0.0,
        detection_lines=(
            DetectionLine(line_id="detect-1", kind="detection", s_m=1_600.0),
            DetectionLine(line_id="activate-1", kind="activation", s_m=1_900.0),
            DetectionLine(line_id="attack-exit", kind="checkpoint", s_m=2_100.0),
            DetectionLine(line_id="counterattack-exit", kind="checkpoint", s_m=3_500.0),
        ),
        unknown_conditions=unknown_conditions,
    )


def rule_context(
    *,
    eligibility: EligibilityState = EligibilityState.ELIGIBLE_DETECTED,
    unknown_conditions: tuple[str, ...] = (),
    progress_m: float = 1_950.0,
    resolved_at_s: float = 12.2,
) -> RuleContext:
    admissible: tuple[DeploymentProfile, ...]
    if unknown_conditions:
        admissible = ()
    elif eligibility in (EligibilityState.ELIGIBLE_DETECTED, EligibilityState.ACTIVE):
        admissible = (
            DeploymentProfile.HARVEST,
            DeploymentProfile.CONSERVE,
            DeploymentProfile.NEUTRAL,
            DeploymentProfile.PUSH,
            DeploymentProfile.OVERTAKE,
        )
    else:
        admissible = (
            DeploymentProfile.HARVEST,
            DeploymentProfile.CONSERVE,
            DeploymentProfile.NEUTRAL,
            DeploymentProfile.PUSH,
        )
    return RuleContext(
        schema_version=SCHEMA_VERSION,
        session_id=FIXTURE_SESSION_ID,
        season_revision="synthetic-2026-r0",
        ruleset_hash=FIXTURE_RULESET_HASH,
        resolved_at_s=resolved_at_s,
        progress_m=progress_m,
        current_flags=(FlagState.GREEN,),
        eligibility=eligibility,
        eligibility_observed_at_s=11.8,
        active_curve_id="baseline-speed-curve",
        applicable_limits=ApplicableLimits(
            deployment_ceiling_w=350_000.0,
            recovery_ceiling_w=350_000.0,
            battery_energy_min_j=0.0,
            battery_energy_max_j=4_000_000.0,
            recharge_allowance_remaining_j=6_100_000.0,
            max_power_ramp_w_per_s=700_000.0,
            thermal_derate_factor=1.0,
        ),
        admissible_profiles=admissible,
        unknown_conditions=unknown_conditions,
    )


def own_car_estimate(*, energy_j: float | None = 2_400_000.0) -> OwnCarEstimate:
    energy = (
        ScalarValue(
            value=energy_j,
            unit="J",
            provenance=Provenance.SIMULATED,
            quality=Quality.VALID,
            observed_at_s=12.0,
            age_s=0.2,
            standard_deviation=15_000.0,
        )
        if energy_j is not None
        else ScalarValue.missing("J", Provenance.MEASURED, source_id="public-replay")
    )
    return OwnCarEstimate(
        car_id=FIXTURE_CAR_ID,
        progress_m=ScalarValue(
            value=1_950.0, unit="m", provenance=Provenance.SIMULATED, observed_at_s=12.0, age_s=0.2
        ),
        lap_distance_m=ScalarValue(
            value=1_950.0, unit="m", provenance=Provenance.SIMULATED, observed_at_s=12.0, age_s=0.2
        ),
        completed_laps=0,
        speed_mps=ScalarValue(
            value=75.0,
            unit="m/s",
            provenance=Provenance.SIMULATED,
            observed_at_s=12.0,
            age_s=0.2,
            standard_deviation=0.3,
        ),
        acceleration_mps2=ScalarValue(
            value=0.4, unit="m/s^2", provenance=Provenance.ESTIMATED, observed_at_s=12.0, age_s=0.2
        ),
        battery_energy_j=energy,
        battery_energy_interval=(
            None
            if energy_j is not None
            else IntervalValue(
                lower=0.0,
                upper=4_000_000.0,
                unit="J",
                kind="physical_bounds",
                provenance=Provenance.CONFIGURED,
                quality=Quality.DEGRADED,
            )
        ),
        battery_temperature_k=ScalarValue(
            value=318.0, unit="K", provenance=Provenance.SIMULATED, observed_at_s=12.0, age_s=0.2
        ),
        electrical_power_w=ScalarValue(
            value=120_000.0, unit="W", provenance=Provenance.SIMULATED, observed_at_s=12.0, age_s=0.2
        ),
        recharge_spent_this_lap_j=ScalarValue(
            value=2_400_000.0, unit="J", provenance=Provenance.SIMULATED, observed_at_s=12.0, age_s=0.2
        ),
        active_profile_id=DeploymentProfile.NEUTRAL.value,
    )


def rival_belief(
    *,
    slot: str = "ahead_1",
    is_ahead: bool = True,
    gap_s: float = 0.65,
    energy_known: bool = True,
) -> RivalBelief:
    return RivalBelief(
        car_id=FIXTURE_RIVAL_ID,
        slot=slot,
        is_ahead=is_ahead,
        gap_s=ScalarValue(
            value=gap_s if is_ahead else -abs(gap_s),
            unit="s",
            provenance=Provenance.ESTIMATED,
            observed_at_s=12.0,
            age_s=0.2,
            standard_deviation=0.08,
        ),
        gap_m=ScalarValue(
            value=(gap_s if is_ahead else -abs(gap_s)) * 75.0,
            unit="m",
            provenance=Provenance.ESTIMATED,
            observed_at_s=12.0,
            age_s=0.2,
        ),
        relative_speed_mps=ScalarValue(
            value=-0.8, unit="m/s", provenance=Provenance.ESTIMATED, observed_at_s=12.0, age_s=0.2
        ),
        energy_interval_j=(
            IntervalValue(
                lower=1_800_000.0,
                upper=3_400_000.0,
                unit="J",
                kind="quantile",
                coverage=0.9,
                provenance=Provenance.ESTIMATED,
                observed_at_s=12.0,
                age_s=0.2,
            )
            if energy_known
            else None
        ),
        energy_mean_j=(
            ScalarValue(
                value=2_600_000.0,
                unit="J",
                provenance=Provenance.ESTIMATED,
                observed_at_s=12.0,
                age_s=0.2,
                standard_deviation=480_000.0,
            )
            if energy_known
            else None
        ),
        pace_bias_s_per_lap=ScalarValue(
            value=-0.15, unit="s", provenance=Provenance.ESTIMATED, observed_at_s=12.0, age_s=0.2
        ),
        intentions=IntentionWeights(conserve=0.15, normal=0.45, attack=0.10, defend=0.30),
        observation_age_s=0.2,
        lateral_geometry_known=False,
    )


def state_estimate(
    *,
    revision: int = 4,
    cutoff_s: float = 12.2,
    energy_j: float | None = 2_400_000.0,
    with_rivals: bool = True,
) -> StateEstimate:
    rivals = (rival_belief(), rival_belief(slot="behind_1", is_ahead=False, gap_s=1.4)) if with_rivals else ()
    return StateEstimate(
        schema_version=SCHEMA_VERSION,
        session_id=FIXTURE_SESSION_ID,
        revision=revision,
        cutoff_s=cutoff_s,
        created_at_s=cutoff_s,
        own_car=own_car_estimate(energy_j=energy_j),
        rival_beliefs=rivals,
        race_context=RaceContext(
            lap=1,
            total_laps=8,
            remaining_distance_m=ScalarValue(value=39_650.0, unit="m", provenance=Provenance.CONFIGURED),
            track_length_m=5_200.0,
            flag_state=FlagState.GREEN,
            flag_known=True,
            eligibility=EligibilityState.ELIGIBLE_DETECTED,
            eligibility_observed_at_s=11.8,
            position=4,
        ),
        quality=EstimateQuality(
            overall=Quality.VALID if energy_j is not None else Quality.DEGRADED,
            channels=(
                ChannelQuality(
                    channel="battery_energy_j",
                    car_id=FIXTURE_CAR_ID,
                    quality=Quality.VALID if energy_j is not None else Quality.MISSING,
                    last_source_time_s=12.0 if energy_j is not None else None,
                    age_s=0.2 if energy_j is not None else None,
                    expected_period_s=0.05,
                    reason=None if energy_j is not None else "source declares no battery channel",
                ),
            ),
            clock_uncertainty_s=0.02,
            own_energy_capability=energy_j is not None,
        ),
        contributing_event_ids=("fixture-001", "fixture-002"),
    )


def constraint_result(
    *, status: CheckStatus = CheckStatus.PASS, checked_at_s: float = 12.25
) -> ConstraintResult:
    checks: tuple[ConstraintCheck, ...]
    if status is CheckStatus.PASS:
        checks = (
            ConstraintCheck(
                check_id="power_ceiling",
                status=CheckStatus.PASS,
                margin=30_000.0,
                unit="W",
                limit=350_000.0,
                observed=320_000.0,
                at_progress_m=2_000.0,
            ),
            ConstraintCheck(
                check_id="battery_energy_window",
                status=CheckStatus.PASS,
                margin=410_000.0,
                unit="J",
                limit=0.0,
                observed=410_000.0,
                at_progress_m=2_100.0,
            ),
        )
    elif status is CheckStatus.FAIL:
        checks = (
            ConstraintCheck(
                check_id="power_ceiling",
                status=CheckStatus.FAIL,
                margin=-25_000.0,
                unit="W",
                limit=350_000.0,
                observed=375_000.0,
                at_progress_m=2_000.0,
            ),
        )
    else:
        checks = (
            ConstraintCheck(
                check_id="overtake_eligibility",
                status=CheckStatus.UNKNOWN,
                detail="event supporting document not resolved in this synthetic pack",
            ),
        )
    return ConstraintResult(
        schema_version=SCHEMA_VERSION,
        status=status,
        checks=checks,
        ruleset_hash=FIXTURE_RULESET_HASH,
        checked_at_s=checked_at_s,
        checker_version="checker-v1",
        unresolved_conditions=() if status is not CheckStatus.UNKNOWN else ("event_supporting_documents",),
    )


def candidate_plan(
    *,
    plan_id: str = "plan-attack-1",
    intention: ActionCode = ActionCode.ATTACK,
    status: CheckStatus = CheckStatus.PASS,
) -> CandidatePlan:
    objective = ObjectiveTerms(
        objective_version="objective-v1",
        expected_utility=-41.2,
        tail_alpha=0.9,
        cvar_loss=52.8,
        lambda_tail=0.25,
        switch_count=1,
        lambda_switch=0.1,
        final_score=-54.5,
        generation_score=-54.5,
    )
    return CandidatePlan(
        schema_version=SCHEMA_VERSION,
        id=plan_id,
        state_revision=4,
        intention=intention,
        profile_segments=(
            ProfileSegment(
                start_progress_m=1_950.0,
                end_progress_m=2_100.0,
                profile_id=DeploymentProfile.OVERTAKE,
                requested_budget_j=520_000.0,
                harvest_target_j=0.0,
                execution_window_s=1.2,
            ),
            ProfileSegment(
                start_progress_m=2_100.0,
                end_progress_m=3_500.0,
                profile_id=DeploymentProfile.CONSERVE,
                requested_budget_j=180_000.0,
                harvest_target_j=640_000.0,
                execution_window_s=4.0,
            ),
        ),
        scenario_outcomes=(
            ScenarioOutcome(
                scenario_id="scenario-defend",
                weight=0.55,
                checkpoints=(
                    CheckpointOutcome(
                        checkpoint_id="attack-exit",
                        progress_m=2_100.0,
                        elapsed_time_s=2.1,
                        gap_to_reference_s=-0.12,
                        own_energy_j=1_880_000.0,
                        ahead_of_rival=True,
                    ),
                ),
                utility=-38.9,
                elapsed_time_s=21.4,
                final_energy_j=1_640_000.0,
                terminal_value=-12.1,
                terminal_value_source="analytic",
            ),
            ScenarioOutcome(
                scenario_id="scenario-conserve",
                weight=0.45,
                checkpoints=(
                    CheckpointOutcome(
                        checkpoint_id="attack-exit",
                        progress_m=2_100.0,
                        elapsed_time_s=2.0,
                        gap_to_reference_s=-0.31,
                        own_energy_j=1_880_000.0,
                        ahead_of_rival=True,
                    ),
                ),
                utility=-44.0,
                elapsed_time_s=21.9,
                final_energy_j=1_660_000.0,
                terminal_value=-13.4,
                terminal_value_source="analytic",
            ),
        ),
        terminal_target_energy_j=1_600_000.0,
        objective=objective,
        constraint_result=constraint_result(status=status),
        objective_version="objective-v1",
        solver_status="converged",
        solve_duration_ms=42.0,
        probabilities=(
            ProbabilityStatement(
                event_definition="pass_before(checkpoint=attack-exit)",
                checkpoint_id="attack-exit",
                value=0.61,
                raw_frequency=0.61,
                sample_count=64,
                model_version="scenario-ensemble-v1",
                calibration_status=CalibrationStatus.UNCALIBRATED,
            ),
        ),
    )


def planning_result(*, with_candidate: bool = True) -> PlanningResult:
    from .enums import PlanningStatus

    plan = candidate_plan()
    if not with_candidate:
        return PlanningResult(
            schema_version=SCHEMA_VERSION,
            session_id=FIXTURE_SESSION_ID,
            state_revision=4,
            status=PlanningStatus.NO_FEASIBLE_CANDIDATE,
            created_at_s=12.25,
            deadline_s=0.2,
            duration_ms=48.0,
            scenario_count=32,
            candidate_count=5,
            detail="all enumerated intentions failed the independent checker",
        )
    return PlanningResult(
        schema_version=SCHEMA_VERSION,
        session_id=FIXTURE_SESSION_ID,
        state_revision=4,
        status=PlanningStatus.OK,
        created_at_s=12.25,
        deadline_s=0.2,
        duration_ms=51.0,
        accepted=(plan,),
        rejected=(
            candidate_plan(plan_id="plan-defend-1", intention=ActionCode.DEFEND, status=CheckStatus.FAIL),
        ),
        selected_plan_id=plan.id,
        scenario_count=32,
        candidate_count=5,
    )


def recommendation(
    *,
    status: RecommendationStatus = RecommendationStatus.PROPOSED,
    expires_at_s: float = 20.0,
    valid_from_s: float = 12.3,
) -> Recommendation:
    return Recommendation(
        schema_version=SCHEMA_VERSION,
        id="rec-001",
        revision=1,
        session_id=FIXTURE_SESSION_ID,
        state_revision=4,
        plan_id="plan-attack-1",
        status=status,
        action_code=ActionCode.ATTACK,
        display_text="Attack into T7, hold through attack-exit",
        trigger=Trigger(
            kind="checkpoint",
            checkpoint_id="activate-1",
            progress_m=1_900.0,
            description="At the activation line",
        ),
        end_condition="attack-exit checkpoint",
        created_at_s=12.25,
        valid_from_s=valid_from_s,
        expires_at_s=expires_at_s,
        observation_cutoff_s=12.2,
        ruleset_hash=FIXTURE_RULESET_HASH,
        objective_version="objective-v1",
        outcomes=(
            CheckpointOutcome(
                checkpoint_id="attack-exit",
                progress_m=2_100.0,
                elapsed_time_s=2.1,
                own_energy_j=1_880_000.0,
                ahead_of_rival=True,
            ),
        ),
        probabilities=(
            ProbabilityStatement(
                event_definition="ahead_at(checkpoint=counterattack-exit)",
                checkpoint_id="counterattack-exit",
                value=0.48,
                raw_frequency=0.48,
                sample_count=64,
                model_version="scenario-ensemble-v1",
                calibration_status=CalibrationStatus.UNCALIBRATED,
            ),
        ),
        constraint_result=constraint_result(),
        learned_contribution_enabled=False,
        baseline_identity="mpc_baseline",
    )


def control_lease(*, operator_id: str = "engineer-1") -> ControlLease:
    return ControlLease(
        session_id=FIXTURE_SESSION_ID,
        operator_id=operator_id,
        revision=1,
        granted_at_s=10.0,
        expires_at_s=130.0,
    )


def operator_event(*, action: OperatorAction = OperatorAction.SELECT) -> OperatorEvent:
    return OperatorEvent(
        schema_version=SCHEMA_VERSION,
        id="op-001",
        session_id=FIXTURE_SESSION_ID,
        idempotency_key="fixture-idem-001",
        recommendation_id="rec-001",
        expected_revision=1,
        operator_id="engineer-1",
        action=action,
        session_time_s=12.6,
        sequence=41,
        resulting_status=RecommendationStatus.SELECTED,
    )


def execution_event(*, match: ExecutionMatch = ExecutionMatch.MATCHED) -> ExecutionEvent:
    return ExecutionEvent(
        schema_version=SCHEMA_VERSION,
        id="exec-001",
        session_id=FIXTURE_SESSION_ID,
        recommendation_id=None if match is ExecutionMatch.UNSOLICITED else "rec-001",
        source=Provenance.SIMULATED,
        observed_profile_id=DeploymentProfile.OVERTAKE,
        start_time_s=13.1,
        evidence_event_ids=("fixture-010",),
        match_status=match,
        sequence=45,
        delay_from_communication_s=0.5,
    )


def outcome_record() -> OutcomeRecord:
    return OutcomeRecord(
        schema_version=SCHEMA_VERSION,
        id="outcome-001",
        session_id=FIXTURE_SESSION_ID,
        decision_id="rec-001",
        checkpoint=CheckpointDefinition(
            checkpoint_id="counterattack-exit",
            progress_m=3_500.0,
            description="Retained-position evaluation point",
        ),
        evaluation_horizon_s=30.0,
        event_observed=True,
        elapsed_time_s=18.4,
        energy_j=1_610_000.0,
        position=3,
        gap_to_reference_s=-0.42,
        provenance=Provenance.SIMULATED,
    )


def session_manifest(*, mode: SessionMode = SessionMode.SIMULATION) -> SessionManifest:
    return SessionManifest(
        schema_version=SCHEMA_VERSION,
        id=FIXTURE_SESSION_ID,
        mode=mode,
        track_hash=fixture_hash("test-loop"),
        car_hashes={
            FIXTURE_CAR_ID: fixture_hash("synthetic-car"),
            FIXTURE_RIVAL_ID: fixture_hash("synthetic-car"),
        },
        ruleset_hash=FIXTURE_RULESET_HASH,
        objective_hash=fixture_hash("objective-v1"),
        seed=42,
        created_at=FIXTURE_CREATED_AT,
        source_capabilities=(source_capability(mode=mode),),
        scenario_id="two-straight-counterattack",
        synthetic=True,
        label="Synthetic counterattack fixture",
    )


def session_snapshot(*, mode: SessionMode = SessionMode.SIMULATION) -> SessionSnapshot:
    return SessionSnapshot(
        schema_version=SCHEMA_VERSION,
        session_id=FIXTURE_SESSION_ID,
        revision=7,
        last_sequence=100,
        server_time=FIXTURE_CREATED_AT,
        session_time_s=12.3,
        status="running",
        manifest=session_manifest(mode=mode),
        estimate=state_estimate(),
        rule_context=rule_context(),
        recommendation=recommendation(),
        lease=control_lease(),
        capabilities=RuntimeCapabilities(
            notes=(SYNTHETIC_NOTICE,),
        ),
    )


def reward_manifest() -> RewardManifest:
    """objective-v1 defaults from ``learning/training.example.json``."""
    return RewardManifest(
        revision="objective-v1",
        elapsed_second_penalty=1.0,
        instruction_change_penalty=0.1,
        finish_position_penalty=30.0,
        terminal_failure_penalty=1200.0,
        potential_reference_time_scale_s=100.0,
        gamma=0.9966722160545233,
        maximum_supported_field_size=20,
        maximum_charged_instruction_changes_per_s=1.0,
    )


def minimal_feature_manifest(value_count: int = 4) -> FeatureManifest:
    """Small manifest for contract tests; the real one is built by the learning package."""
    return FeatureManifest(
        schema_version=SCHEMA_VERSION,
        revision="fixture-v0",
        value_count=value_count,
        observation_size=2 * value_count,
        fields=tuple(
            FeatureField(index=i, name=f"field_{i}", unit="1", offset=0.0, scale=1.0)
            for i in range(value_count)
        ),
        action_size=2,
        policy_interval_s=1.0,
        preference_window_s=10.0,
    )


__all__ = [
    "FIXTURE_CAR_ID",
    "FIXTURE_CREATED_AT",
    "FIXTURE_RIVAL_ID",
    "FIXTURE_RULESET_HASH",
    "FIXTURE_SESSION_ID",
    "SYNTHETIC_NOTICE",
    "candidate_plan",
    "constraint_result",
    "control_lease",
    "execution_event",
    "fixture_hash",
    "minimal_feature_manifest",
    "operator_event",
    "outcome_record",
    "own_car_estimate",
    "planning_result",
    "recommendation",
    "reward_manifest",
    "rival_belief",
    "rule_context",
    "rule_manifest",
    "session_manifest",
    "session_snapshot",
    "source_capability",
    "state_estimate",
    "telemetry_event",
]
