import type { Page, Route } from '@playwright/test';

/**
 * The mocked control plane for the A09/A10/A11 routes.
 *
 * Contract-shaped JSON, written out here rather than imported from
 * `src/test/contractFixtures.ts` so the end-to-end suite has no dependency on
 * the app's module aliases. Everything is synthetic.
 *
 * The stream is mocked too, with `page.routeWebSocket`, so reconnect and
 * resync behaviour can be driven from a test.
 */
export const SESSION_ID = 'synthetic-battle-001';
export const LAST_SEQUENCE = 100;

export const MANIFEST = {
  schema_version: '1.0',
  id: SESSION_ID,
  mode: 'simulation',
  track_hash: 'sha256:track',
  car_hashes: { 'car-01': 'sha256:car' },
  ruleset_hash: 'sha256:synthetic-pack-v1',
  model_hash: null,
  objective_hash: 'sha256:objective',
  seed: 42,
  created_at: '2026-09-08T12:00:00Z',
  source_capabilities: [],
  scenario_id: 'two-straight-counterattack',
  synthetic: true,
  label: 'Synthetic battle, undercut window',
} as const;

function scalar(value: number | null, unit: string, provenance = 'simulated') {
  return {
    value,
    unit,
    provenance,
    quality: value === null ? 'missing' : 'valid',
    observed_at_s: 12.0,
    age_s: 0.2,
    standard_deviation: null,
    source_id: null,
  };
}

export const ESTIMATE = {
  schema_version: '1.0',
  session_id: SESSION_ID,
  revision: 4,
  cutoff_s: 12.2,
  created_at_s: 12.2,
  own_car: {
    car_id: 'car-01',
    progress_m: scalar(1950, 'm'),
    lap_distance_m: scalar(1950, 'm'),
    completed_laps: 0,
    speed_mps: scalar(75, 'm/s'),
    acceleration_mps2: scalar(0.4, 'm/s^2', 'estimated'),
    battery_energy_j: scalar(2_400_000, 'J'),
    battery_energy_interval: null,
    battery_temperature_k: scalar(318, 'K'),
    electrical_power_w: scalar(120_000, 'W'),
    recharge_spent_this_lap_j: scalar(2_400_000, 'J'),
    tyre_pace_residual_s_per_lap: null,
    active_profile_id: 'neutral',
  },
  rival_beliefs: [
    {
      car_id: 'car-07',
      slot: 'ahead_1',
      is_ahead: true,
      gap_s: scalar(0.65, 's', 'estimated'),
      gap_m: scalar(48.75, 'm', 'estimated'),
      relative_speed_mps: scalar(-0.8, 'm/s', 'estimated'),
      energy_interval_j: {
        lower: 1_800_000,
        upper: 3_400_000,
        unit: 'J',
        kind: 'quantile',
        coverage: 0.9,
        provenance: 'estimated',
        quality: 'degraded',
        observed_at_s: 12.0,
        age_s: 0.2,
      },
      energy_mean_j: scalar(2_600_000, 'J', 'estimated'),
      pace_bias_s_per_lap: scalar(-0.15, 's', 'estimated'),
      intentions: { conserve: 0.15, normal: 0.45, attack: 0.1, defend: 0.3 },
      observation_age_s: 0.2,
      lateral_geometry_known: false,
    },
  ],
  race_context: {
    lap: 1,
    total_laps: 8,
    remaining_distance_m: scalar(39_650, 'm', 'configured'),
    track_length_m: 5200,
    flag_state: 'green',
    flag_known: true,
    eligibility: 'eligible_detected',
    eligibility_observed_at_s: 11.8,
    position: 4,
  },
  quality: {
    overall: 'valid',
    channels: [
      {
        channel: 'battery_energy_j',
        car_id: 'car-01',
        quality: 'valid',
        last_source_time_s: 12.0,
        age_s: 0.2,
        expected_period_s: 0.05,
        reason: null,
      },
    ],
    clock_uncertainty_s: 0.02,
    own_energy_capability: true,
    residual_alarm: false,
    notes: [],
  },
  contributing_event_ids: ['fixture-001'],
} as const;

