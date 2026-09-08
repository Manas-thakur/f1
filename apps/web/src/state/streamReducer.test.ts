import { describe, expect, it } from 'vitest';

import { RECOMMENDATION, SESSION_SNAPSHOT } from '../test/contractFixtures';
import {
  estimateEnvelope,
  executionEnvelope,
  foreignEnvelope,
  heartbeatEnvelope,
  qualityEnvelope,
  recommendationEnvelope,
  resyncEnvelope,
  ruleContextEnvelope,
  snapshotEnvelope,
  telemetryEnvelope,
} from '../test/envelopes';
import { validateEnvelope } from '../api/validate';
import { applySnapshot, reduceAll, reduceStream } from './streamReducer';
import { selectTimeSensitiveActionsEnabled, selectTimeSensitiveDisabledReason } from './selectors';
import {
  INITIAL_REQUEST_STATE,
  INITIAL_SERVER_STATE,
  INITIAL_STREAM_STATE,
  INITIAL_VIEW_STATE,
  type SessionStoreState,
  type StreamSlice,
} from './types';

function emptySlice(): StreamSlice {
  return { server: INITIAL_SERVER_STATE, stream: INITIAL_STREAM_STATE };
}

function boundSlice(): StreamSlice {
  return applySnapshot(emptySlice(), SESSION_SNAPSHOT);
}

function asStoreState(slice: StreamSlice): SessionStoreState {
  return {
    server: slice.server,
    stream: slice.stream,
    view: INITIAL_VIEW_STATE,
    request: INITIAL_REQUEST_STATE,
  };
}

describe('every fixture envelope is schema-valid', () => {
  it('validates the builders the reducer tests depend on', () => {
    const envelopes = [
      snapshotEnvelope(),
      estimateEnvelope(101, 5),
      recommendationEnvelope(101),
      qualityEnvelope(101, 'stale'),
      heartbeatEnvelope(101),
      resyncEnvelope(101),
      telemetryEnvelope(101),
      executionEnvelope(101),
      ruleContextEnvelope(101),
      foreignEnvelope(101),
    ];
    for (const envelope of envelopes) {
      const result = validateEnvelope(envelope);
      expect(result.ok, `${envelope.event_type}: ${result.ok ? '' : result.message}`).toBe(true);
    }
  });
});

describe('snapshot', () => {
  it('atomically replaces session state and last_sequence', () => {
    const next = reduceStream(emptySlice(), snapshotEnvelope());
    expect(next.server.sessionId).toBe(SESSION_SNAPSHOT.session_id);
    expect(next.server.lastSequence).toBe(SESSION_SNAPSHOT.last_sequence);
    expect(next.server.revision).toBe(SESSION_SNAPSHOT.revision);
    expect(next.server.estimate?.revision).toBe(SESSION_SNAPSHOT.estimate?.revision);
    expect(next.server.recommendation?.id).toBe(SESSION_SNAPSHOT.recommendation?.id);
    expect(next.stream.applyingDeltas).toBe(true);
  });

  it('discards telemetry received before the snapshot', () => {
    const withTelemetry = reduceStream(boundSlice(), telemetryEnvelope(101));
    expect(Object.keys(withTelemetry.server.telemetry)).toHaveLength(1);

    const resnapshotted = reduceStream(withTelemetry, snapshotEnvelope(undefined, 400));
    expect(resnapshotted.server.telemetry).toEqual({});
    expect(resnapshotted.server.telemetryFreshAtS).toBeNull();
  });

  it('is applied even when its sequence does not follow the last one', () => {
    const jumped = reduceStream(boundSlice(), snapshotEnvelope({ last_sequence: 9_000 }));
    expect(jumped.server.lastSequence).toBe(9_000);
    expect(jumped.stream.resyncRequired).toBe(false);
  });
});

