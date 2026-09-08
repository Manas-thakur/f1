import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { IntervalValue } from '@contracts';

import {
  RIVAL_ENERGY_COVERAGE,
  RIVAL_ENERGY_QUANTILE_NOTE,
  describeInterval,
  intervalKindLine,
} from './intervals';
import { rivalWithQuantile } from './testFixtures';

describe('a quantile interval is described as a model quantile', () => {
  it('names the kind and the nominal label for the shipped rival belief', () => {
    const interval = rivalWithQuantile().energy_interval_j ?? null;
    expect(interval).not.toBeNull();
    expect(interval?.kind).toBe('quantile');

    const described = describeInterval(interval);
    expect(described?.kindText).toBe('model quantile');
    expect(described?.nominalText).toBe('nominal 90% label');
    expect(described?.optimistic).toBe(true);
    expect(intervalKindLine(interval)).toBe('model quantile, nominal 90% label');
  });

  it('never uses the word confidence for a quantile', () => {
    const described = describeInterval(rivalWithQuantile().energy_interval_j ?? null);
    expect(described?.kindText).not.toMatch(/confidence/i);
    expect(intervalKindLine(rivalWithQuantile().energy_interval_j ?? null)).not.toMatch(
      /confidence/i,
    );
  });

  it('reports A05’s measured coverage against the nominal label', () => {
    expect(RIVAL_ENERGY_COVERAGE.measured).toBeCloseTo(0.7885, 4);
    expect(RIVAL_ENERGY_COVERAGE.nominal).toBe(0.9);
    expect(RIVAL_ENERGY_QUANTILE_NOTE).toContain('0.7885');
    expect(RIVAL_ENERGY_QUANTILE_NOTE).toContain('156 samples');
    expect(RIVAL_ENERGY_QUANTILE_NOTE).toContain('optimistic');
    expect(RIVAL_ENERGY_QUANTILE_NOTE).toContain('belief, not a measurement');
  });

  it('keeps the declared kind for an interval that really is a confidence interval', () => {
    const interval: IntervalValue = {
      lower: 1,
      upper: 2,
      unit: 'J',
      kind: 'confidence_interval',
      coverage: 0.95,
      provenance: 'estimated',
    };
    const described = describeInterval(interval);
    expect(described?.kindText).toBe('confidence interval');
    expect(described?.optimistic).toBe(false);
  });

  it('describes physical bounds as bounds, with no coverage claim', () => {
    const interval: IntervalValue = {
      lower: 0,
      upper: 4_000_000,
      unit: 'J',
      kind: 'physical_bounds',
      coverage: null,
      provenance: 'configured',
    };
    const described = describeInterval(interval);
    expect(described?.kindText).toBe('physical bounds');
    expect(described?.nominalText).toBeNull();
  });

  it('says so plainly when no interval was published', () => {
    expect(describeInterval(null)).toBeNull();
    expect(intervalKindLine(undefined)).toBe('no interval published');
  });
});


const PERCENT = '%';
const FORBIDDEN = [
  `90${PERCENT} confidence`,
  `90 ${PERCENT} confidence`,
  `90${PERCENT} confident`,
];

function sourceFiles(directory: string): readonly string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      found.push(...sourceFiles(path));
    } else if (/\.(ts|tsx|css|html)$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

describe('the string "90 per cent confidence" appears nowhere in the product', () => {
  it('is absent from every source file under src/', () => {

    const root = join(process.cwd(), 'src');
    const offenders: string[] = [];
    for (const file of sourceFiles(root)) {
      const text = readFileSync(file, 'utf8').toLowerCase();
      for (const needle of FORBIDDEN) {
        if (text.includes(needle.toLowerCase())) {
          offenders.push(`${file}: ${needle}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
