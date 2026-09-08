import { describe, expect, it } from 'vitest';

import { SESSION_SNAPSHOT } from '../test/contractFixtures';
import { qualityEnvelope, telemetryEnvelope } from '../test/envelopes';
import { useSessionStore } from './sessionStore';
import {
  selectCursor,
  selectInspector,
  selectQualitySummary,
  selectTelemetrySeries,
  selectView,
} from './selectors';

function state() {
  return useSessionStore.getState();
}


describe('derived selectors return a stable reference', () => {
  it('selectQualitySummary is identical across calls on unchanged state', () => {
    useSessionStore.getState().applyRestSnapshot(SESSION_SNAPSHOT);
    const first = selectQualitySummary(state());
    const second = selectQualitySummary(state());
    expect(second).toBe(first);
  });

  it('selectQualitySummary is unaffected by a view-only change', () => {
    useSessionStore.getState().applyRestSnapshot(SESSION_SNAPSHOT);
    const before = selectQualitySummary(state());
    useSessionStore.getState().setDensity('compact');
    useSessionStore.getState().setCursor(1234);
    expect(selectQualitySummary(state())).toBe(before);
  });

  it('selectQualitySummary produces a new reference when quality actually changes', () => {
    useSessionStore.getState().applyRestSnapshot(SESSION_SNAPSHOT);
    const before = selectQualitySummary(state());
    useSessionStore.getState().applyEnvelope(qualityEnvelope(101, 'stale'));
    const after = selectQualitySummary(state());
    expect(after).not.toBe(before);
    expect(after.blocking).toBe(true);
  });

  it('selectCursor is identical across calls and survives a server change', () => {
    useSessionStore.getState().applyRestSnapshot(SESSION_SNAPSHOT);
    const first = selectCursor(state());
    expect(selectCursor(state())).toBe(first);

    useSessionStore.getState().applyEnvelope(telemetryEnvelope(101));
    expect(selectCursor(state())).toBe(first);

    useSessionStore.getState().setCursor(2500);
    expect(selectCursor(state())).not.toBe(first);
    expect(selectCursor(state()).value).toBe(2500);
  });

  it('selectTelemetrySeries is identical until telemetry actually changes', () => {
    useSessionStore.getState().applyRestSnapshot(SESSION_SNAPSHOT);
    const empty = selectTelemetrySeries(state());
    expect(selectTelemetrySeries(state())).toBe(empty);

    useSessionStore.getState().applyEnvelope(telemetryEnvelope(101));
    const withSeries = selectTelemetrySeries(state());
    expect(withSeries).not.toBe(empty);
    expect(withSeries).toHaveLength(1);
    expect(selectTelemetrySeries(state())).toBe(withSeries);
  });

  it('selectView and selectInspector were already stable', () => {
    const view = selectView(state());
    const inspector = selectInspector(state());
    expect(selectView(state())).toBe(view);
    expect(selectInspector(state())).toBe(inspector);

    useSessionStore.getState().openInspector('evidence', 'rec-001', 'btn-1');
    expect(selectInspector(state())).not.toBe(inspector);
    expect(selectInspector(state()).open).toBe(true);
  });
});