export const RULE_CONTEXT = {
  schema_version: '1.0',
  session_id: SESSION_ID,
  season_revision: 'synthetic-2026-r0',
  ruleset_hash: 'sha256:synthetic-pack-v1',
  event_pack_hash: null,
  resolved_at_s: 12.2,
  progress_m: 1950,
  current_flags: ['green'],
  eligibility: 'eligible_detected',
  eligibility_observed_at_s: 11.8,
  active_curve_id: 'baseline-speed-curve',
  applicable_limits: {
    deployment_ceiling_w: 350_000,
    recovery_ceiling_w: 350_000,
    battery_energy_min_j: 0,
    battery_energy_max_j: 4_000_000,
    recharge_allowance_remaining_j: 6_100_000,
    max_power_ramp_w_per_s: 700_000,
    thermal_derate_factor: 1.0,
  },
  admissible_profiles: ['harvest', 'conserve', 'neutral', 'push', 'overtake'],
  unknown_conditions: [],
  coverage: [],
} as const;

export function recommendation(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: '1.0',
    id: 'rec-001',
    revision: 1,
    session_id: SESSION_ID,
    state_revision: 4,
    plan_id: 'plan-attack-1',
    status: 'proposed',
    action_code: 'attack',
    display_text: 'Attack into T7, hold through attack-exit',
    trigger: {
      kind: 'checkpoint',
      checkpoint_id: 'activate-1',
      progress_m: 1900,
      gap_threshold_s: null,
      description: 'At the activation line',
    },
    end_condition: 'attack-exit checkpoint',
    created_at_s: 12.25,
    valid_from_s: 12.3,
    expires_at_s: 20.0,
    observation_cutoff_s: 12.2,
    ruleset_hash: 'sha256:synthetic-pack-v1',
    model_hash: null,
    objective_version: 'objective-v1',
    reason_codes: [],
    outcomes: [
      {
        checkpoint_id: 'attack-exit',
        progress_m: 2100,
        elapsed_time_s: 2.1,
        gap_to_reference_s: null,
        own_energy_j: 1_880_000,
        position: null,
        ahead_of_rival: true,
      },
    ],
    probabilities: [],
    constraint_result: {
      schema_version: '1.0',
      status: 'pass',
      checks: [
        {
          check_id: 'power_ceiling',
          status: 'pass',
          margin: 30_000,
          unit: 'W',
          limit: 350_000,
          observed: 320_000,
          at_progress_m: 2000,
          at_session_time_s: null,
          references: [],
          detail: null,
        },
      ],
      ruleset_hash: 'sha256:synthetic-pack-v1',
      checked_at_s: 12.25,
      checker_version: 'checker-v1',
      unresolved_conditions: [],
    },
    learned_contribution_enabled: false,
    baseline_identity: 'mpc_baseline',
    ...overrides,
  };
}

export function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: '1.0',
    session_id: SESSION_ID,
    revision: 7,
    last_sequence: LAST_SEQUENCE,
    server_time: '2026-09-08T12:00:12Z',
    session_time_s: 12.3,
    status: 'running',
    manifest: MANIFEST,
    estimate: ESTIMATE,
    rule_context: RULE_CONTEXT,
    recommendation: recommendation(),
    lease: null,
    capabilities: {
      own_energy: 'available',
      rival_energy: 'degraded',
      lateral_geometry: 'unavailable',
      rules_coverage: 'degraded',
      solver: 'available',
      learned_model: 'unavailable',
      persistence: 'available',
      driver_link: 'available',
      notes: ['Synthetic fixture. Not measured telemetry.'],
    },
    ...overrides,
  };
}

export const RULE_MANIFEST = {
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
      note: null,
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
      note: 'The pack declares no gap threshold.',
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
} as const;

export const MODELS = {
  models: [
    {
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
      promotion_policy: { enabled: false, frozen_at: null },
      created_at: '2026-09-01T00:00:00Z',
    },
  ],
} as const;

