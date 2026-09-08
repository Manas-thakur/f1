
import { toDisplay, tryChannel } from '../../contracts/channels';
import type { ChartAxis, ChartSeries } from './types';

export interface UnitGroup {
  
  readonly key: string;
  
  readonly unit: string;
  readonly decimals: number;
  
  readonly seriesIndices: readonly number[];
  
  readonly side: 1 | 3;
}

export function scaleKeyForUnit(unit: string): string {
  return `y_${unit.replace(/[^A-Za-z0-9]/g, '_')}`;
}

export function displayUnitOf(series: ChartSeries): string {
  return tryChannel(series.channel)?.displayUnit ?? series.unit;
}


export function toDisplayValue(channel: string, value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  const spec = tryChannel(channel);
  return spec === undefined ? value : toDisplay(spec, value);
}


export function unitGroupsFor(series: readonly ChartSeries[]): UnitGroup[] {
  const order: string[] = [];
  const byKey = new Map<string, { unit: string; decimals: number; indices: number[] }>();

  series.forEach((s, index) => {
    const spec = tryChannel(s.channel);
    const unit = displayUnitOf(s);
    const key = scaleKeyForUnit(unit);
    const existing = byKey.get(key);
    if (existing === undefined) {
      order.push(key);
      byKey.set(key, { unit, decimals: spec?.displayDecimals ?? 2, indices: [index] });
    } else {
      existing.indices.push(index);
      existing.decimals = Math.max(existing.decimals, spec?.displayDecimals ?? 2);
    }
  });

  return order.map((key, i) => {
    const group = byKey.get(key) as { unit: string; decimals: number; indices: number[] };
    return {
      key,
      unit: group.unit,
      decimals: group.decimals,
      seriesIndices: group.indices,
      side: i % 2 === 0 ? 3 : 1,
    };
  });
}


export function xAxisLabel(axis: ChartAxis): string {
  return axis === 'progress_m' ? 'distance (m)' : 'session time (s)';
}

export function xAxisUnit(axis: ChartAxis): string {
  return axis === 'progress_m' ? 'm' : 's';
}


export function formatXTick(value: number, axis: ChartAxis): string {
  if (!Number.isFinite(value)) {
    return '';
  }
  if (axis === 'progress_m') {
    return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
  }
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
}

export function formatYTick(value: number, decimals: number): string {
  if (!Number.isFinite(value)) {
    return '';
  }
  const text = value.toFixed(decimals);
  return Number(text) === 0 ? text.replace(/^-/, '') : text;
}


export function axisSizeFor(labels: readonly string[], labelText: string | null): number {
  const widest = labels.reduce((max, label) => Math.max(max, label.length), 0);
  const tickRoom = Math.ceil(widest * 9.5) + 16;
  const labelRoom = labelText === null ? 0 : 20;
  return Math.max(44, tickRoom + labelRoom);
}


export function axesSummary(axis: ChartAxis, groups: readonly UnitGroup[]): string {
  const sides = groups.map(
    (g) => `${g.side === 3 ? 'left' : 'right'} axis in ${g.unit}`,
  );
  return `x axis: ${xAxisLabel(axis)}${sides.length === 0 ? '' : ` — ${sides.join(', ')}`}`;
}
