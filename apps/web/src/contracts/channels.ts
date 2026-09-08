
import type { Provenance } from '@contracts';

export interface ChannelSpec {
  readonly name: string;
  
  readonly unit: string;
  readonly displayUnit: string;
  readonly displayScale: number;
  readonly displayOffset: number;
  readonly displayDecimals: number;
  readonly family: string;
  readonly expectedProvenance: readonly Provenance[];
  
  readonly plotColourToken: string;
  readonly lowerBound: number | null;
  readonly upperBound: number | null;
  readonly note: string | null;
}

function spec(partial: {
  name: string;
  unit: string;
  displayUnit: string;
  displayScale: number;
  displayOffset?: number;
  displayDecimals: number;
  family: string;
  expectedProvenance: readonly Provenance[];
  plotColourToken: string;
  lowerBound?: number | null;
  upperBound?: number | null;
  note?: string | null;
}): ChannelSpec {
  return {
    displayOffset: 0,
    lowerBound: null,
    upperBound: null,
    note: null,
    ...partial,
  };
}

export const CHANNELS: readonly ChannelSpec[] = [
  spec({
    name: 'speed_mps',
    unit: 'm/s',
    displayUnit: 'km/h',
    displayScale: 3.6,
    displayDecimals: 0,
    family: 'motion',
    expectedProvenance: ['measured', 'simulated'],
    plotColourToken: '--series-speed',
    lowerBound: 0,
    upperBound: 120,
  }),
  spec({
    name: 'acceleration_mps2',
    unit: 'm/s^2',
    displayUnit: 'm/s²',
    displayScale: 1,
    displayDecimals: 2,
    family: 'motion',
    expectedProvenance: ['estimated', 'simulated'],
    plotColourToken: '--series-accel',
    lowerBound: -80,
    upperBound: 40,
  }),
  spec({
    name: 'progress_m',
    unit: 'm',
    displayUnit: 'm',
    displayScale: 1,
    displayDecimals: 0,
    family: 'motion',
    expectedProvenance: ['measured', 'simulated'],
    plotColourToken: '--series-progress',
    lowerBound: 0,
  }),
  spec({
    name: 'lap_distance_m',
    unit: 'm',
    displayUnit: 'm',
    displayScale: 1,
    displayDecimals: 0,
    family: 'motion',
    expectedProvenance: ['measured', 'simulated'],
    plotColourToken: '--series-progress',
    lowerBound: 0,
  }),
  spec({
    name: 'battery_energy_j',
    unit: 'J',
    displayUnit: 'MJ',
    displayScale: 1e-6,
    displayDecimals: 2,
    family: 'electrical',
    expectedProvenance: ['measured', 'simulated', 'estimated'],
    plotColourToken: '--series-energy',
    lowerBound: 0,
    note: 'Battery-side stored energy. Not interchangeable with the CU-K recharge ledger.',
  }),
  spec({
    name: 'electrical_power_w',
    unit: 'W',
    displayUnit: 'kW',
    displayScale: 1e-3,
    displayDecimals: 0,
    family: 'electrical',
    expectedProvenance: ['measured', 'simulated'],
    plotColourToken: '--series-power',
    note: 'Signed DC-bus power: positive deploys, negative harvests. Documented convention.',
  }),
  spec({
    name: 'deploy_power_w',
    unit: 'W',
    displayUnit: 'kW',
    displayScale: 1e-3,
    displayDecimals: 0,
    family: 'electrical',
    expectedProvenance: ['simulated', 'measured'],
    plotColourToken: '--series-power',
    lowerBound: 0,
  }),
  spec({
    name: 'harvest_power_w',
    unit: 'W',
    displayUnit: 'kW',
    displayScale: 1e-3,
    displayDecimals: 0,
    family: 'electrical',
    expectedProvenance: ['simulated', 'measured'],
    plotColourToken: '--series-harvest',
    lowerBound: 0,
    note: 'Separately named nonnegative flow; never netted against deploy without a stated convention.',
  }),
  spec({
    name: 'recharge_ledger_j',
    unit: 'J',
    displayUnit: 'MJ',
    displayScale: 1e-6,
    displayDecimals: 2,
    family: 'electrical',
    expectedProvenance: ['simulated', 'estimated'],
    plotColourToken: '--series-ledger',
    lowerBound: 0,
    note: 'Regulatory CU-K bus ledger, integrated at its specified bus, not battery gain.',
  }),
  spec({
    name: 'battery_temperature_k',
    unit: 'K',
    displayUnit: '°C',
    displayScale: 1,
    displayOffset: -273.15,
    displayDecimals: 0,
    family: 'thermal',
    expectedProvenance: ['measured', 'simulated'],
    plotColourToken: '--series-thermal',
    lowerBound: 200,
    upperBound: 450,
  }),
  spec({
    name: 'gap_ahead_s',
    unit: 's',
    displayUnit: 's',
    displayScale: 1,
    displayDecimals: 2,
    family: 'battle',
    expectedProvenance: ['estimated', 'simulated'],
    plotColourToken: '--series-gap',
    note: 'Derived at common progress, not by dividing distance by instantaneous speed.',
  }),
  spec({
    name: 'gap_behind_s',
    unit: 's',
    displayUnit: 's',
    displayScale: 1,
    displayDecimals: 2,
    family: 'battle',
    expectedProvenance: ['estimated', 'simulated'],
    plotColourToken: '--series-gap',
  }),
  spec({
    name: 'lateral_position_m',
    unit: 'm',
    displayUnit: 'm',
    displayScale: 1,
    displayDecimals: 2,
    family: 'geometry',
    expectedProvenance: ['simulated'],
    plotColourToken: '--series-lateral',
    note: 'Frenet lateral coordinate, positive left. Public feeds cannot supply this reliably.',
  }),
] as const;

export const CHANNELS_BY_NAME: ReadonlyMap<string, ChannelSpec> = new Map(
  CHANNELS.map((c) => [c.name, c]),
);

export const CHANNEL_FAMILIES: readonly string[] = [
  ...new Set(CHANNELS.map((c) => c.family)),
].sort();

export function isRegisteredChannel(name: string): boolean {
  return CHANNELS_BY_NAME.has(name);
}


export function channel(name: string): ChannelSpec {
  const found = CHANNELS_BY_NAME.get(name);
  if (found === undefined) {
    throw new Error(
      `unknown channel ${JSON.stringify(name)}; register it in afterlap_contracts.registry before use`,
    );
  }
  return found;
}


export function tryChannel(name: string): ChannelSpec | undefined {
  return CHANNELS_BY_NAME.get(name);
}


export function toDisplay(spec: ChannelSpec, siValue: number): number {
  return siValue * spec.displayScale + spec.displayOffset;
}

export function fromDisplay(spec: ChannelSpec, displayValue: number): number {
  return (displayValue - spec.displayOffset) / spec.displayScale;
}


export function seriesColourVar(spec: ChannelSpec, surface: 'chrome' | 'well'): string {
  return surface === 'well' ? `var(${spec.plotColourToken}-well)` : `var(${spec.plotColourToken})`;
}
