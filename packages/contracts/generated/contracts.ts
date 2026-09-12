// Generated from afterlap_contracts. Do not edit by hand.
// Regenerate with: python -m afterlap_contracts.schema_export
/* eslint-disable */


export const SCHEMA_VERSION = "1.0" as const;

export type ActionCode = "maintain" | "prepare_attack" | "attack" | "defend" | "recover" | "withdraw_advice";

export interface ApiError {
  "code": ErrorCode;
  "message": string;
  "retryable": boolean;
  "request_id": string;
  "details"?: Record<string, unknown>;
}

export interface ApplicableLimits {
  "deployment_ceiling_w"?: number | null;
  "recovery_ceiling_w"?: number | null;
  "battery_energy_min_j"?: number | null;
  "battery_energy_max_j"?: number | null;
  "recharge_allowance_remaining_j"?: number | null;
  "max_power_ramp_w_per_s"?: number | null;
  "thermal_derate_factor"?: number | null;
}

export type ApprovalStatus = "unevaluated" | "candidate" | "rejected" | "approved";

export interface BenchmarkComparison {
  "controller": string;
  "reference": string;
  "metric": string;
  "unit": string;
  "difference_mean": number;
  "ci_low": number;
  "ci_high": number;
  "coverage": number;
  "scenario_count": number;
  "seed_count": number;
  "favours_controller": boolean;
}

export interface CalibrationReport {
  "event_definition": string;
  "status": CalibrationStatus;
  "brier_score"?: number | null;
  "log_loss"?: number | null;
  "bin_counts"?: Array<number>;
  "bin_predicted"?: Array<number>;
  "bin_observed"?: Array<number>;
  "support_count"?: number;
}

export type CalibrationStatus = "uncalibrated" | "calibrated" | "unavailable";

export interface CandidatePlan {
  "schema_version": "1.0";
  "id": string;
  "state_revision": number;
  "intention": ActionCode;
  "profile_segments": Array<ProfileSegment>;
  "scenario_outcomes"?: Array<ScenarioOutcome>;
  "terminal_target_energy_j"?: number | null;
  "objective": ObjectiveTerms;
  "constraint_result": ConstraintResult;
  "model_version"?: string | null;
  "objective_version": string;
  "solver_status"?: string | null;
  "solve_duration_ms"?: number | null;
  "reason_codes"?: Array<ReasonCode>;
  "probabilities"?: Array<ProbabilityStatement>;
}

export type CapabilityState = "available" | "degraded" | "unavailable";

export interface ChannelQuality {
  "channel": string;
  "car_id"?: string | null;
  "quality": Quality;
  "last_source_time_s"?: number | null;
  "age_s"?: number | null;
  "expected_period_s"?: number | null;
  "reason"?: string | null;
}

export type CheckStatus = "pass" | "fail" | "unknown";

export interface CheckpointDefinition {
  "checkpoint_id": string;
  "progress_m": number;
  "description"?: string | null;
}

export interface CheckpointOutcome {
  "checkpoint_id": string;
  "progress_m": number;
  "elapsed_time_s"?: number | null;
  "gap_to_reference_s"?: number | null;
  "own_energy_j"?: number | null;
  "position"?: number | null;
  "ahead_of_rival"?: boolean | null;
}

export interface ConditionsSummary {
  "conditions_id": string;
  "description"?: string | null;
  "source": string;
  "available": boolean;
  "content_hash"?: string | null;
  "sample_count"?: number | null;
  "duration_s"?: number | null;
  "rainfall_minutes"?: number | null;
  "session_key"?: number | null;
  "altitude_m"?: number | null;
  "altitude_source"?: string | null;
  "permission"?: string | null;
  "retrieved_at"?: string | null;
  "time_origin_utc"?: string | null;
  "gust_enabled"?: boolean;
  "frozen_tape_available"?: boolean;
  "unavailable_reason"?: string | null;
}

export interface ConstraintCheck {
  "check_id": string;
  "status": CheckStatus;
  "margin"?: number | null;
  "unit"?: string | null;
  "limit"?: number | null;
  "observed"?: number | null;
  "at_progress_m"?: number | null;
  "at_session_time_s"?: number | null;
  "references"?: Array<RuleReference>;
  "detail"?: string | null;
}

export interface ConstraintResult {
  "schema_version": "1.0";
  "status": CheckStatus;
  "checks"?: Array<ConstraintCheck>;
  "ruleset_hash": string;
  "checked_at_s": number;
  "checker_version": string;
  "unresolved_conditions"?: Array<string>;
}