export const EXPERIMENT_JOB = {
  job: {
    schema_version: '1.0',
    id: 'exp-0001',
    manifest_hash: 'sha256:manifest',
    status: 'completed',
    progress: 1,
    created_at: '2026-09-08T10:00:00Z',
    started_at: '2026-09-08T10:00:01Z',
    finished_at: '2026-09-08T10:05:00Z',
    report_hash: 'sha256:report',
    failure: null,
    partial_results: false,
  },
  status: 'completed',
  report_path: '/artifacts/reports/exp-0001.json',
} as const;

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
      'unmeasured comparison-matrix rows: mpc_only, mpc_plus_actor, mpc_plus_value, full_system.',
    ],
  },
  report_hash: 'sha256:synthetic-report',
  detail: {
    population: { planned_units: 4, completed_runs: 8, unavailable_runs: 16, failed_runs: 0 },
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
        controller: 'mpc_only',
        reference: 'legal_fixed_schedule',
        purpose: 'planner without any learned contribution',
        owner: 'A06',
        status: 'unmeasured',
        reason: 'not wired into run_benchmark as a controller',
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
    ],
    gates: { status: 'unmeasured' },
    certification: 'not_claimed',
  },
} as const;

export const DECISION_RECORD = {
  recommendation: recommendation(),
  estimate_revision: 4,
  operator_events: [],
  execution_events: [],
} as const;

function envelope(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
  sessionTimeS = 12.3,
) {
  return JSON.stringify({
    schema_version: '1.0',
    session_id: SESSION_ID,
    sequence,
    event_type: eventType,
    session_time_s: sessionTimeS,
    payload: { event_type: eventType, ...payload },
  });
}

function series(channel: string, unit: string, values: readonly number[]) {
  return {
    channel,
    car_id: 'car-01',
    unit,
    provenance: 'simulated',
    x_coordinate: 'progress_m',
    x: [1900, 1950, 2000, 2050, 2100],
    y: [...values],
    sample_count: 5,
    decimated: false,
  };
}

export function telemetryFrame(sequence: number): string {
  return envelope(sequence, 'telemetry_view', {
    series: [
      series('battery_energy_j', 'J', [2_600_000, 2_500_000, 2_350_000, 2_100_000, 1_880_000]),
      series('speed_mps', 'm/s', [72, 75, 78, 80, 79]),
      series('gap_ahead_s', 's', [0.9, 0.8, 0.72, 0.68, 0.65]),
    ],
  });
}

export function snapshotFrame(sequence: number, overrides: Record<string, unknown> = {}): string {
  return envelope(sequence, 'snapshot', { snapshot: snapshot(overrides) });
}

export function resyncFrame(sequence: number): string {
  return envelope(sequence, 'resync_required', {
    reason: 'reconnect buffer overrun',
    earliest_available_sequence: LAST_SEQUENCE + 10,
  });
}

