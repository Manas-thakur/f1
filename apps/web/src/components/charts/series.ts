
import type {
  Recommendation,
  RuleContext,
  TelemetrySeries,
} from '@contracts';

import { fromTelemetrySeries, type ChartSeries, type EventMarker } from './types';
import { telemetryKey } from '@/state';

export interface Domain {
  readonly min: number;
  readonly max: number;
}

export function seriesFor(
  telemetry: Readonly<Record<string, TelemetrySeries>>,
  channel: string,
  carId: string | null,
  options: { label?: string; role?: ChartSeries['role']; events?: readonly EventMarker[] } = {},
): ChartSeries | null {
  const found = telemetry[telemetryKey({ channel, car_id: carId })] ?? telemetry[channel];
  if (found === undefined) {
    return null;
  }
  if ((found.x ?? []).length === 0) {
    return null;
  }
  return fromTelemetrySeries(found, {
    label: options.label ?? channel,
    ...(options.role === undefined ? {} : { role: options.role }),
    ...(options.events === undefined ? {} : { events: options.events }),
  });
}

export function domainOf(series: readonly ChartSeries[]): Domain | null {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const s of series) {
    if (s.x.length === 0) {continue;}
    min = Math.min(min, s.x[0] as number);
    max = Math.max(max, s.x[s.x.length - 1] as number);
  }
  return Number.isFinite(min) && Number.isFinite(max) && max > min ? { min, max } : null;
}


export function decisionMarkers(recommendation: Recommendation | null): readonly EventMarker[] {
  if (recommendation === null) {
    return [];
  }
  const markers: EventMarker[] = [];
  const trigger = recommendation.trigger;
  if (typeof trigger.progress_m === 'number') {
    markers.push({
      kind: 'trigger',
      id: trigger.checkpoint_id ?? `${recommendation.id}-trigger`,
      x: trigger.progress_m,
      label: trigger.description,
      preserveExactly: true,
    });
  }
  for (const outcome of recommendation.outcomes ?? []) {
    markers.push({
      kind: 'checkpoint',
      id: outcome.checkpoint_id,
      x: outcome.progress_m,
      label: outcome.checkpoint_id,
      preserveExactly: true,
    });
  }
  return markers;
}


export function projectedEnergySeries(recommendation: Recommendation | null): ChartSeries | null {
  const outcomes = recommendation?.outcomes ?? [];
  if (recommendation === null || outcomes.length === 0) {
    return null;
  }
  const ordered = [...outcomes].sort((a, b) => a.progress_m - b.progress_m);
  return {
    id: `projected-energy-${recommendation.id}`,
    channel: 'battery_energy_j',
    label: 'projected at checkpoints',
    carId: null,
    unit: 'J',
    provenance: 'estimated',
    xCoordinate: 'progress_m',
    x: ordered.map((o) => o.progress_m),
    y: ordered.map((o) => o.own_energy_j ?? null),
    quantileDefinition: null,
    nativeResolution: null,
    sampleCount: ordered.length,
    decimated: false,
    events: ordered.map((o) => ({
      kind: 'checkpoint',
      id: o.checkpoint_id,
      x: o.progress_m,
      label: o.checkpoint_id,
      preserveExactly: true,
    })),
    role: 'reference',
  };
}


export function energyFloorSeries(
  ruleContext: RuleContext | null,
  domain: Domain | null,
): ChartSeries | null {
  const floor = ruleContext?.applicable_limits?.battery_energy_min_j;
  if (ruleContext === null || domain === null || floor === undefined || floor === null) {
    return null;
  }
  return {
    id: 'energy-floor',
    channel: 'battery_energy_j',
    label: 'energy floor (rule limit)',
    carId: null,
    unit: 'J',
    provenance: 'configured',
    xCoordinate: 'progress_m',
    x: [domain.min, domain.max],
    y: [floor, floor],
    quantileDefinition: null,
    nativeResolution: null,
    sampleCount: 2,
    decimated: false,
    role: 'context',
  };
}


export function compact<T>(items: readonly (T | null)[]): readonly T[] {
  return items.filter((item): item is T => item !== null);
}