export interface ControlLease {
  "session_id": string;
  "operator_id": string;
  "revision": number;
  "granted_at_s": number;
  "expires_at_s": number;
}

export interface CoverageEntry {
  "concern": string;
  "status": CoverageStatus;
  "references"?: Array<RuleReference>;
  "test_ids"?: Array<string>;
  "note"?: string | null;
}

export type CoverageStatus = "implemented_and_tested" | "review_required" | "not_applicable" | "unsupported";

export type DeploymentProfile = "harvest" | "conserve" | "neutral" | "push" | "overtake";

export interface DetectionLine {
  "line_id": string;
  "kind": string;
  "s_m": number;
}

export type EligibilityState = "unknown" | "ineligible" | "eligible_detected" | "active";

export type ErrorCode = "stale_revision" | "idempotency_conflict" | "recommendation_expired" | "recommendation_invalidated" | "capability_unavailable" | "lease_not_held" | "mode_not_permitted" | "not_found" | "validation_failed" | "persistence_degraded" | "spool_exhausted" | "internal";

export interface EstimateQuality {
  "overall": Quality;
  "channels"?: Array<ChannelQuality>;
  "clock_uncertainty_s": number;
  "own_energy_capability"?: boolean;
  "residual_alarm"?: boolean;
  "notes"?: Array<string>;
}

export interface EstimateUpdatedPayload {
  "event_type"?: "estimate_updated";
  "estimate": StateEstimate;
}

export interface EventOverlaySummary {
  "event_id": string;
  "review_status": string;
  "reviewer_count": number;
  "confirmed": boolean;
  "overlay_hash": string;
  "ruleset_hash": string;
  "detection_line_count": number;
  "activation_line_count": number;
  "standard_curve_points": number;
  "overtake_curve_points": number;
  "unknown_fields"?: Array<string>;
  "fia_document_hashes"?: Array<string>;
  "effective_values_resolved"?: Array<string>;
  "effective_values_unknown"?: Array<string>;
}

export interface ExecutionEvent {
  "schema_version": "1.0";
  "id": string;
  "session_id": string;
  "recommendation_id"?: string | null;
  "source": Provenance;
  "observed_profile_id": DeploymentProfile;
  "start_time_s": number;
  "end_time_s"?: number | null;
  "evidence_event_ids"?: Array<string>;
  "match_status": ExecutionMatch;
  "sequence": number;
  "delay_from_communication_s"?: number | null;
}

export type ExecutionMatch = "matched" | "different_profile" | "late" | "unsolicited";

export interface ExecutionObservedPayload {
  "event_type"?: "execution_observed";
  "execution": ExecutionEvent;
}

export interface ExperimentJob {
  "schema_version": "1.0";
  "id": string;
  "manifest_hash": string;
  "status": JobStatus;
  "progress"?: number;
  "created_at": string;
  "started_at"?: string | null;
  "finished_at"?: string | null;
  "report_hash"?: string | null;
  "failure"?: string | null;
  "partial_results"?: boolean;
}

export interface ExperimentProgressPayload {
  "event_type"?: "experiment_progress";
  "experiment_id": string;
  "status": string;
  "progress": number;
  "detail"?: string | null;
}

export type FailureCategory = "energy_depletion" | "missed_response" | "poor_opponent_belief" | "unknown_eligibility" | "infeasible_projection" | "planner_timeout" | "model_support_rejection" | "lost_communication" | "simulator_defect" | "infrastructure_failure";

export interface FeatureField {
  "index": number;
  "name": string;
  "unit": string;
  "offset": number;
  "scale": number;
  "clip_low"?: number;
  "clip_high"?: number;
  "maskable"?: boolean;
  "provenance_note"?: string | null;
}

export interface FeatureSummary {
  "start_finish_s_m": number;
  "sector_count": number;
  "corner_count": number;
  "corner_ids"?: Array<string>;
  "pit_lane_excluded"?: boolean;
}

export type FlagState = "green" | "yellow" | "double_yellow" | "safety_car" | "virtual_safety_car" | "red" | "chequered" | "unknown";

export interface HeartbeatPayload {
  "event_type"?: "heartbeat";
  "server_uptime_s": number;
}

export interface IntentionWeights {
  "conserve": number;
  "normal": number;
  "attack": number;
  "defend": number;
}

