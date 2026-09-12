
import type { IntervalValue } from '@contracts';

export interface IntervalDescription {
  
  readonly kindText: string;
  
  readonly nominalText: string | null;
  
  readonly optimistic: boolean;
  
  readonly caveat: string;
}


export const RIVAL_ENERGY_COVERAGE = {
  nominal: 0.9,
  measured: 0.7885,
  sampleCount: 156,
  source: 'A05 calibration run, split rival-energy-calibration',
} as const;

export const RIVAL_ENERGY_QUANTILE_NOTE =
  `Model quantile from the opponent belief filter. Nominal ${(RIVAL_ENERGY_COVERAGE.nominal * 100).toFixed(0)}% label; ` +
  `measured empirical coverage ${RIVAL_ENERGY_COVERAGE.measured.toFixed(4)} on ${RIVAL_ENERGY_COVERAGE.sampleCount} samples ` +
  `(${RIVAL_ENERGY_COVERAGE.source}). The label is optimistic: the interval covers less often than it claims. ` +
  'It is a belief, not a measurement of the rival car.';

export function describeInterval(
  interval: IntervalValue | null | undefined,
): IntervalDescription | null {
  if (interval === null || interval === undefined) {
    return null;
  }
  const coverage = interval.coverage ?? null;
  const nominalText =
    coverage === null ? null : `nominal ${(coverage * 100).toFixed(0)}% label`;

  switch (interval.kind) {
    case 'quantile':
      return {
        kindText: 'model quantile',
        nominalText,
        optimistic: true,
        caveat:
          'A model quantile of a simulated belief. Not a confidence bound and not a measurement.',
      };
    case 'confidence_interval':
      return {
        kindText: 'confidence interval',
        nominalText,
        optimistic: false,
        caveat: 'Declared by the producing estimator as a confidence interval.',
      };
    default:
      return {
        kindText: 'physical bounds',
        nominalText: null,
        optimistic: false,
        caveat: 'Hard bounds implied by the configured limits, not a distribution.',
      };
  }
}


export function intervalKindLine(interval: IntervalValue | null | undefined): string {
  const described = describeInterval(interval);
  if (described === null) {
    return 'no interval published';
  }
  return described.nominalText === null
    ? described.kindText
    : `${described.kindText}, ${described.nominalText}`;
}
