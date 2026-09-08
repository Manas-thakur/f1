/**
 * Textual summaries of a chart, for nonvisual review and for the accessible
 * table that accompanies every plot.
 */
import { formatChannelValue } from '../../contracts/units';
import type { ChartSeries } from './types';

export interface SeriesSummary {
  readonly id: string;
  readonly label: string;
  readonly unit: string;
  readonly provenance: string;
  readonly role: ChartSeries['role'];
  readonly sampleCount: number;
  readonly plottedCount: number;
  readonly decimated: boolean;
  readonly nativeResolutionText: string;
  readonly xFromText: string;
  readonly xToText: string;
  readonly minText: string;
  readonly maxText: string;
  readonly meanText: string;
  readonly lastText: string;
  readonly gapCount: number;
  readonly quantileDefinition: string | null;
  readonly eventCount: number;
  readonly sentence: string;
}

function axisUnit(axis: ChartSeries['xCoordinate']): string {
  return axis === 'progress_m' ? 'm' : 's';
}

export function summariseSeries(series: ChartSeries): SeriesSummary {
  const values: number[] = [];
  let gapCount = 0;
  for (const value of series.y) {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      gapCount += 1;
    } else {
      values.push(value);
    }
  }

  const fmt = (v: number | null) => formatChannelValue(series.channel, v).text;
  const min = values.length > 0 ? Math.min(...values) : null;
  const max = values.length > 0 ? Math.max(...values) : null;
  const mean =
    values.length > 0 ? values.reduce((acc, v) => acc + v, 0) / values.length : null;
  const last = values.length > 0 ? (values[values.length - 1] as number) : null;

  const xFrom = series.x.length > 0 ? (series.x[0] as number) : null;
  const xTo = series.x.length > 0 ? (series.x[series.x.length - 1] as number) : null;
  const unit = axisUnit(series.xCoordinate);
  const xFromText = xFrom === null ? 'not available' : `${xFrom.toFixed(0)} ${unit}`;
  const xToText = xTo === null ? 'not available' : `${xTo.toFixed(0)} ${unit}`;

  const nativeResolutionText =
    series.nativeResolution === null
      ? 'sampling resolution unknown'
      : `${series.nativeResolution.toFixed(2)} ${unit} per sample`;

  const sentence =
    values.length === 0
      ? `${series.label}: no values available over ${xFromText} to ${xToText}.`
      : `${series.label} (${series.provenance}, ${series.role} series): ` +
        `${values.length} of ${series.sampleCount} samples between ${xFromText} and ${xToText}; ` +
        `minimum ${fmt(min)}, maximum ${fmt(max)}, mean ${fmt(mean)}, last ${fmt(last)}; ` +
        `${nativeResolutionText}` +
        (series.decimated ? ', drawn from a min/max envelope that preserves extrema' : '') +
        (gapCount > 0 ? `; ${gapCount} sample gaps` : '') +
        '.';

  return {
    id: series.id,
    label: series.label,
    unit: series.unit,
    provenance: series.provenance,
    role: series.role,
    sampleCount: series.sampleCount,
    plottedCount: series.x.length,
    decimated: series.decimated,
    nativeResolutionText,
    xFromText,
    xToText,
    minText: fmt(min),
    maxText: fmt(max),
    meanText: fmt(mean),
    lastText: fmt(last),
    gapCount,
    quantileDefinition: series.quantileDefinition ?? null,
    eventCount: series.events?.length ?? 0,
    sentence,
  };
}

export function summariseChart(title: string, series: readonly ChartSeries[]): string {
  if (series.length === 0) {
    return `${title}: no series available.`;
  }
  return [`${title}. ${series.length} series.`, ...series.map((s) => summariseSeries(s).sentence)].join(
    ' ',
  );
}
