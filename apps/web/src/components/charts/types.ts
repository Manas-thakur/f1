import type { Provenance, TelemetrySeries } from '@contracts';


export type ChartAxis = 'progress_m' | 'session_time_s';

export interface EventMarker {
  
  readonly kind: string;
  readonly id: string;
  
  readonly x: number;
  readonly label: string;
  
  readonly preserveExactly?: boolean;
}

export interface ChartSeries {
  readonly id: string;
  
  readonly channel: string;
  readonly label: string;
  readonly carId?: string | null;
  
  readonly unit: string;
  readonly provenance: Provenance;
  readonly xCoordinate: ChartAxis;
  readonly x: readonly number[];
  readonly y: readonly (number | null)[];
  
  readonly yLow?: readonly (number | null)[] | null;
  readonly yHigh?: readonly (number | null)[] | null;
  
  readonly quantileDefinition?: string | null;
  
  readonly sampleTimestampsS?: readonly number[] | null;
  
  readonly nativeResolution: number | null;
  readonly sampleCount: number;
  readonly decimated: boolean;
  readonly events?: readonly EventMarker[];
  
  readonly role: 'selected' | 'reference' | 'context';
}


export function fromTelemetrySeries(
  series: TelemetrySeries,
  options: {
    role?: ChartSeries['role'];
    label?: string;
    events?: readonly EventMarker[];
    sampleTimestampsS?: readonly number[] | null;
  } = {},
): ChartSeries {
  const x = series.x ?? [];
  const y = series.y ?? [];
  const spacing =
    x.length >= 2 ? ((x[x.length - 1] as number) - (x[0] as number)) / (x.length - 1) : null;
  return {
    id: series.car_id ? `${series.channel}@${series.car_id}` : series.channel,
    channel: series.channel,
    label: options.label ?? series.channel,
    carId: series.car_id ?? null,
    unit: series.unit,
    provenance: series.provenance as Provenance,
    xCoordinate: series.x_coordinate,
    x,
    y,
    yLow: series.y_low ?? null,
    yHigh: series.y_high ?? null,
    quantileDefinition: series.quantile_definition ?? null,
    sampleTimestampsS: options.sampleTimestampsS ?? null,
    nativeResolution: spacing !== null && Number.isFinite(spacing) ? spacing : null,
    sampleCount: series.sample_count ?? x.length,
    decimated: series.decimated ?? false,
    ...(options.events === undefined ? {} : { events: options.events }),
    role: options.role ?? 'selected',
  };
}