export interface MockOptions {
  /** Replace the snapshot the control plane returns. */
  readonly snapshotOverrides?: Record<string, unknown>;
  /** Answer the recommendation action route with this typed error. */
  readonly actionError?: { code: string; message: string; status: number };
  /** Serve the benchmark report body. Off by default: no such route exists. */
  readonly serveReport?: boolean;
  /** Frames pushed once the socket opens. */
  readonly frames?: readonly string[];
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

function typedError(route: Route, code: string, message: string, status: number): Promise<void> {
  return json(route, { error: { code, message, retryable: false, request_id: 'e2e' } }, status);
}

/** Requests the page issued, for asserting what was *not* sent. */
export interface RequestLog {
  readonly urls: string[];
}

export async function mockFeatureApi(page: Page, options: MockOptions = {}): Promise<RequestLog> {
  const log: RequestLog = { urls: [] };

  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) {
      log.urls.push(`${request.method()} ${request.url()}`);
    }
  });

  // Registered first so the specific routes below take precedence.
  await page.route('**/api/v1/**', (route) =>
    typedError(route, 'not_found', 'not mocked in the end-to-end suite', 404),
  );

  await page.route('**/api/v1/sessions?*', (route) => json(route, { sessions: [], next_cursor: null }));
  await page.route('**/api/v1/sessions', (route) => json(route, { sessions: [], next_cursor: null }));

  await page.route('**/api/v1/sessions/*/snapshot', (route) => json(route, snapshot(options.snapshotOverrides ?? {})));
  await page.route('**/api/v1/decisions/**', (route) => json(route, DECISION_RECORD));
  await page.route('**/api/v1/rulesets/**', (route) => json(route, { manifest: RULE_MANIFEST }));
  await page.route('**/api/v1/models**', (route) => json(route, MODELS));

  // Playwright checks the most recently registered handler first, so these go
  // from least to most specific: collection, then one job, then its report.
  await page.route('**/api/v1/experiments**', (route) =>
    route.request().method() === 'POST'
      ? json(route, { job: { ...EXPERIMENT_JOB.job, id: 'exp-new', status: 'queued' } }, 202)
      : json(route, [EXPERIMENT_JOB]),
  );
  await page.route('**/api/v1/experiments/*', (route) =>
    route.request().method() === 'POST'
      ? json(route, { job: { ...EXPERIMENT_JOB.job, status: 'cancelled', partial_results: true } })
      : json(route, EXPERIMENT_JOB),
  );
  await page.route('**/api/v1/experiments/*/report', (route) =>
    options.serveReport === true
      ? json(route, REPORT_BUNDLE)
      : typedError(route, 'not_found', 'the control plane serves no report body', 404),
  );

  await page.route('**/api/v1/sessions/*/control-lease', (route) =>
    json(route, {
      lease: {
        session_id: SESSION_ID,
        operator_id: 'console-operator',
        revision: 1,
        granted_at_s: 12,
        expires_at_s: 120,
      },
    }),
  );

  await page.route('**/api/v1/sessions/*/commands', (route) =>
    json(route, { accepted: true, revision: 8, sequence: 101, status: 'running' }),
  );

  await page.route('**/api/v1/sessions/*/snapshots', (route) =>
    json(
      route,
      {
        snapshot: {
          snapshot_id: 'snap-e2e',
          session_id: SESSION_ID,
          snapshot_hash: 'sha256:e2e-snapshot',
          session_time_s: 12.3,
          label: 'e2e',
          created_at: '2026-09-08T12:00:13Z',
        },
      },
      201,
    ),
  );

  await page.route('**/api/v1/sessions/*/recommendations/*/actions', (route) => {
    if (options.actionError !== undefined) {
      return typedError(
        route,
        options.actionError.code,
        options.actionError.message,
        options.actionError.status,
      );
    }
    return json(route, {
      recommendation: recommendation({ status: 'selected', revision: 2 }),
      operator_event: {
        schema_version: '1.0',
        id: 'op-e2e',
        session_id: SESSION_ID,
        idempotency_key: 'e2e',
        recommendation_id: 'rec-001',
        expected_revision: 7,
        operator_id: 'console-operator',
        action: 'select',
        reason: null,
        session_time_s: 12.4,
        sequence: 102,
        resulting_status: 'selected',
      },
    });
  });

  await page.route('**/api/v1/sessions/*/simulator/driver-action', (route) =>
    json(route, {
      execution: {
        schema_version: '1.0',
        id: 'exec-e2e',
        session_id: SESSION_ID,
        recommendation_id: 'rec-001',
        source: 'simulated',
        observed_profile_id: 'overtake',
        start_time_s: 12.6,
        end_time_s: null,
        evidence_event_ids: [],
        match_status: 'matched',
        sequence: 103,
        delay_from_communication_s: 0.4,
      },
      recommendation: recommendation({ status: 'executing', revision: 3 }),
    }),
  );

  const frames = options.frames ?? [telemetryFrame(LAST_SEQUENCE + 1)];
  await page.routeWebSocket(/\/api\/v1\/sessions\/.*\/stream/, (ws) => {
    for (const frame of frames) {
      ws.send(frame);
    }
    ws.onMessage(() => {});
  });

  return log;
}
