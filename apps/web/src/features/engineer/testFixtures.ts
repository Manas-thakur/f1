
import type {
  ExperimentStatusResponse,
  ModelManifest,
  Recommendation,
  RivalBelief,
  RuleContext,
  RuleManifest,
  SessionSnapshot,
  StateEstimate,
  TelemetrySeries,
} from '@contracts';

import {
  RECOMMENDATION,
  RULE_CONTEXT,
  SESSION_SNAPSHOT,
  STATE_ESTIMATE,
} from '@/test/contractFixtures';
import type { QualitySummary } from '@/state/types';

export const SNAPSHOT: SessionSnapshot = SESSION_SNAPSHOT;
export const ESTIMATE: StateEstimate = STATE_ESTIMATE;
export const RECOMMENDATION_FIXTURE: Recommendation = RECOMMENDATION;
export const RULES: RuleContext = RULE_CONTEXT;

export function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return { ...RECOMMENDATION, ...overrides };
}

export function ruleContext(overrides: Partial<RuleContext> = {}): RuleContext {
  return { ...RULE_CONTEXT, ...overrides };
}

export function estimate(overrides: Partial<StateEstimate> = {}): StateEstimate {
  return { ...STATE_ESTIMATE, ...overrides };
}


export function estimateWithoutEnergy(): StateEstimate {
  const base = STATE_ESTIMATE;
  return {
    ...base,
    own_car: {
      ...base.own_car,
      battery_energy_j: { ...base.own_car.battery_energy_j, value: null, quality: 'missing' },
    },
    quality: { ...base.quality, own_energy_capability: false },
  };
}

export function qualitySummary(overrides: Partial<QualitySummary> = {}): QualitySummary {
  return {
    overall: 'valid',
    worstChannel: null,
    blocking: false,
    reason: null,
    ...overrides,
  };
}


export function rivalWithQuantile(): RivalBelief {
  const rival = (STATE_ESTIMATE.rival_beliefs ?? [])[0];
  if (rival === undefined) {
    throw new Error('the generated estimate fixture has no rival belief');
  }
  return rival;
}

export function energySeries(): TelemetrySeries {
  return {
    channel: 'battery_energy_j',
    car_id: 'car-01',
    unit: 'J',
    provenance: 'simulated',
    x_coordinate: 'progress_m',
    x: [1900, 1950, 2000, 2050, 2100],
    y: [2_600_000, 2_500_000, 2_350_000, 2_100_000, 1_880_000],
    sample_count: 5,
    decimated: false,
  };
}

export function speedSeries(): TelemetrySeries {
  return {
    channel: 'speed_mps',
    car_id: 'car-01',
    unit: 'm/s',
    provenance: 'simulated',
    x_coordinate: 'progress_m',
    x: [1900, 1950, 2000, 2050, 2100],
    y: [72, 75, 78, 80, 79],
    sample_count: 5,
    decimated: false,
  };
}

export const RULE_MANIFEST: RuleManifest = {
  schema_version: '1.0',
  ruleset_id: 'synthetic-pack-v1',
  season_revision: 'synthetic-2026-r0',
  event_pack_id: null,
  synthetic: true,
  reviewed: false,
  references: [
    {
      article: 'PU-ENERGY-LIMIT',
      source_id: 'synthetic-source-register',
      source_url: null,
      published_date: null,
      effective_date: null,
      reviewer: null,
      note: 'Names where a transcription would come from. Not a transcription.',
    },
  ],
  coverage: [
    {
      concern: 'deployment power ceiling',
      status: 'implemented_and_tested',
      references: [],
      test_ids: ['test_power_ceiling'],
      note: null,
    },
    {
      concern: 'overtake eligibility window',
      status: 'unsupported',
      references: [],
      test_ids: [],
      note: 'The pack declares no gap threshold, so eligibility cannot be resolved.',
    },
  ],
  absolute_power_ceiling_w: 350_000,
  power_curves: [],
  battery_energy_min_j: 0,
  battery_energy_max_j: 4_000_000,
  recharge_allowance_per_lap_j: 6_100_000,
  recharge_measurement_bus: 'dc_bus',
  max_power_ramp_w_per_s: 700_000,
  overtake_profile_extra_power_w: null,
  detection_lines: [{ line_id: 'activate-1', kind: 'activation', s_m: 1900 }],
  unknown_conditions: ['overtake_gap_threshold_s'],
};

export const CANDIDATE_MODEL: ModelManifest = {
  schema_version: '1.0',
  id: 'bundle-candidate-1',
  algorithm: 'sac',
  weights_hash: 'sha256:candidate-weights',
  feature_schema_hash: 'sha256:features',
  rule_family: 'synthetic-pack-v1',
  reward_revision: 'reward-v1',
  approval_status: 'candidate',
  benchmark_report_hash: null,
  support_thresholds: {
    max_ensemble_disagreement: 0.2,
    max_clip_fraction: 0.05,
    min_known_mask_fraction: 0.9,
  },
  promotion_policy: {
    enabled: false,
    minimum_benefit: null,
    benefit_metric: null,
    frozen_at: null,
    rationale: 'No promotion is automatic in this product.',
  },
  created_at: '2026-09-01T00:00:00Z',
};