describe('estimate_updated', () => {
  it('accepts the next valid revision', () => {
    const base = boundSlice();
    const current = base.server.estimate?.revision ?? 0;
    const next = reduceStream(base, estimateEnvelope(101, current + 1));
    expect(next.server.estimate?.revision).toBe(current + 1);
    expect(next.server.lastSequence).toBe(101);
    expect(next.stream.rejectedEnvelopes).toBe(0);
  });

  it('rejects a stale revision without applying it', () => {
    const base = boundSlice();
    const current = base.server.estimate?.revision ?? 0;
    const next = reduceStream(base, estimateEnvelope(101, current));
    expect(next.server.estimate?.revision).toBe(current);
    expect(next.server.lastSequence).toBe(base.server.lastSequence);
    expect(next.stream.rejectedEnvelopes).toBe(1);
    expect(next.stream.rejections.at(-1)?.reason).toBe('stale_estimate_revision');
  });

  it('asks for a resync when a revision is skipped', () => {
    const base = boundSlice();
    const current = base.server.estimate?.revision ?? 0;
    const next = reduceStream(base, estimateEnvelope(101, current + 2));
    expect(next.server.estimate?.revision).toBe(current);
    expect(next.stream.resyncRequired).toBe(true);
    expect(next.stream.rejections.at(-1)?.reason).toBe('estimate_revision_skip');
  });
});

describe('recommendation_updated', () => {
  it('applies a strictly newer revision of the same recommendation', () => {
    const base = boundSlice();
    const currentRevision = base.server.recommendation?.revision ?? 0;
    const next = reduceStream(
      base,
      recommendationEnvelope(101, { revision: currentRevision + 1, status: 'selected' }),
    );
    expect(next.server.recommendation?.revision).toBe(currentRevision + 1);
    expect(next.server.recommendation?.status).toBe('selected');
  });

  it('rejects a revision that is not newer', () => {
    const base = boundSlice();
    const currentRevision = base.server.recommendation?.revision ?? 0;
    const next = reduceStream(
      base,
      recommendationEnvelope(101, { revision: currentRevision, status: 'rejected' }),
    );
    expect(next.server.recommendation?.status).toBe(RECOMMENDATION.status);
    expect(next.stream.rejections.at(-1)?.reason).toBe('stale_recommendation');
  });

  it('ignores a recommendation belonging to another session', () => {
    const base = boundSlice();
    const next = reduceStream(base, foreignEnvelope(101));
    expect(next.server.estimate?.revision).toBe(base.server.estimate?.revision);
    expect(next.server.lastSequence).toBe(base.server.lastSequence);
    expect(next.stream.rejectedEnvelopes).toBe(1);
    expect(next.stream.rejections.at(-1)?.reason).toBe('wrong_session');
    expect(next.stream.resyncRequired).toBe(false);
  });
});

describe('sequence continuity', () => {
  it('resyncs on a gap: snapshot ending 100 then delta 102', () => {
    const base = boundSlice();
    expect(base.server.lastSequence).toBe(100);
    const next = reduceStream(base, estimateEnvelope(102, 5));
    expect(next.stream.resyncRequired).toBe(true);
    expect(next.stream.applyingDeltas).toBe(false);
    expect(next.stream.rejections.at(-1)?.reason).toBe('sequence_gap');
    expect(next.server.lastSequence).toBe(100);
  });

  it('drops further deltas until a snapshot arrives, then resumes', () => {
    const gapped = reduceStream(boundSlice(), estimateEnvelope(102, 5));
    const stillPaused = reduceStream(gapped, estimateEnvelope(103, 6));
    expect(stillPaused.stream.rejections.at(-1)?.reason).toBe('deltas_paused');

    const resumed = reduceStream(stillPaused, snapshotEnvelope({ last_sequence: 103 }));
    expect(resumed.stream.applyingDeltas).toBe(true);
    expect(resumed.stream.resyncRequired).toBe(false);
    expect(resumed.server.lastSequence).toBe(103);

    const applied = reduceStream(resumed, estimateEnvelope(104, 5));
    expect(applied.server.lastSequence).toBe(104);
  });

  it('ignores a duplicate sequence without triggering a resync', () => {
    const base = boundSlice();
    const next = reduceStream(base, estimateEnvelope(100, 5));
    expect(next.stream.rejections.at(-1)?.reason).toBe('duplicate_sequence');
    expect(next.stream.resyncRequired).toBe(false);
  });

  it('honours a coalesced telemetry sequence range', () => {
    const base = boundSlice();
    const next = reduceStream(
      base,
      telemetryEnvelope(105, { coalescedFrom: 101, coalescedTo: 105 }),
    );
    expect(next.server.lastSequence).toBe(105);
    expect(next.stream.resyncRequired).toBe(false);
  });
});

