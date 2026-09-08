
import type {
  ChannelQuality,
  EstimateUpdatedPayload,
  ExecutionObservedPayload,
  ExperimentProgressPayload,
  HeartbeatPayload,
  QualityChangedPayload,
  RecommendationUpdatedPayload,
  ResyncRequiredPayload,
  RuleContextChangedPayload,
  SessionSnapshot,
  SnapshotPayload,
  StreamEnvelope,
  TelemetrySeries,
  TelemetryViewPayload,
} from '@contracts';

import {
  INITIAL_SERVER_STATE,
  type EnvelopeRejection,
  type EnvelopeRejectionReason,
  type ServerState,
  type StreamSlice,
} from './types';

const MAX_REJECTIONS_KEPT = 25;
const MAX_EXECUTIONS_KEPT = 200;

export function telemetryKey(series: Pick<TelemetrySeries, 'channel' | 'car_id'>): string {
  return series.car_id ? `${series.channel}@${series.car_id}` : series.channel;
}

function reject(
  slice: StreamSlice,
  envelope: Pick<StreamEnvelope, 'event_type' | 'sequence'> | null,
  reason: EnvelopeRejectionReason,
  detail: string,
): StreamSlice {
  const rejection: EnvelopeRejection = {
    reason,
    eventType: envelope?.event_type ?? null,
    sequence: envelope?.sequence ?? null,
    detail,
  };
  return {
    ...slice,
    stream: {
      ...slice.stream,
      rejectedEnvelopes: slice.stream.rejectedEnvelopes + 1,
      rejections: [...slice.stream.rejections, rejection].slice(-MAX_REJECTIONS_KEPT),
    },
  };
}

function requestResync(
  slice: StreamSlice,
  envelope: StreamEnvelope,
  reason: EnvelopeRejectionReason,
  detail: string,
): StreamSlice {
  const rejected = reject(slice, envelope, reason, detail);
  return {
    ...rejected,
    stream: {
      ...rejected.stream,
      applyingDeltas: false,
      resyncRequired: true,
      resyncReason: detail,
      resyncCount: rejected.stream.resyncCount + 1,
      connection: 'resyncing',
    },
  };
}

function accepted(slice: StreamSlice, server: ServerState, lastSequence: number): StreamSlice {
  return {
    server: { ...server, lastSequence },
    stream: { ...slice.stream, acceptedEnvelopes: slice.stream.acceptedEnvelopes + 1 },
  };
}


export function applySnapshot(slice: StreamSlice, snapshot: SessionSnapshot): StreamSlice {
  const server: ServerState = {
    ...INITIAL_SERVER_STATE,
    sessionId: snapshot.session_id,
    manifest: snapshot.manifest,
    estimate: snapshot.estimate ?? null,
    recommendation: snapshot.recommendation ?? null,
    ruleContext: snapshot.rule_context ?? null,
    quality: snapshot.estimate?.quality ?? null,
    channelQuality: snapshot.estimate?.quality.channels ?? [],
    qualityMessage: null,
    capabilities: snapshot.capabilities ?? null,
    lease: snapshot.lease ?? null,
    revision: snapshot.revision,
    lastSequence: snapshot.last_sequence,
    serverTime: snapshot.server_time,
    sessionTimeS: snapshot.session_time_s,
    status: snapshot.status,


    telemetry: {},
    telemetryFreshAtS: null,
    executions: [],
    experimentProgress: {},
    invalidatedRecommendationIds: [],
  };
  return {
    server,
    stream: {
      ...slice.stream,
      applyingDeltas: true,
      resyncRequired: false,
      resyncReason: null,
      earliestAvailableSequence: null,
      connection: slice.stream.connection === 'idle' ? 'open' : slice.stream.connection,
      acceptedEnvelopes: slice.stream.acceptedEnvelopes + 1,
    },
  };
}

function mergeChannelQuality(
  current: readonly ChannelQuality[],
  incoming: readonly ChannelQuality[],
): ChannelQuality[] {
  const byKey = new Map<string, ChannelQuality>();
  for (const entry of current) {
    byKey.set(`${entry.channel}@${entry.car_id ?? ''}`, entry);
  }
  for (const entry of incoming) {
    byKey.set(`${entry.channel}@${entry.car_id ?? ''}`, entry);
  }
  return [...byKey.values()];
}

function nextSequenceFor(envelope: StreamEnvelope): { from: number; to: number } {
  if (envelope.event_type === 'telemetry_view') {
    const payload = envelope.payload as TelemetryViewPayload;
    return {
      from: payload.coalesced_from_sequence ?? envelope.sequence,
      to: payload.coalesced_to_sequence ?? envelope.sequence,
    };
  }
  return { from: envelope.sequence, to: envelope.sequence };
}