export const UNSUPPORTED_APPROVED_MODEL: ModelManifest = {
  ...CANDIDATE_MODEL,
  id: 'bundle-approved-without-evidence',
  approval_status: 'approved',
  benchmark_report_hash: null,
};

export function experimentJob(
  overrides: Partial<ExperimentStatusResponse['job']> = {},
  status: ExperimentStatusResponse['status'] = 'running',
): ExperimentStatusResponse {
  return {
    job: {
      schema_version: '1.0',
      id: 'exp-0001',
      manifest_hash: 'sha256:manifest',
      status,
      progress: 0.5,
      created_at: '2026-09-08T10:00:00Z',
      started_at: '2026-09-08T10:00:01Z',
      finished_at: null,
      report_hash: null,
      failure: null,
      partial_results: false,
      ...overrides,
    },
    status,
  };
}


export const REPORT_BUNDLE = {
  report: {
    schema_version: '1.0',
    id: 'report-commissioning-smoke',
    created_at: '2026-09-08T09:00:00Z',
    evaluator_version: 'evaluator-v1',
    metrics_version: 'metrics-v1',
    scenario_family: 'commissioning-smoke',
    scenario_count: 2,
    seed_count: 2,
    comparisons: [],
    calibration: [],
    latency_p50_ms: 4.1,
    latency_p95_ms: 9.7,
    latency_p99_ms: 14.2,
    withdrawn_decisions: 3,
    modelled_violations: 0,
    failures_by_category: {},
    hardware: 'synthetic fixture, no hardware measured',
    rerun_command: 'afterlap_core.cli benchmark --manifest commissioning-smoke',
    notes: [
      'unmeasured comparison-matrix rows: mpc_only, mpc_plus_actor, mpc_plus_value, full_system. These rows carry no number; the evidence screen must render them as unavailable.',
      'no probability calibration was assessed: this benchmark declares no probabilistic event forecast, so calibration is unmeasured rather than perfect',
    ],
  },
  report_hash: 'sha256:synthetic-report',
  detail: {
    population: {
      planned_units: 4,
      completed_runs: 8,
      unavailable_runs: 16,
      failed_runs: 0,
      scenario_ids: ['two-straight-counterattack', 'oval-defend-hold'],
      seeds: [1, 2],
    },
    comparison_matrix: [
      {
        controller: 'legal_fixed_schedule',
        reference: null,
        purpose: 'reference arm',
        owner: 'A13',
        status: 'measured',
        reason: null,
        comparison: null,
        distribution: null,
      },
      {
        controller: 'legal_greedy_attacker',
        reference: 'legal_fixed_schedule',
        purpose: 'rule-legal greedy baseline',
        owner: 'A13',
        status: 'measured',
        reason: null,
        comparison: {
          controller: 'legal_greedy_attacker',
          reference: 'legal_fixed_schedule',
          metric: 'elapsed_time_s',
          unit: 's',
          difference_mean: 14.8,
          ci_low: -0.3,
          ci_high: 29.9,
          coverage: 0.95,
          scenario_count: 2,
          seed_count: 2,
          favours_controller: false,
        },
        distribution: null,
      },
      {
        controller: 'mpc_only',
        reference: 'legal_fixed_schedule',
        purpose: 'planner without any learned contribution',
        owner: 'A06',
        status: 'unmeasured',
        reason:
          'the row runs functionally in the acceptance slice but is not wired into run_benchmark as a controller',
        comparison: null,
        distribution: null,
      },
      {
        controller: 'mpc_plus_actor',
        reference: 'mpc_only',
        purpose: 'planner with a learned actor',
        owner: 'A07',
        status: 'unmeasured',
        reason: 'needs a trained actor; no bundle exists',
        comparison: null,
        distribution: null,
      },
      {
        controller: 'mpc_plus_value',
        reference: 'mpc_only',
        purpose: 'planner with a learned continuation value',
        owner: 'A07',
        status: 'unmeasured',
        reason: 'needs a trained continuation ensemble; none exists',
        comparison: null,
        distribution: null,
      },
      {
        controller: 'full_system',
        reference: 'mpc_only',
        purpose: 'actor and learned return together',
        owner: 'A07',
        status: 'unmeasured',
        reason: 'needs a promoted model bundle; none exists',
        comparison: null,
        distribution: null,
      },
    ],
    matrix_coverage: [
      {
        controller: 'legal_fixed_schedule',
        uses_actor: false,
        uses_learned_return: false,
        purpose: 'reference arm',
        owner: 'A13',
        status: 'measured',
        reason: null,
      },
      {
        controller: 'mpc_plus_actor',
        uses_actor: true,
        uses_learned_return: false,
        purpose: 'planner with a learned actor',
        owner: 'A07',
        status: 'unmeasured',
        reason: 'needs a trained actor; no bundle exists',
      },
    ],
    gates: { status: 'unmeasured' },
    certification: 'not_claimed',
  },
} as const;