export interface IntervalValue {
  "lower": number | null;
  "upper": number | null;
  "unit": string;
  "kind": "physical_bounds" | "quantile" | "confidence_interval";
  "coverage"?: number | null;
  "provenance": Provenance;
  "quality"?: Quality;
  "observed_at_s"?: number | null;
  "age_s"?: number | null;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface LearnedContribution {
  "enabled": boolean;
  "bundle_id"?: string | null;
  "weights_hash"?: string | null;
  "in_support"?: boolean;
  "support_reason"?: string | null;
  "continuation_value"?: number | null;
  "disagreement"?: number | null;
  "member_count"?: number | null;
  "calibrator_id"?: string | null;
  "calibration_status"?: CalibrationStatus;
  "baseline_identity": string;
  "reason_codes"?: Array<ReasonCode>;
}

export interface ModelManifest {
  "schema_version": "1.0";
  "id": string;
  "algorithm": string;
  "weights_hash": string;
  "artifact_hashes"?: Record<string, string>;
  "feature_schema_hash": string;
  "normalizer_hash"?: string | null;
  "rule_family": string;
  "reward_revision": string;
  "continuation_controller"?: string | null;
  "training_data_hash"?: string | null;
  "training_code_revision"?: string | null;
  "library_versions"?: Record<string, string>;
  "supported_scenario_families"?: Array<string>;
  "ruleset_hash"?: string | null;
  "supported_track_ids"?: Array<string>;
  "track_package_hashes"?: Record<string, string>;
  "supported_conditions_ids"?: Array<string>;
  "support_thresholds"?: SupportThresholds | null;
  "approval_status"?: ApprovalStatus;
  "benchmark_report_hash"?: string | null;
  "promotion_policy"?: PromotionPolicy;
  "created_at": string;
  "model_card"?: string | null;
}

export interface ObjectiveTerms {
  "objective_version": string;
  "expected_utility": number;
  "tail_alpha": number;
  "cvar_loss": number;
  "lambda_tail": number;
  "switch_count": number;
  "lambda_switch": number;
  "disagreement_penalty"?: number;
  "generation_score"?: number | null;
  "final_score": number;
}

export type OperatorAction = "select" | "reject" | "mark_communicated";

export interface OperatorEvent {
  "schema_version": "1.0";
  "id": string;
  "session_id": string;
  "idempotency_key": string;
  "recommendation_id"?: string | null;
  "expected_revision": number;
  "operator_id": string;
  "action": OperatorAction;
  "reason"?: string | null;
  "session_time_s": number;
  "sequence": number;
  "resulting_status"?: RecommendationStatus | null;
}

export interface OutcomeRange {
  "checkpoint_id": string;
  "progress_m": number;
  "scenario_count": number;
  "weight_covered": number;
  "elapsed_time_s"?: IntervalValue | null;
  "gap_to_reference_s"?: IntervalValue | null;
  "own_energy_j"?: IntervalValue | null;
  "ahead_of_rival_weight"?: number | null;
}

export interface OwnCarEstimate {
  "car_id": string;
  "progress_m": ScalarValue;
  "lap_distance_m": ScalarValue;
  "completed_laps": number;
  "speed_mps": ScalarValue;
  "acceleration_mps2": ScalarValue;
  "battery_energy_j": ScalarValue;
  "battery_energy_interval"?: IntervalValue | null;
  "battery_temperature_k": ScalarValue;
  "electrical_power_w": ScalarValue;
  "recharge_spent_this_lap_j": ScalarValue;
  "tyre_pace_residual_s_per_lap"?: ScalarValue | null;
  "active_profile_id"?: string | null;
}

export type PlanningStatus = "ok" | "no_feasible_candidate" | "deadline_exceeded" | "input_unavailable" | "rules_unknown" | "solver_unavailable";

export interface PowerCurve {
  "curve_id": string;
  "measurement_bus": string;
  "points": Array<PowerCurvePoint>;
  "applies_to_profiles"?: Array<DeploymentProfile>;
  "sector_ids"?: Array<string>;
}

export interface PowerCurvePoint {
  "speed_mps": number;
  "max_power_w": number;
}

export interface ProbabilityStatement {
  "event_definition": string;
  "checkpoint_id"?: string | null;
  "horizon_s"?: number | null;
  "value"?: number | null;
  "raw_frequency"?: number | null;
  "sample_count"?: number | null;
  "model_version"?: string | null;
  "calibration_status"?: CalibrationStatus;
}

export interface ProfileSegment {
  "start_progress_m": number;
  "end_progress_m": number;
  "profile_id": DeploymentProfile;
  "requested_budget_j": number;
  "harvest_target_j"?: number;
  "execution_window_s": number;
}

export interface PromotionPolicy {
  "enabled"?: boolean;
  "minimum_benefit"?: number | null;
  "benefit_metric"?: string | null;
  "downside_noninferiority_limit"?: number | null;
  "latency_limit_ms"?: number | null;
  "frozen_at"?: string | null;
  "rationale"?: string | null;
}

export type Provenance = "measured" | "estimated" | "configured" | "simulated";

export type Quality = "valid" | "degraded" | "stale" | "missing" | "invalid";

export interface QualityChangedPayload {
  "event_type"?: "quality_changed";
  "channels"?: Array<ChannelQuality>;
  "message"?: string | null;
}

export interface RaceContext {
  "lap": number;
  "total_laps"?: number | null;
  "remaining_distance_m": ScalarValue;
  "track_length_m": number;
  "flag_state"?: FlagState;
  "flag_known"?: boolean;
  "eligibility"?: EligibilityState;
  "eligibility_observed_at_s"?: number | null;
  "position"?: number | null;
}

export type ReasonCode = "reserve_for_counterattack" | "insufficient_execution_lead" | "eligibility_unknown" | "energy_floor" | "small_expected_improvement" | "thermal_derate" | "recharge_allowance_exhausted" | "power_ceiling_exceeded" | "rival_energy_unknown" | "gap_too_large" | "expected_pass_retained" | "learned_model_out_of_support" | "learned_model_disabled" | "baseline_fallback" | "own_energy_unavailable" | "stale_observations" | "solver_timeout" | "switch_cost_dominates";

export interface Recommendation {
  "schema_version": "1.0";
  "id": string;
  "revision": number;
  "session_id": string;
  "state_revision": number;
  "plan_id"?: string | null;
  "status": RecommendationStatus;
  "action_code": ActionCode;
  "display_text": string;
  "trigger": Trigger;
  "end_condition": string;
  "created_at_s": number;
  "valid_from_s": number;
  "expires_at_s": number;
  "observation_cutoff_s": number;
  "ruleset_hash": string;
  "model_hash"?: string | null;
  "objective_version": string;
  "reason_codes"?: Array<ReasonCode>;
  "outcomes"?: Array<CheckpointOutcome>;
  "probabilities"?: Array<ProbabilityStatement>;
  "constraint_result": ConstraintResult;
  "learned_contribution_enabled"?: boolean;
  "baseline_identity"?: string;
  "outcome_ranges"?: Array<OutcomeRange>;
  "alternatives"?: Array<RecommendationAlternative>;
  "learned"?: LearnedContribution | null;
  "planner_identity"?: string | null;
  "unavailable_reasons"?: Array<string>;
}

export interface RecommendationAlternative {
  "plan_id": string;
  "action_code": ActionCode;
  "display_text": string;
  "rank": number;
  "selected"?: boolean;
  "constraint_status": CheckStatus;
  "final_score"?: number | null;
  "score_delta_vs_selected"?: number | null;
  "expected_utility"?: number | null;
  "cvar_loss"?: number | null;
  "terminal_energy_j"?: number | null;
  "switch_count"?: number | null;
  "switching_penalty"?: number | null;
  "rejected_reason"?: string | null;
  "reason_codes"?: Array<ReasonCode>;
}

export type RecommendationStatus = "proposed" | "selected" | "communicated" | "executing" | "completed" | "rejected" | "expired" | "invalidated";

export interface RecommendationUpdatedPayload {
  "event_type"?: "recommendation_updated";
  "recommendation": Recommendation;
}

export interface ResyncRequiredPayload {
  "event_type"?: "resync_required";
  "reason": string;
  "earliest_available_sequence": number;
}

export interface RivalBelief {
  "car_id": string;
  "slot": string;
  "is_ahead": boolean;
  "gap_s": ScalarValue;
  "gap_m": ScalarValue;
  "relative_speed_mps": ScalarValue;
  "energy_interval_j"?: IntervalValue | null;
  "energy_mean_j"?: ScalarValue | null;
  "pace_bias_s_per_lap"?: ScalarValue | null;
  "intentions": IntentionWeights;
  "observation_age_s"?: number | null;
  "lateral_geometry_known"?: boolean;
}

export interface RuleContext {
  "schema_version": "1.0";
  "session_id": string;
  "season_revision": string;
  "ruleset_hash": string;
  "event_pack_hash"?: string | null;
  "resolved_at_s": number;
  "progress_m": number;
  "current_flags"?: Array<FlagState>;
  "eligibility"?: EligibilityState;
  "eligibility_observed_at_s"?: number | null;
  "active_curve_id"?: string | null;
  "applicable_limits"?: ApplicableLimits;
  "admissible_profiles"?: Array<DeploymentProfile>;
  "unknown_conditions"?: Array<string>;
  "coverage"?: Array<CoverageEntry>;
}

export interface RuleContextChangedPayload {
  "event_type"?: "rule_context_changed";
  "rule_context": RuleContext;
  "invalidated_recommendation_ids"?: Array<string>;
}

export interface RuleManifest {
  "schema_version": "1.0";
  "ruleset_id": string;
  "season_revision": string;
  "event_pack_id"?: string | null;
  "synthetic": boolean;
  "reviewed"?: boolean;
  "references"?: Array<RuleReference>;
  "coverage"?: Array<CoverageEntry>;
  "absolute_power_ceiling_w": number;
  "power_curves"?: Array<PowerCurve>;
  "battery_energy_min_j": number;
  "battery_energy_max_j": number;
  "recharge_allowance_per_lap_j"?: number | null;
  "recharge_measurement_bus"?: string;
  "max_power_ramp_w_per_s"?: number | null;
  "overtake_profile_extra_power_w"?: number | null;
  "detection_lines"?: Array<DetectionLine>;
  "unknown_conditions"?: Array<string>;
}

export interface RuleReference {
  "article": string;
  "source_id": string;
  "source_url"?: string | null;
  "published_date"?: string | null;
  "effective_date"?: string | null;
  "reviewer"?: string | null;
  "note"?: string | null;
}

export interface RuntimeCapabilities {
  "own_energy"?: CapabilityState;
  "rival_energy"?: CapabilityState;
  "lateral_geometry"?: CapabilityState;
  "rules_coverage"?: CapabilityState;
  "solver"?: CapabilityState;
  "learned_model"?: CapabilityState;
  "persistence"?: CapabilityState;
  "driver_link"?: CapabilityState;
  "track_geometry"?: CapabilityState;
  "notes"?: Array<string>;
}

export interface ScalarValue {
  "value": number | null;
  "unit": string;
  "provenance": Provenance;
  "quality"?: Quality;
  "observed_at_s"?: number | null;
  "age_s"?: number | null;
  "standard_deviation"?: number | null;
  "source_id"?: string | null;
}

export interface ScenarioOutcome {
  "scenario_id": string;
  "weight": number;
  "checkpoints"?: Array<CheckpointOutcome>;
  "utility": number;
  "elapsed_time_s"?: number | null;
  "final_energy_j"?: number | null;
  "terminal_value"?: number | null;
  "terminal_value_source"?: string | null;
  "feasible"?: boolean;
}

export interface ScenarioSummary {
  "scenario_id": string;
  "description"?: string | null;
  "track_id"?: string | null;
  "conditions_id"?: string | null;
  "event_id"?: string | null;
  "synthetic"?: boolean | null;
  "status_note"?: string | null;
  "rule_pack"?: string | null;
  "ego_car_id"?: string | null;
  "car_ids"?: Array<string>;
  "duration_s"?: number | null;
  "seed"?: number | null;
  "real_circuit"?: boolean;
  "track_readiness"?: TrackReadiness | null;
  "track_package_hash"?: string | null;
  "run_label"?: string | null;
  "unavailable_reason"?: string | null;
}

export type SessionCommandKind = "start" | "pause" | "resume" | "stop" | "step";

export interface SessionManifest {
  "schema_version": "1.0";
  "id": string;
  "mode": SessionMode;
  "track_hash": string;
  "car_hashes": Record<string, string>;
  "ruleset_hash": string;
  "model_hash"?: string | null;
  "objective_hash": string;
  "seed": number;
  "created_at": string;
  "source_capabilities"?: Array<SourceCapability>;
  "scenario_id"?: string | null;
  "synthetic"?: boolean;
  "label"?: string | null;
  "track_id"?: string | null;
  "event_id"?: string | null;
  "track_package_hash"?: string | null;
  "event_package_hash"?: string | null;
  "track_readiness"?: TrackReadiness | null;
  "geometry_provenance"?: string | null;
  "conditions_id"?: string | null;
  "conditions_hash"?: string | null;
}

export type SessionMode = "simulation" | "replay" | "live_team";

export interface SessionSnapshot {
  "schema_version": "1.0";
  "session_id": string;
  "revision": number;
  "last_sequence": number;
  "server_time": string;
  "session_time_s": number;
  "status": string;
  "manifest": SessionManifest;
  "estimate"?: StateEstimate | null;
  "rule_context"?: RuleContext | null;
  "recommendation"?: Recommendation | null;
  "lease"?: ControlLease | null;
  "capabilities"?: RuntimeCapabilities;
}

export interface SessionSummary {
  "id": string;
  "mode": SessionMode;
  "status": string;
  "revision": number;
  "created_at": string;
  "label"?: string | null;
  "synthetic"?: boolean;
  "scenario_id"?: string | null;
}

export interface SnapshotPayload {
  "event_type"?: "snapshot";
  "snapshot": SessionSnapshot;
}

export interface SnapshotReference {
  "snapshot_id": string;
  "session_id": string;
  "snapshot_hash": string;
  "session_time_s": number;
  "label"?: string | null;
  "created_at": string;
}

export interface SourceCapability {
  "source_id": string;
  "mode": SessionMode;
  "supported_channels"?: Array<string>;
  "measured_channels"?: Array<string>;
  "update_rates_hz"?: Record<string, number>;
  "clock_error_s": number;
  "limitations"?: Array<string>;
  "license_note"?: string | null;
}

export interface SourceSummary {
  "source_id": string;
  "title": string;
  "url": string;
  "retrieved_at": string;
  "sha256"?: string | null;
  "permission": string;
  "priority"?: number | null;
  "document_revision"?: string | null;
}

export interface StateEstimate {
  "schema_version": "1.0";
  "session_id": string;
  "revision": number;
  "cutoff_s": number;
  "created_at_s": number;
  "own_car": OwnCarEstimate;
  "rival_beliefs"?: Array<RivalBelief>;
  "race_context": RaceContext;
  "quality": EstimateQuality;
  "contributing_event_ids"?: Array<string>;
}

export type StreamEventType = "snapshot" | "telemetry_view" | "estimate_updated" | "recommendation_updated" | "execution_observed" | "rule_context_changed" | "quality_changed" | "experiment_progress" | "heartbeat" | "resync_required";

export interface SupportThresholds {
  "max_ensemble_disagreement": number;
  "max_clip_fraction": number;
  "min_known_mask_fraction": number;
  "frozen_before_final_test"?: boolean;
}

export interface TelemetrySeries {
  "channel": string;
  "car_id"?: string | null;
  "unit": string;
  "provenance": string;
  "x_coordinate": "progress_m" | "session_time_s";
  "x"?: Array<number>;
  "y"?: Array<number | null>;
  "y_low"?: Array<number | null> | null;
  "y_high"?: Array<number | null> | null;
  "quantile_definition"?: string | null;
  "sample_count"?: number;
  "decimated"?: boolean;
}

export interface TelemetryViewPayload {
  "event_type"?: "telemetry_view";
  "series": Array<TelemetrySeries>;
  "coalesced_from_sequence"?: number | null;
  "coalesced_to_sequence"?: number | null;
}

export type TrackReadiness = "discovered" | "geometry_validated" | "event_rules_validated" | "condition_calibrated" | "simulation_eligible" | "rejected";

export interface TrackSummary {
  "track_id": string;
  "display_name": string;
  "country"?: string | null;
  "registry_readiness"?: TrackReadiness | null;
  "official_length_m"?: number | null;
  "official_length_verified"?: boolean;
  "official_length_source_url"?: string | null;
  "official_length_sha256"?: string | null;
  "event_ids"?: Array<string>;
  "package_present"?: boolean;
  "package_hash"?: string | null;
  "readiness"?: TrackReadiness | null;
  "geometry_provenance"?: string | null;
  "corridor_quality"?: string | null;
  "lateral_geometry_surveyed"?: boolean | null;
  "nominal_length_m"?: number | null;
  "point_count"?: number | null;
  "sample_spacing_m"?: number | null;
  "arrays_sha256"?: string | null;
  "source_count"?: number | null;
  "licence_labels"?: Array<string>;
  "closure_error_m"?: number | null;
  "length_error_fraction"?: number | null;
  "simulation_ready"?: boolean;
  "event_overlay_ids"?: Array<string>;
  "unavailable_reason"?: string | null;
  "notes"?: Array<string>;
}

export interface TreatmentSpec {
  "treatment_id": string;
  "controller": string;
  "model_bundle_id"?: string | null;
  "description"?: string | null;
}

export interface Trigger {
  "kind": string;
  "checkpoint_id"?: string | null;
  "progress_m"?: number | null;
  "gap_threshold_s"?: number | null;
  "description": string;
}

export interface ValidationSummary {
  "status": TrackReadiness;
  "closure_error_m"?: number | null;
  "length_error_fraction"?: number | null;
  "official_length_m"?: number | null;
  "report_path"?: string | null;
  "checks"?: Record<string, string>;
  "notes"?: Array<string>;
}

export interface TelemetryEvent {
  "schema_version": "1.0";
  "event_id": string;
  "session_id": string;
  "car_id": string;
  "sequence": number;
  "source_time_s": number;
  "received_time_s": number;
  "channel": string;
  "value": number | null;
  "unit": string;
  "provenance": Provenance;
  "quality": Quality;
}

export interface TelemetryChunkManifest {
  "chunk_hash": string;
  "session_id": string;
  "car_id"?: string | null;
  "channel_family": string;
  "start_session_time_s": number;
  "end_session_time_s": number;
  "row_count": number;
  "path": string;
  "mapping_revision": string;
}

export interface QualityEvent {
  "schema_version": "1.0";
  "event_id": string;
  "session_id": string;
  "sequence": number;
  "session_time_s": number;
  "channels"?: Array<ChannelQuality>;
  "capability_states"?: Record<string, CapabilityState>;
  "message"?: string | null;
}

export interface PlanningResult {
  "schema_version": "1.0";
  "session_id": string;
  "state_revision": number;
  "status": PlanningStatus;
  "created_at_s": number;
  "deadline_s": number;
  "duration_ms": number;
  "accepted"?: Array<CandidatePlan>;
  "rejected"?: Array<CandidatePlan>;
  "selected_plan_id"?: string | null;
  "reason_codes"?: Array<ReasonCode>;
  "scenario_count"?: number;
  "candidate_count"?: number;
  "learned_contribution_enabled"?: boolean;
  "baseline_identity"?: string;
  "detail"?: string | null;
}

export interface SessionCommand {
  "schema_version": "1.0";
  "id": string;
  "session_id": string;
  "idempotency_key": string;
  "kind": SessionCommandKind;
  "expected_revision": number;
  "operator_id": string;
  "session_time_s": number;
  "step_duration_s"?: number | null;
}

export interface LifecycleTransition {
  "schema_version": "1.0";
  "id": string;
  "session_id": string;
  "recommendation_id": string;
  "from_status": RecommendationStatus;
  "to_status": RecommendationStatus;
  "session_time_s": number;
  "sequence": number;
  "evidence_event_id"?: string | null;
  "reason"?: string | null;
}

export interface OutcomeRecord {
  "schema_version": "1.0";
  "id": string;
  "session_id": string;
  "decision_id"?: string | null;
  "checkpoint": CheckpointDefinition;
  "evaluation_horizon_s": number;
  "event_observed": boolean;
  "elapsed_time_s"?: number | null;
  "energy_j"?: number | null;
  "position"?: number | null;
  "gap_to_reference_s"?: number | null;
  "provenance": Provenance;
  "incomplete_reason"?: string | null;
}

export interface FeatureManifest {
  "schema_version": "1.0";
  "revision": string;
  "value_count": number;
  "observation_size": number;
  "fields": Array<FeatureField>;
  "action_size": number;
  "policy_interval_s": number;
  "preference_window_s": number;
}

export interface ExperimentManifest {
  "schema_version": "1.0";
  "id": string;
  "snapshot_hash": string;
  "treatment_ids": Array<string>;
  "opponent_policy_hashes"?: Record<string, string>;
  "disturbance_seed_ids": Array<number>;
  "evaluator_version": string;
  "metrics_version": string;
  "evaluation_horizon_s": number;
  "checkpoint_ids"?: Array<string>;
  "created_at": string;
}

export interface BenchmarkReport {
  "schema_version": "1.0";
  "id": string;
  "created_at": string;
  "evaluator_version": string;
  "metrics_version": string;
  "scenario_family": string;
  "scenario_count": number;
  "seed_count": number;
  "comparisons"?: Array<BenchmarkComparison>;
  "calibration"?: Array<CalibrationReport>;
  "latency_p50_ms"?: number | null;
  "latency_p95_ms"?: number | null;
  "latency_p99_ms"?: number | null;
  "withdrawn_decisions"?: number;
  "modelled_violations"?: number;
  "failures_by_category"?: Record<string, number>;
  "hardware"?: string | null;
  "rerun_command"?: string | null;
  "notes"?: Array<string>;
}

export interface StreamEnvelope {
  "schema_version": "1.0";
  "session_id": string;
  "sequence": number;
  "event_type": StreamEventType;
  "session_time_s": number;
  "payload": SnapshotPayload | TelemetryViewPayload | EstimateUpdatedPayload | RecommendationUpdatedPayload | ExecutionObservedPayload | RuleContextChangedPayload | QualityChangedPayload | ExperimentProgressPayload | HeartbeatPayload | ResyncRequiredPayload;
}

export interface ApiErrorResponse {
  "error": ApiError;
}

export interface CreateSessionRequest {
  "mode": SessionMode;
  "scenario_id": string;
  "ruleset_id": string;
  "seed": number;
  "model_bundle_id"?: string | null;
  "label"?: string | null;
  "track_id"?: string | null;
  "event_id"?: string | null;
  "conditions_id"?: string | null;
}

export interface CreateSessionResponse {
  "manifest": SessionManifest;
  "snapshot": SessionSnapshot;
}

export interface SessionListResponse {
  "sessions"?: Array<SessionSummary>;
  "next_cursor"?: string | null;
}

export interface AcquireLeaseRequest {
  "operator_id": string;
  "expected_lease_revision"?: number | null;
  "ttl_s"?: number;
}

export interface AcquireLeaseResponse {
  "lease": ControlLease;
}

export interface SessionCommandRequest {
  "kind": SessionCommandKind;
  "expected_revision": number;
  "operator_id": string;
  "step_duration_s"?: number | null;
}

export interface SessionCommandResponse {
  "accepted": boolean;
  "revision": number;
  "sequence": number;
  "status": string;
}

export interface RecommendationActionRequest {
  "action": OperatorAction;
  "expected_revision": number;
  "operator_id": string;
  "reason"?: string | null;
}

export interface RecommendationActionResponse {
  "recommendation": Recommendation;
  "operator_event": OperatorEvent;
}

export interface DriverActionRequest {
  "profile_id": DeploymentProfile;
  "observed_at_s": number;
  "recommendation_id"?: string | null;
  "operator_id": string;
}

export interface DriverActionResponse {
  "execution": ExecutionEvent;
  "recommendation"?: Recommendation | null;
}

export interface CreateSnapshotRequest {
  "label"?: string | null;
}

export interface CreateSnapshotResponse {
  "snapshot": SnapshotReference;
}

export interface CreateExperimentRequest {
  "snapshot_id": string;
  "treatments": Array<TreatmentSpec>;
  "seeds": Array<number>;
  "evaluator_version": string;
  "evaluation_horizon_s": number;
}

export interface CreateExperimentResponse {
  "job": ExperimentJob;
}

export interface CancelExperimentRequest {
  "reason": string;
}

export interface ExperimentStatusResponse {
  "job": ExperimentJob;
  "status": JobStatus;
  "report_path"?: string | null;
}

export interface ModelListResponse {
  "models"?: Array<ModelManifest>;
}

export interface RulesetResponse {
  "manifest": RuleManifest;
}

export interface CreateExportRequest {
  "session_id": string;
  "format": string;
  "start_session_time_s"?: number | null;
  "end_session_time_s"?: number | null;
}

export interface ExportJobResponse {
  "export_id": string;
  "status": JobStatus;
  "path"?: string | null;
  "hashes"?: Record<string, string>;
  "synthetic"?: boolean;
  "created_at": string;
}

export interface HealthResponse {
  "status": string;
  "detail"?: Record<string, string>;
}

export interface DecisionEvidenceResponse {
  "recommendation": Recommendation;
  "estimate_revision": number;
  "operator_events"?: Array<OperatorEvent>;
  "execution_events"?: Array<ExecutionEvent>;
}

export interface TrackListResponse {
  "schema_version"?: string;
  "season"?: number | null;
  "snapshot_date"?: string | null;
  "minimum_readiness_to_drive"?: TrackReadiness;
  "notice"?: string;
  "tracks"?: Array<TrackSummary>;
}

export interface TrackDetailResponse {
  "schema_version"?: string;
  "notice"?: string;
  "track": TrackSummary;
  "validation"?: ValidationSummary | null;
  "features"?: FeatureSummary | null;
  "sources"?: Array<SourceSummary>;
  "event_overlays"?: Array<EventOverlaySummary>;
}

export interface CentrelineResponse {
  "schema_version"?: string;
  "track_id": string;
  "package_hash": string;
  "arrays_sha256"?: string | null;
  "readiness": TrackReadiness;
  "geometry_provenance": string;
  "corridor_quality": string;
  "length_m": number;
  "source_point_count": number;
  "sample_spacing_m": number;
  "stride_m": number;
  "index_stride": number;
  "point_count": number;
  "units"?: Record<string, string>;
  "s_m"?: Array<number>;
  "x_m"?: Array<number>;
  "y_m"?: Array<number>;
  "curvature_1pm"?: Array<number>;
  "notice"?: string;
}

export interface ConditionsListResponse {
  "schema_version"?: string;
  "conditions"?: Array<ConditionsSummary>;
  "notice"?: string;
}

export interface ScenarioListResponse {
  "schema_version"?: string;
  "scenarios"?: Array<ScenarioSummary>;
  "notice"?: string;
}
