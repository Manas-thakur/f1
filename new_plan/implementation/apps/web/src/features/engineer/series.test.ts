import { describe, expect, it } from 'vitest';
import type { TelemetrySeries } from '@contracts';

import {
  compact,
  decisionMarkers,
  domainOf,
  energyFloorSeries,
  projectedEnergySeries,
  seriesFor,
} from './series';
import { RECOMMENDATION_FIXTURE, RULES, energySeries, recommendation, ruleContext } from './testFixtures';

const telemetry: Readonly<Record<string, TelemetrySeries>> = {
  'battery_energy_j@car-01': energySeries(),
};

describe('telemetry series adaptation', () => {
  it('finds a series keyed by channel and car', () => {
    const series = seriesFor(telemetry, 'battery_energy_j', 'car-01', { label: 'stored energy' });
    expect(series?.label).toBe('stored energy');
    expect(series?.unit).toBe('J');
    expect(series?.xCoordinate).toBe('progress_m');
    expect(series?.sampleCount).toBe(5);
  });

  it('returns null rather than an empty plot when the channel has not arrived', () => {
    expect(seriesFor(telemetry, 'speed_mps', 'car-01')).toBeNull();
  });

  it('returns null for a published series that carries no samples', () => {
    const empty: Record<string, TelemetrySeries> = {
      gap_ahead_s: { ...energySeries(), channel: 'gap_ahead_s', car_id: null, x: [], y: [] },
    };
    expect(seriesFor(empty, 'gap_ahead_s', null)).toBeNull();
  });
});

describe('decision markers', () => {
  it('carries the trigger and every checkpoint, all preserved exactly', () => {
    const markers = decisionMarkers(RECOMMENDATION_FIXTURE);
    expect(markers.map((marker) => marker.kind)).toEqual(['trigger', 'checkpoint']);
    expect(markers.every((marker) => marker.preserveExactly === true)).toBe(true);
    expect(markers[0]?.x).toBe(1900);
    expect(markers[1]?.x).toBe(2100);
  });

  it('is empty when there is no recommendation', () => {
    expect(decisionMarkers(null)).toEqual([]);
  });
});

describe('projected energy', () => {
  it('plots the planner’s own checkpoint outcomes as an estimated reference', () => {
    const series = projectedEnergySeries(RECOMMENDATION_FIXTURE);
    expect(series?.role).toBe('reference');
    expect(series?.provenance).toBe('estimated');
    expect(series?.x).toEqual([2100]);
    expect(series?.y).toEqual([1_880_000]);
  });

  it('keeps a checkpoint with no predicted energy as null, never as zero', () => {
    const series = projectedEnergySeries(
      recommendation({
        outcomes: [
          { checkpoint_id: 'a', progress_m: 2000, own_energy_j: null },
          { checkpoint_id: 'b', progress_m: 2100, own_energy_j: 1_000_000 },
        ],
      }),
    );
    expect(series?.y).toEqual([null, 1_000_000]);
    expect(series?.y).not.toContain(0);
  });

  it('produces nothing when the plan publishes no checkpoint outcome', () => {
    expect(projectedEnergySeries(recommendation({ outcomes: [] }))).toBeNull();
  });
});

describe('the configured energy floor', () => {
  it('is a two-point configured line across the panel domain', () => {
    const domain = { min: 1900, max: 2100 };
    const series = energyFloorSeries(RULES, domain);
    expect(series?.provenance).toBe('configured');
    expect(series?.role).toBe('context');
    expect(series?.x).toEqual([1900, 2100]);
    expect(series?.y).toEqual([0, 0]);
  });

  it('is absent when the rule context declares no floor', () => {
    expect(
      energyFloorSeries(ruleContext({ applicable_limits: {} }), { min: 0, max: 1 }),
    ).toBeNull();
  });

  it('is absent when there is no domain to draw it across', () => {
    expect(energyFloorSeries(RULES, null)).toBeNull();
  });
});

describe('domain', () => {
  it('spans every series', () => {
    const series = compact([
      seriesFor(telemetry, 'battery_energy_j', 'car-01'),
      projectedEnergySeries(RECOMMENDATION_FIXTURE),
    ]);
    expect(domainOf(series)).toEqual({ min: 1900, max: 2100 });
  });

  it('is null when nothing has samples', () => {
    expect(domainOf([])).toBeNull();
  });
});