export function reduceStream(slice: StreamSlice, envelope: StreamEnvelope): StreamSlice {
  const { server, stream } = slice;


  if (server.sessionId !== null && envelope.session_id !== server.sessionId) {
    return reject(
      slice,
      envelope,
      'wrong_session',
      `envelope for session ${envelope.session_id}, bound to ${server.sessionId}`,
    );
  }
  if (server.sessionId === null && envelope.event_type !== 'snapshot') {
    return reject(
      slice,
      envelope,
      'wrong_session',
      'no snapshot received yet; a delta cannot bind a session',
    );
  }


  if (envelope.event_type === 'snapshot') {
    const payload = envelope.payload as SnapshotPayload;
    return applySnapshot(slice, payload.snapshot);
  }


  if (envelope.event_type === 'resync_required') {
    const payload = envelope.payload as ResyncRequiredPayload;
    return {
      server,
      stream: {
        ...stream,
        applyingDeltas: false,
        resyncRequired: true,
        resyncReason: payload.reason,
        earliestAvailableSequence: payload.earliest_available_sequence,
        resyncCount: stream.resyncCount + 1,
        connection: 'resyncing',
        acceptedEnvelopes: stream.acceptedEnvelopes + 1,
      },
    };
  }


  if (envelope.event_type === 'heartbeat') {
    const payload = envelope.payload as HeartbeatPayload;
    void payload;
    const advances = envelope.sequence === server.lastSequence + 1;
    return {
      server: advances ? { ...server, lastSequence: envelope.sequence } : server,
      stream: {
        ...stream,
        lastHeartbeatAtS: envelope.session_time_s,
        acceptedEnvelopes: stream.acceptedEnvelopes + 1,
      },
    };
  }


  if (!stream.applyingDeltas) {
    return reject(
      slice,
      envelope,
      'deltas_paused',
      'delta application paused pending a fresh snapshot',
    );
  }


  const { from, to } = nextSequenceFor(envelope);
  const expected = server.lastSequence + 1;
  if (to <= server.lastSequence) {
    return reject(
      slice,
      envelope,
      'duplicate_sequence',
      `sequence ${to} already applied (last ${server.lastSequence})`,
    );
  }
  if (from !== expected) {
    return requestResync(
      slice,
      envelope,
      'sequence_gap',
      `expected sequence ${expected}, received ${from}`,
    );
  }

  const base: ServerState = { ...server, sessionTimeS: envelope.session_time_s };

  switch (envelope.event_type) {
    case 'estimate_updated': {
      const payload = envelope.payload as EstimateUpdatedPayload;
      const incoming = payload.estimate;
      const currentRevision = server.estimate?.revision ?? null;
      if (currentRevision !== null) {
        if (incoming.revision <= currentRevision) {
          return reject(
            slice,
            envelope,
            'stale_estimate_revision',
            `estimate revision ${incoming.revision} is not newer than ${currentRevision}`,
          );
        }
        if (incoming.revision !== currentRevision + 1) {


          return requestResync(
            slice,
            envelope,
            'estimate_revision_skip',
            `estimate revision ${incoming.revision} skips ${currentRevision + 1}`,
          );
        }
      }
      return accepted(
        slice,
        {
          ...base,
          estimate: incoming,
          quality: incoming.quality,
          channelQuality: mergeChannelQuality(server.channelQuality, incoming.quality.channels ?? []),
        },
        to,
      );
    }

    case 'recommendation_updated': {
      const payload = envelope.payload as RecommendationUpdatedPayload;
      const incoming = payload.recommendation;
      if (incoming.session_id !== envelope.session_id) {
        return reject(
          slice,
          envelope,
          'wrong_session',
          `recommendation belongs to session ${incoming.session_id}`,
        );
      }
      const current = server.recommendation;
      if (current !== null) {
        if (current.id === incoming.id && incoming.revision <= current.revision) {
          return reject(
            slice,
            envelope,
            'stale_recommendation',
            `recommendation revision ${incoming.revision} is not newer than ${current.revision}`,
          );
        }
        if (current.id !== incoming.id && incoming.state_revision < current.state_revision) {
          return reject(
            slice,
            envelope,
            'stale_recommendation',
            `recommendation for state revision ${incoming.state_revision} is older than ${current.state_revision}`,
          );
        }
      }
      return accepted(slice, { ...base, recommendation: incoming }, to);
    }

    case 'quality_changed': {
      const payload = envelope.payload as QualityChangedPayload;
      return accepted(
        slice,
        {
          ...base,
          channelQuality: mergeChannelQuality(server.channelQuality, payload.channels ?? []),
          qualityMessage: payload.message ?? null,
        },
        to,
      );
    }

    case 'rule_context_changed': {
      const payload = envelope.payload as RuleContextChangedPayload;
      const invalidated = payload.invalidated_recommendation_ids ?? [];
      const current = server.recommendation;


      const recommendation =
        current !== null && invalidated.includes(current.id)
          ? { ...current, status: 'invalidated' as const }
          : current;
      return accepted(
        slice,
        {
          ...base,
          ruleContext: payload.rule_context,
          recommendation,
          invalidatedRecommendationIds: [
            ...new Set([...server.invalidatedRecommendationIds, ...invalidated]),
          ],
        },
        to,
      );
    }

    case 'execution_observed': {
      const payload = envelope.payload as ExecutionObservedPayload;
      return accepted(
        slice,
        {
          ...base,
          executions: [...server.executions, payload.execution].slice(-MAX_EXECUTIONS_KEPT),
        },
        to,
      );
    }

    case 'telemetry_view': {
      const payload = envelope.payload as TelemetryViewPayload;
      const telemetry = { ...server.telemetry };
      for (const series of payload.series) {
        telemetry[telemetryKey(series)] = series;
      }
      return accepted(
        slice,
        { ...base, telemetry, telemetryFreshAtS: envelope.session_time_s },
        to,
      );
    }

    case 'experiment_progress': {
      const payload = envelope.payload as ExperimentProgressPayload;
      return accepted(
        slice,
        {
          ...base,
          experimentProgress: {
            ...server.experimentProgress,
            [payload.experiment_id]: {
              status: payload.status,
              progress: payload.progress,
              detail: payload.detail ?? null,
            },
          },
        },
        to,
      );
    }

    default: {


      const unreachable: never = envelope.event_type;
      return reject(slice, envelope, 'schema_invalid', `unhandled event type ${String(unreachable)}`);
    }
  }
}


export function reduceAll(slice: StreamSlice, envelopes: readonly StreamEnvelope[]): StreamSlice {
  return envelopes.reduce(reduceStream, slice);
}
