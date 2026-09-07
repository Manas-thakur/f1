/**
 * Selectors are the public read surface of the session store.
 *
 * Feature agents import from here rather than reading raw slice shapes, so the
 * store's internals can change without breaking four feature trees.
 *
 * Every selector here returns a stable reference for a given store state, so
 * any of them may be passed straight to `useSessionStore(...)`. Zustand
 * compares snapshots by reference: a selector that built a fresh object on
 * each call would re-render without end. The three that derive an object
 * (`selectQualitySummary`, `selectCursor`, `selectTelemetrySeries`) are
 * memoised on the slice they read, so they only produce a new reference when
 * that slice actually changes.
 */
import type { ChannelQuality, Quality, Recommendation, TelemetrySeries } from '@contracts';

import { isBlockingQuality } from '../contracts/units';
import type { QualitySummary, SessionStoreState, StreamSlice } from './types';

/**
 * Memoise a derived value against the slice it is derived from.
 *
 * The slice object identity is the cache key, so the result is stable for as
 * long as the input is, and entries fall away with the state they belong to.
 */
function weakMemo<Input extends object, Result>(
  compute: (input: Input) => Result,
): (input: Input) => Result {
  const cache = new WeakMap<Input, Result>();
  return (input: Input): Result => {
    const hit = cache.get(input);
    if (hit !== undefined || cache.has(input)) {
      return hit as Result;
    }
    const value = compute(input);
    cache.set(input, value);
    return value;
  };
}

const QUALITY_ORDER: Record<Quality, number> = {
  valid: 0,
  degraded: 1,
  stale: 2,
  missing: 3,
  invalid: 4,
};

export function selectSessionId(s: SessionStoreState): string | null {
  return s.server.sessionId;
}

export function selectManifest(s: SessionStoreState) {
  return s.server.manifest;
}

export function selectEstimate(s: SessionStoreState) {
  return s.server.estimate;
}

export function selectRecommendation(s: SessionStoreState): Recommendation | null {
  return s.server.recommendation;
}

export function selectRuleContext(s: SessionStoreState) {
  return s.server.ruleContext;
}

export function selectRevision(s: SessionStoreState): number {
  return s.server.revision;
}

export function selectLastSequence(s: SessionStoreState): number {
  return s.server.lastSequence;
}

export function selectConnection(s: SessionStoreState) {
  return s.stream.connection;
}

export function selectResyncRequired(s: SessionStoreState): boolean {
  return s.stream.resyncRequired;
}

export function selectRejectedEnvelopeCount(s: SessionStoreState): number {
  return s.stream.rejectedEnvelopes;
}

const telemetrySeriesOf = weakMemo(
  (telemetry: Readonly<Record<string, TelemetrySeries>>): readonly TelemetrySeries[] =>
    Object.values(telemetry),
);

export function selectTelemetrySeries(s: SessionStoreState): readonly TelemetrySeries[] {
  return telemetrySeriesOf(s.server.telemetry);
}

export function selectSeriesByKey(s: SessionStoreState, key: string): TelemetrySeries | null {
  return s.server.telemetry[key] ?? null;
}

/**
 * Session time at which telemetry actually last arrived, or null.
 * A heartbeat never updates this.
 */
export function selectTelemetryFreshAtS(s: SessionStoreState): number | null {
  return s.server.telemetryFreshAtS;
}

export function selectDataAgeS(s: SessionStoreState): number | null {
  const fresh = s.server.telemetryFreshAtS;
  if (fresh === null) {
    return null;
  }
  return Math.max(0, s.server.sessionTimeS - fresh);
}

function worstChannel(channels: readonly ChannelQuality[]): ChannelQuality | null {
  let worst: ChannelQuality | null = null;
  for (const c of channels) {
    if (worst === null || QUALITY_ORDER[c.quality] > QUALITY_ORDER[worst.quality]) {
      worst = c;
    }
  }
  return worst;
}

const qualitySummaryOf = weakMemo((server: SessionStoreState['server']): QualitySummary => {
  const overall = server.quality?.overall ?? null;
  const worst = worstChannel(server.channelQuality);
  const blocking = isBlockingQuality(overall) || isBlockingQuality(worst?.quality);
  let reason: string | null = null;
  if (blocking) {
    if (isBlockingQuality(overall)) {
      reason = `Estimate quality is ${overall}.`;
    } else if (worst) {
      reason = `Channel ${worst.channel} is ${worst.quality}.`;
    }
  } else if (server.qualityMessage) {
    reason = server.qualityMessage;
  }
  return { overall, worstChannel: worst, blocking, reason };
});

/** Stable for a given server slice; safe to pass straight to the hook. */
export function selectQualitySummary(s: SessionStoreState): QualitySummary {
  return qualitySummaryOf(s.server);
}

/**
 * Whether a time-sensitive action (select, communicate, driver action) may be
 * offered at all. A quality change disables these immediately.
 */
export function selectTimeSensitiveActionsEnabled(s: SessionStoreState): boolean {
  if (s.stream.resyncRequired || !s.stream.applyingDeltas) {
    return false;
  }
  return !selectQualitySummary(s).blocking;
}

export function selectTimeSensitiveDisabledReason(s: SessionStoreState): string | null {
  if (s.stream.resyncRequired || !s.stream.applyingDeltas) {
    return 'Stream is resynchronising; the displayed state may be behind the server.';
  }
  const summary = selectQualitySummary(s);
  return summary.blocking ? summary.reason : null;
}

export function selectIsRequestPending(s: SessionStoreState, key: string): boolean {
  return s.request.inFlight[key] !== undefined;
}

export function selectAnyRequestPending(s: SessionStoreState): boolean {
  return Object.keys(s.request.inFlight).length > 0;
}

export function selectRequestError(s: SessionStoreState) {
  return s.request.lastError;
}

export function selectHasConflict(s: SessionStoreState, key: string): boolean {
  return s.request.conflictedKeys.includes(key);
}

/** Already a stable reference: the store replaces `view` only when it changes. */
export function selectView(s: SessionStoreState) {
  return s.view;
}

const cursorOf = weakMemo((view: SessionStoreState['view']) => ({
  axis: view.cursorAxis,
  value: view.cursorValue,
}));

/** Stable for a given view slice; safe to pass straight to the hook. */
export function selectCursor(s: SessionStoreState): { axis: string; value: number | null } {
  return cursorOf(s.view);
}

/** Already a stable reference; the store replaces the object on open/close. */
export function selectInspector(s: SessionStoreState) {
  return s.view.inspector;
}

export function selectDensity(s: SessionStoreState) {
  return s.view.density;
}

export function selectMotion(s: SessionStoreState) {
  return s.view.motion;
}

/** Convenience for reducer tests: extract the reducer's slice from the store. */
export function toStreamSlice(s: SessionStoreState): StreamSlice {
  return { server: s.server, stream: s.stream };
}