describe('resync_required', () => {
  it('pauses delta application and records the earliest available sequence', () => {
    const base = boundSlice();
    const next = reduceStream(base, resyncEnvelope(140, 250));
    expect(next.stream.applyingDeltas).toBe(false);
    expect(next.stream.resyncRequired).toBe(true);
    expect(next.stream.earliestAvailableSequence).toBe(250);
    expect(next.stream.connection).toBe('resyncing');
  });

  it('is honoured even when its own sequence has a gap', () => {
    const next = reduceStream(boundSlice(), resyncEnvelope(9_999));
    expect(next.stream.resyncRequired).toBe(true);
    expect(next.stream.rejectedEnvelopes).toBe(0);
  });
});

describe('quality_changed', () => {
  it('records the warning and disables time-sensitive actions immediately', () => {
    const base = boundSlice();
    expect(selectTimeSensitiveActionsEnabled(asStoreState(base))).toBe(true);

    const next = reduceStream(base, qualityEnvelope(101, 'stale'));
    expect(next.server.qualityMessage).toBe('Battery energy channel stopped updating.');
    const state = asStoreState(next);
    expect(selectTimeSensitiveActionsEnabled(state)).toBe(false);
    expect(selectTimeSensitiveDisabledReason(state)).toContain('battery_energy_j');
  });

  it('leaves actions enabled for a merely degraded channel', () => {
    const next = reduceStream(boundSlice(), qualityEnvelope(101, 'degraded'));
    expect(selectTimeSensitiveActionsEnabled(asStoreState(next))).toBe(true);
  });
});

describe('heartbeat', () => {
  it('never implies fresh telemetry', () => {
    const withTelemetry = reduceStream(boundSlice(), telemetryEnvelope(101));
    const freshAt = withTelemetry.server.telemetryFreshAtS;
    expect(freshAt).not.toBeNull();

    const beat = reduceStream(withTelemetry, {
      ...heartbeatEnvelope(102),
      session_time_s: 999,
    });
    expect(beat.server.telemetryFreshAtS).toBe(freshAt);
    expect(beat.stream.lastHeartbeatAtS).toBe(999);


    expect(beat.server.sessionTimeS).toBe(withTelemetry.server.sessionTimeS);
  });

  it('never triggers a resync, even far out of sequence', () => {
    const next = reduceStream(boundSlice(), heartbeatEnvelope(50_000));
    expect(next.stream.resyncRequired).toBe(false);
    expect(next.stream.rejectedEnvelopes).toBe(0);
  });
});

describe('rule_context_changed', () => {
  it('marks a named recommendation invalidated', () => {
    const base = boundSlice();
    const id = base.server.recommendation?.id as string;
    const next = reduceStream(base, ruleContextEnvelope(101, [id]));
    expect(next.server.recommendation?.status).toBe('invalidated');
    expect(next.server.invalidatedRecommendationIds).toContain(id);
  });
});

describe('unbound store', () => {
  it('refuses to bind a session from a delta', () => {
    const next = reduceStream(emptySlice(), estimateEnvelope(1, 1));
    expect(next.server.sessionId).toBeNull();
    expect(next.stream.rejections.at(-1)?.reason).toBe('wrong_session');
  });
});

describe('folding a realistic stream', () => {
  it('applies a contiguous run and counts nothing as rejected', () => {
    const result = reduceAll(emptySlice(), [
      snapshotEnvelope(),
      telemetryEnvelope(101),
      estimateEnvelope(102, (SESSION_SNAPSHOT.estimate?.revision ?? 0) + 1),
      executionEnvelope(103),
      heartbeatEnvelope(104),
    ]);
    expect(result.stream.rejectedEnvelopes).toBe(0);
    expect(result.server.lastSequence).toBe(104);
    expect(result.server.executions).toHaveLength(1);
  });
});
