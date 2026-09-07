/**
 * Axis construction for the plot.
 *
 * Two rules this module exists to enforce, both of which were broken by
 * handing uPlot raw SI values and letting it pick its own defaults:
 *
 *  1. The x axis is a physical coordinate — distance in metres or session time
 *     in seconds. It is never a wall-clock time. uPlot's x scale defaults to
 *     `time: true`, which formats a progress value of 20 000 m as "5:33am" on
 *     1/1/70. That is not a cosmetic defect: it is a plausible-looking axis
 *     that says something false about the data.
 *
 *  2. Y values are converted to the channel's display unit *before* they reach
 *     the plot, so the painted axis and the legend agree. Series whose display
 *     units differ get separate scales, so a kW trace is not flattened onto the
 *     baseline by an MJ trace six orders of magnitude away.
 */
import { toDisplay, tryChannel } from '../../contracts/channels';
import type { ChartAxis, ChartSeries } from './types';

export interface UnitGroup {
  /** uPlot scale key. */
  readonly key: string;
  /** Display unit, e.g. "kW". Painted as the axis label. */
  readonly unit: string;
  readonly decimals: number;
  /** Indices into the series array that share this scale. */
  readonly seriesIndices: readonly number[];
  /** 3 = left, 1 = right, alternating as groups are added. */
  readonly side: 1 | 3;
}

export function scaleKeyForUnit(unit: string): string {
  return `y_${unit.replace(/[^A-Za-z0-9]/g, '_')}`;
}

export function displayUnitOf(series: ChartSeries): string {
  return tryChannel(series.channel)?.displayUnit ?? series.unit;
}

/** Convert one SI sample to the channel's display unit. Null stays null. */
export function toDisplayValue(channel: string, value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  const spec = tryChannel(channel);
  return spec === undefined ? value : toDisplay(spec, value);
}

/**
 * Group series by display unit, in first-appearance order. Each group becomes
 * one y scale and one labelled axis, alternating left and right.
 */
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

/** Human label for the x coordinate, always carrying its unit. */
export function xAxisLabel(axis: ChartAxis): string {
  return axis === 'progress_m' ? 'distance (m)' : 'session time (s)';
}

export function xAxisUnit(axis: ChartAxis): string {
  return axis === 'progress_m' ? 'm' : 's';
}

/** A physical-coordinate tick. Never a date, never a clock time. */
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

/**
 * Width to reserve for a y axis so no tick label is clipped.
 *
 * uPlot's default axis size is a fixed 50px, which cuts the leading digit off
 * a label such as "600,000". Sizing from the widest formatted label is the
 * only way to be sure every tick is fully painted.
 */
export function axisSizeFor(labels: readonly string[], labelText: string | null): number {
  const widest = labels.reduce((max, label) => Math.max(max, label.length), 0);
  const tickRoom = Math.ceil(widest * 7.6) + 16;
  const labelRoom = labelText === null ? 0 : 20;
  return Math.max(44, tickRoom + labelRoom);
}

/** One-line textual description of the axes, for the accessible caption. */
export function axesSummary(axis: ChartAxis, groups: readonly UnitGroup[]): string {
  const sides = groups.map(
    (g) => `${g.side === 3 ? 'left' : 'right'} axis in ${g.unit}`,
  );
  return `x axis: ${xAxisLabel(axis)}${sides.length === 0 ? '' : ` — ${sides.join(', ')}`}`;
}
