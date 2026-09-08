
import type { ChartSeries, EventMarker } from '../components/charts/types';

const LAP_LENGTH_M = 5300;
const SAMPLES = 265;

function progressAxis(): number[] {
  return Array.from({ length: SAMPLES }, (_unused, i) => (i * LAP_LENGTH_M) / (SAMPLES - 1));
}


function deployProfile(progress: number): number {
  const straights = [
    { at: 400, width: 320, peak: 340_000 },
    { at: 1750, width: 260, peak: 300_000 },
    { at: 3100, width: 420, peak: 350_000 },
    { at: 4550, width: 300, peak: 250_000 },
  ];
  let total = 0;
  for (const s of straights) {
    const d = (progress - s.at) / s.width;
    total += s.peak * Math.exp(-d * d);
  }
  const harvest = -120_000 * Math.exp(-(((progress - 2500) / 500) ** 2));
  return Math.round(total + harvest);
}

function energyProfile(progress: number): number {

  const base = 3_800_000 - (progress / LAP_LENGTH_M) * 1_500_000;
  const recovery = 260_000 * Math.exp(-(((progress - 2500) / 420) ** 2));
  return Math.round(base + recovery);
}

export const SPECIMEN_EVENTS: readonly EventMarker[] = [
  { kind: 'checkpoint', id: 'T7-entry', x: 2960, label: 'T7 entry', preserveExactly: true },
  {
    kind: 'rule_transition',
    id: 'overtake-window',
    x: 3320,
    label: 'Overtake profile window opens',
    preserveExactly: true,
  },
  { kind: 'checkpoint', id: 'T9-exit', x: 4180, label: 'T9 exit', preserveExactly: true },
];

export function specimenSeries(): readonly ChartSeries[] {
  const x = progressAxis();
  const spacing = LAP_LENGTH_M / (SAMPLES - 1);
  return [
    {
      id: 'electrical_power_w@own',
      channel: 'electrical_power_w',
      label: 'Own car deployment',
      carId: 'own',
      unit: 'W',
      provenance: 'simulated',
      xCoordinate: 'progress_m',
      x,
      y: x.map(deployProfile),
      quantileDefinition: null,
      nativeResolution: spacing,
      sampleCount: SAMPLES,
      decimated: false,
      events: SPECIMEN_EVENTS,
      role: 'selected',
    },
    {
      id: 'electrical_power_w@rival',
      channel: 'electrical_power_w',
      label: 'Reference lap deployment',
      carId: 'reference',
      unit: 'W',
      provenance: 'simulated',
      xCoordinate: 'progress_m',
      x,
      y: x.map((p) => Math.round(deployProfile(p) * 0.82 - 12_000)),
      quantileDefinition: null,
      nativeResolution: spacing,
      sampleCount: SAMPLES,
      decimated: false,
      role: 'reference',
    },
    {
      id: 'battery_energy_j@own',
      channel: 'battery_energy_j',
      label: 'Own car stored energy',
      carId: 'own',
      unit: 'J',
      provenance: 'simulated',
      xCoordinate: 'progress_m',
      x,
      y: x.map(energyProfile),
      quantileDefinition: null,
      nativeResolution: spacing,
      sampleCount: SAMPLES,
      decimated: false,
      events: SPECIMEN_EVENTS,
      role: 'selected',
    },
  ];
}


export interface SpecimenReadout {
  readonly label: string;
  readonly channel: string;
  readonly value: number | null;
  readonly provenance: 'simulated' | 'estimated';
  readonly quality: 'valid' | 'degraded' | 'missing';
  readonly ageS: number | null;
  readonly unavailableReason?: string;
}

export const SPECIMEN_READOUTS: readonly SpecimenReadout[] = [
  {
    label: 'Own stored energy',
    channel: 'battery_energy_j',
    value: 2_940_000,
    provenance: 'simulated',
    quality: 'valid',
    ageS: 0.2,
  },
  {
    label: 'Deployment at cursor',
    channel: 'electrical_power_w',
    value: 318_000,
    provenance: 'simulated',
    quality: 'valid',
    ageS: 0.2,
  },
  {
    label: 'Gap to car ahead',
    channel: 'gap_ahead_s',
    value: 0.84,
    provenance: 'estimated',
    quality: 'degraded',
    ageS: 1.4,
  },
  {


    label: 'Rival stored energy',
    channel: 'battery_energy_j',
    value: null,
    provenance: 'estimated',
    quality: 'missing',
    ageS: null,
    unavailableReason: 'No public feed publishes a rival battery state.',
  },
];
