# Domain model — contract v1

The coordinator generates Python/TypeScript models from reviewed JSON Schema. Reject unexpected fields at service boundaries. Models are immutable records; state transitions create new revisions. Example schema in `schemas/telemetry-event.schema.json` is a normative seed for TelemetryEvent; remaining types below must be turned into schemas before parallel implementation integration.

| Type | Required fields and meaning |
|---|---|
| SourceCapability | source_id, mode, supported_channels, measured_channels, update_rates_hz, clock_error_s, limitations |
| TelemetryEvent | schema_version, event_id, session_id, car_id, sequence, source_time_s, received_time_s, channel, value, unit, provenance, quality |
| SessionManifest | id, mode, track_hash, car_hashes, ruleset_hash, model_hash, objective_hash, seed, created_at, source_capabilities |
| WorldState | simulator-only physical states, race state, opponent internal state, random generator states, integrator state, driver queues |
| StateEstimate | session_id, revision, cutoff_s, own_car, rival_beliefs, race_context, quality, uncertainty, contributing_event_ids |
| RuleContext | season_revision, event_pack_hash, current_flags, eligible, eligibility_observed_at_s, active_curve_id, applicable_limits, unknown_conditions |
| CandidatePlan | id, state_revision, intention, profile_segments, scenario_outcomes, terminal_target, model_version, objective_version |
| ProfileSegment | start_progress_m, end_progress_m, profile_id, requested_budget_j, harvest_target_j, execution_window_s |
| ConstraintResult | status: pass/fail/unknown, checks[], margins[], rule_references[], ruleset_hash, checked_at_s |
| Recommendation | id, revision, session_id, state_revision, plan_id, status, action_code, trigger, end_condition, expiry, reason_codes, outcomes, constraint_result |
| OperatorEvent | id, idempotency_key, recommendation_id, expected_revision, operator_id, action, reason, session_time_s |
| ExecutionEvent | id, recommendation_id or null, source, observed_profile_id, start_time_s, evidence_event_ids, match_status |
| OutcomeRecord | decision_id, checkpoint_definition, evaluation_horizon_s, event_observed, elapsed_time_s, energy_j, position, provenance |
| ExperimentManifest | id, snapshot_hash, treatment_ids, opponent_policy_hashes, disturbance_seed_ids, evaluator_version, metrics_version |
| ModelManifest | id, algorithm, weights_hash, feature_schema_hash, normalizer_hash, rule_family, training_data_hash, approval_status, benchmark_report_hash |

## Belief values

Own-car energy stores an estimate, provenance, age and uncertainty. Rival energy is nullable and can be an interval or weighted particles. Operational payloads never include hidden truth for convenience. A probability is an object containing event definition, horizon/checkpoint, value, model version and calibration status. Uncalibrated probabilities are labelled model estimates; unavailable probabilities are not shown as zero.

## Enumerations

Modes: `simulation`, `replay`, `live_team`. Provenance: `measured`, `estimated`, `configured`, `simulated`. Quality: `valid`, `degraded`, `stale`, `missing`, `invalid`. Recommendation states: `proposed`, `selected`, `communicated`, `executing`, `completed`, `rejected`, `expired`, `invalidated`. Action codes: `maintain`, `prepare_attack`, `attack`, `defend`, `recover`, `withdraw_advice`. Display wording is a template mapping, not another action enumeration.

## State ownership

Data owns original source events. Estimation owns beliefs. Rules owns eligibility and constraint calculations. Planning owns candidate predictions. Backend owns lifecycle and operator authority. Simulation owns truth and physical execution. Validation owns realised outcomes and reports. The frontend never computes authoritative eligibility, probability or energy ledgers.

## Version negotiation

Wire envelope `schema_version` is `1.0`. Additive optional changes increment minor version after generated-client tests; renamed units or meanings increment major. Unknown required fields fail closed. Every stored artefact identifies its schema; replay includes a reviewed migration manifest. Feature order is hashed in model manifests to prevent silent inference drift.
