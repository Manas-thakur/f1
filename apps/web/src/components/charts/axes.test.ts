import { describe, expect, it } from 'vitest';

import { specimenSeries } from '../../fixtures/specimen';
import {
  axesSummary,
  axisSizeFor,
  displayUnitOf,
  formatXTick,
  formatYTick,
  scaleKeyForUnit,
  toDisplayValue,
  unitGroupsFor,
  xAxisLabel,
  xAxisUnit,
} from './axes';
import type { ChartSeries } from './types';

const SERIES = specimenSeries();

function series(channel: string, unit: string, id = channel): ChartSeries {
  return {
    id,
    channel,
    label: id,
    unit,
    provenance: 'simulated',
    xCoordinate: 'progress_m',
    x: [0, 1],
    y: [0, 1],
    nativeResolution: 1,
    sampleCount: 2,
    decimated: false,
    role: 'selected',
  };
}

describe('y values reach the plot in their display unit', () => {
  it('converts through the channel registry, matching the readout tests', () => {
    expect(toDisplayValue('electrical_power_w', 350_000)).toBe(350);
    expect(toDisplayValue('battery_energy_j', 1_500_000)).toBeCloseTo(1.5, 9);
    expect(toDisplayValue('speed_mps', 90)).toBeCloseTo(324, 9);
    expect(toDisplayValue('battery_temperature_k', 273.15)).toBeCloseTo(0, 9);
  });

  it('keeps a null as a gap rather than converting it to zero', () => {
    expect(toDisplayValue('electrical_power_w', null)).toBeNull();
    expect(toDisplayValue('electrical_power_w', Number.NaN)).toBeNull();
  });

  it('leaves an unregistered channel untouched instead of guessing a factor', () => {
    expect(toDisplayValue('not_a_channel', 1234)).toBe(1234);
  });
});

describe('unit groups become separate y scales', () => {
  it('gives the specimen a kW scale and an MJ scale', () => {
    const groups = unitGroupsFor(SERIES);
    expect(groups.map((g) => g.unit)).toEqual(['kW', 'MJ']);

    expect(groups[0]?.seriesIndices).toEqual([0, 1]);
    expect(groups[1]?.seriesIndices).toEqual([2]);
  });

  it('puts the first group on the left and the second on the right', () => {
    const groups = unitGroupsFor(SERIES);
    expect(groups[0]?.side).toBe(3);
    expect(groups[1]?.side).toBe(1);
  });

  it('never lets two units share one scale', () => {
    const groups = unitGroupsFor([
      series('electrical_power_w', 'W'),
      series('battery_energy_j', 'J'),
      series('battery_temperature_k', 'K'),
    ]);
    expect(groups).toHaveLength(3);
    expect(new Set(groups.map((g) => g.key)).size).toBe(3);
  });

  it('groups series that genuinely share a unit', () => {
    const groups = unitGroupsFor([
      series('electrical_power_w', 'W', 'a'),
      series('deploy_power_w', 'W', 'b'),
      series('harvest_power_w', 'W', 'c'),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.unit).toBe('kW');
    expect(groups[0]?.seriesIndices).toEqual([0, 1, 2]);
  });

  it('produces scale keys that are safe for a degree symbol', () => {
    expect(scaleKeyForUnit('°C')).toBe('y__C');
    expect(scaleKeyForUnit('m/s²')).toBe('y_m_s_');
    expect(displayUnitOf(series('battery_temperature_k', 'K'))).toBe('°C');
  });
});

describe('x axis ticks are a physical coordinate', () => {
  it('formats distance in metres, never as a time', () => {
    for (const value of [0, 1000, 2650.5, 5300]) {
      const text = formatXTick(value, 'progress_m');
      expect(text).toMatch(/^-?\d+(\.\d+)?$/);
      expect(text).not.toMatch(/\d{1,2}:\d{2}/);
      expect(text).not.toContain('/');
    }
  });

  it('formats session time in seconds', () => {
    expect(formatXTick(90, 'session_time_s')).toBe('90');
    expect(formatXTick(90.5, 'session_time_s')).toBe('90.5');
  });

  it('always states its unit in the label', () => {
    expect(xAxisLabel('progress_m')).toBe('distance (m)');
    expect(xAxisLabel('session_time_s')).toBe('session time (s)');
    expect(xAxisUnit('progress_m')).toBe('m');
    expect(xAxisUnit('session_time_s')).toBe('s');
  });
});

describe('y axis ticks', () => {
  it('use the group decimals and normalise negative zero', () => {
    expect(formatYTick(350, 0)).toBe('350');
    expect(formatYTick(1.5, 2)).toBe('1.50');
    expect(formatYTick(-0.001, 2)).toBe('0.00');
  });
});

describe('axis width', () => {
  it('grows with the widest label so nothing is clipped', () => {
    const narrow = axisSizeFor(['0', '100', '200'], 'kW');
    const wide = axisSizeFor(['0', '600,000', '1,200,000'], 'W');
    expect(wide).toBeGreaterThan(narrow);

    expect(wide).toBeGreaterThan(50);
  });

  it('never returns less than a usable minimum', () => {
    expect(axisSizeFor([], null)).toBeGreaterThanOrEqual(44);
  });
});

describe('axesSummary', () => {
  it('states the x coordinate and every y unit with its side', () => {
    const summary = axesSummary('progress_m', unitGroupsFor(SERIES));
    expect(summary).toContain('distance (m)');
    expect(summary).toContain('left axis in kW');
    expect(summary).toContain('right axis in MJ');
  });
});
