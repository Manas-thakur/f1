
import type {
  Recommendation,
  RuleContext,
  SessionSnapshot,
  StateEstimate,
  StreamEnvelope,
} from '@contracts';

import {
  EXECUTION_EVENT,
  RECOMMENDATION,
  RULE_CONTEXT,
  SESSION_SNAPSHOT,
  STATE_ESTIMATE,
} from './contractFixtures';

export const FIXTURE_SESSION_ID = SESSION_SNAPSHOT.session_id;

function envelope(
  sequence: number,
  eventType: StreamEnvelope['event_type'],
  payload: StreamEnvelope['payload'],
  overrides: Partial<Pick<StreamEnvelope, 'session_id' | 'session_time_s'>> = {},
): StreamEnvelope {
  return {
    schema_version: '1.0',
    session_id: overrides.session_id ?? FIXTURE_SESSION_ID,
    sequence,
    event_type: eventType,
    session_time_s: overrides.session_time_s ?? 42,
    payload,
  };
}

export function snapshotEnvelope(
  overrides: Partial<SessionSnapshot> = {},
  sequence?: number,
): StreamEnvelope {
  const snapshot: SessionSnapshot = { ...SESSION_SNAPSHOT, ...overrides };
  return envelope(sequence ?? snapshot.last_sequence, 'snapshot', {
    event_type: 'snapshot',
    snapshot,
  });
}

export function estimateEnvelope(
  sequence: number,
  revision: number,
  overrides: Partial<StateEstimate> = {},
): StreamEnvelope {
  const estimate: StateEstimate = { ...STATE_ESTIMATE, revision, ...overrides };
  return envelope(sequence, 'estimate_updated', { event_type: 'estimate_updated', estimate });
}

export function recommendationEnvelope(
  sequence: number,
  overrides: Partial<Recommendation> = {},
): StreamEnvelope {
  const recommendation: Recommendation = { ...RECOMMENDATION, ...overrides };
  return envelope(sequence, 'recommendation_updated', {
    event_type: 'recommendation_updated',
    recommendation,
  });
}

export function qualityEnvelope(
  sequence: number,
  quality: 'valid' | 'degraded' | 'stale' | 'missing' | 'invalid',
  message = 'Battery energy channel stopped updating.',
): StreamEnvelope {
  return envelope(sequence, 'quality_changed', {
    event_type: 'quality_changed',
    channels: [
      {
        channel: 'battery_energy_j',
        car_id: 'car-01',
        quality,
        age_s: 4.2,
        expected_period_s: 0.05,
        reason: 'no samples received',
      },
    ],
    message,
  });
}

export function heartbeatEnvelope(sequence: number, uptimeS = 900): StreamEnvelope {
  return envelope(sequence, 'heartbeat', {
    event_type: 'heartbeat',
    server_uptime_s: uptimeS,
  });
}

export function resyncEnvelope(sequence: number, earliest = 250): StreamEnvelope {
  return envelope(sequence, 'resync_required', {
    event_type: 'resync_required',
    reason: 'reconnect buffer overrun',
    earliest_available_sequence: earliest,
  });
}

export function telemetryEnvelope(
  sequence: number,
  options: { coalescedFrom?: number; coalescedTo?: number } = {},
): StreamEnvelope {
  return envelope(sequence, 'telemetry_view', {
    event_type: 'telemetry_view',
    series: [
      {
        channel: 'electrical_power_w',
        car_id: 'car-01',
        unit: 'W',
        provenance: 'simulated',
        x_coordinate: 'progress_m',
        x: [0, 10, 20],
        y: [100_000, 250_000, 350_000],
        sample_count: 3,
        decimated: false,
      },
    ],
    ...(options.coalescedFrom === undefined
      ? {}
      : { coalesced_from_sequence: options.coalescedFrom }),
    ...(options.coalescedTo === undefined ? {} : { coalesced_to_sequence: options.coalescedTo }),
  });
}

export function executionEnvelope(sequence: number): StreamEnvelope {
  return envelope(sequence, 'execution_observed', {
    event_type: 'execution_observed',
    execution: EXECUTION_EVENT,
  });
}

export function ruleContextEnvelope(
  sequence: number,
  invalidated: readonly string[] = [],
  overrides: Partial<RuleContext> = {},
): StreamEnvelope {
  return envelope(sequence, 'rule_context_changed', {
    event_type: 'rule_context_changed',
    rule_context: { ...RULE_CONTEXT, ...overrides },
    invalidated_recommendation_ids: [...invalidated],
  });
}


export function foreignEnvelope(sequence: number): StreamEnvelope {
  return envelope(
    sequence,
    'estimate_updated',
    { event_type: 'estimate_updated', estimate: { ...STATE_ESTIMATE, session_id: 'other-session' } },
    { session_id: 'other-session' },
  );
}
