/**
 * How an interval is described in words.
 *
 * The rule that this module exists to enforce, from A05's handoff and from the
 * program invariants: a `kind="quantile"` interval is a **model quantile**. It
 * is a belief propagated through a simplified model from a broad prior, not a
 * measurement, and it is never described as a confidence bound.
 *
 * A05 measured the rival-energy interval's empirical coverage at **0.7885 on
 * 156 samples against a nominal 0.90 label**. The label is therefore optimistic
 * and the UI says so wherever the interval is shown. A phrase pairing that
 * nominal percentage with the word "confidence" must not appear anywhere in
 * this product; `intervals.test.ts` scans every source file under `src/` and
 * fails if one does.
 */
import type { IntervalValue } from '@contracts';

export interface IntervalDescription {
  /** e.g. "model quantile". Never the word "confidence" for a quantile. */
  readonly kindText: string;
  /** e.g. "nominal 90% label". Null when the payload declares no coverage. */
  readonly nominalText: string | null;
  /** Whether the reader must be warned that the label is not delivered. */
  readonly optimistic: boolean;
  /** One sentence naming what the interval is and is not. */
  readonly caveat: string;
}

/**
 * Measured empirical coverage of the rival stored-energy interval, from A05's
 * calibration run. Reported as a measurement with its sample count, not as a
 * property of the model.
 */
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
  `It is a belief, not a measurement of the rival car.`;

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
    case 'physical_bounds':
    default:
      return {
        kindText: 'physical bounds',
        nominalText: null,
        optimistic: false,
        caveat: 'Hard bounds implied by the configured limits, not a distribution.',
      };
  }
}

/** One line for a readout: "model quantile, nominal 90% label". */
export function intervalKindLine(interval: IntervalValue | null | undefined): string {
  const described = describeInterval(interval);
  if (described === null) {
    return 'no interval published';
  }
  return described.nominalText === null
    ? described.kindText
    : `${described.kindText}, ${described.nominalText}`;
}
