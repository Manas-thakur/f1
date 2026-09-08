import type { Provenance, TelemetrySeries } from '@contracts';

/**
 * The chart contract every panel in this product obeys.
 *
 * A series is only plottable when it can state, for itself: its unit, where
 * the numbers came from, which x coordinate they are indexed by, when each
 * sample was taken, what a band means if it has one, and which discrete events
 * fall inside its span. A chart that cannot answer those is not drawn.
 */
export type ChartAxis = 'progress_m' | 'session_time_s';

export interface EventMarker {
  /** `checkpoint`, `rule_transition`, `flag`, `decision`, … */
  readonly kind: string;
  readonly id: string;
  /** Position on the series' x axis. */
  readonly x: number;
  readonly label: string;
  /** Markers of these kinds must survive decimation exactly. */
  readonly preserveExactly?: boolean;
}

export interface ChartSeries {
  readonly id: string;
  /** Registered channel name. Drives colour, unit and display scaling. */
  readonly channel: string;
  readonly label: string;
  readonly carId?: string | null;
  /** Internal SI unit of `y`. Display conversion happens at render time. */
  readonly unit: string;
  readonly provenance: Provenance;
  readonly xCoordinate: ChartAxis;
  readonly x: readonly number[];
  readonly y: readonly (number | null)[];
  /** Optional band. `quantileDefinition` must be set when these are present. */
  readonly yLow?: readonly (number | null)[] | null;
  readonly yHigh?: readonly (number | null)[] | null;
  /** e.g. "p10/p90 of 512 scenario rollouts". Never omitted for a band. */
  readonly quantileDefinition?: string | null;
  /** Wall/session timestamps per sample, for exact inspection. */
  readonly sampleTimestampsS?: readonly number[] | null;
  /** Original spacing before any decimation, in x units. */
  readonly nativeResolution: number | null;
  readonly sampleCount: number;
  readonly decimated: boolean;
  readonly events?: readonly EventMarker[];
  /**
   * Reference series render dashed as well as in the reference hue, so the
   * distinction survives greyscale and colour-vision deficiency.
   */
  readonly role: 'selected' | 'reference' | 'context';
}

/** Adapt a transport `TelemetrySeries` to the chart contract. */
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
    x.length >= 2 ? Number(((x[x.length - 1] as number) - (x[0] as number)) / (x.length - 1)) : null;
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
