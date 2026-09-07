import { describe, expect, it } from 'vitest';

import { decimateMinMax, interpolateAt, nearestIndex } from './decimate';

function flatSeries(n: number, value = 100): { x: number[]; y: number[] } {
  return {
    x: Array.from({ length: n }, (_unused, i) => i * 10),
    y: Array.from({ length: n }, () => value),
  };
}

describe('decimateMinMax preserves extrema', () => {
  it('keeps a single-sample power spike at its exact x and y', () => {
    const { x, y } = flatSeries(4_000, 120_000);
    const spikeIndex = 1_733;
    y[spikeIndex] = 349_500; // one sample against the 350 kW ceiling
    const spikeX = x[spikeIndex] as number;

    const result = decimateMinMax({ x, y, maxPoints: 200 });

    expect(result.decimated).toBe(true);
    expect(result.x.length).toBeLessThanOrEqual(220);
    expect(result.x.length).toBeLessThan(x.length);

    const at = result.x.indexOf(spikeX);
    expect(at, 'spike x must survive decimation').toBeGreaterThanOrEqual(0);
    expect(result.y[at]).toBe(349_500);
    expect(Math.max(...(result.y.filter((v) => v !== null) as number[]))).toBe(349_500);
  });

  it('keeps a single-sample negative trough as well', () => {
    const { x, y } = flatSeries(3_000, 50_000);
    y[97] = -140_000;
    const troughX = x[97] as number;

    const result = decimateMinMax({ x, y, maxPoints: 120 });
    const at = result.x.indexOf(troughX);
    expect(at).toBeGreaterThanOrEqual(0);
    expect(result.y[at]).toBe(-140_000);
  });

  it('keeps both bounds of the span', () => {
    const { x, y } = flatSeries(5_000);
    const result = decimateMinMax({ x, y, maxPoints: 64 });
    expect(result.x[0]).toBe(x[0]);
    expect(result.x.at(-1)).toBe(x.at(-1));
  });

  it('keeps checkpoint and rule-transition crossings exactly', () => {
    const { x, y } = flatSeries(6_000);
    // Vary y slightly so bucket min/max do not coincidentally land on the
    // event samples; the events must be kept because they were named.
    for (let i = 0; i < y.length; i += 1) {
      y[i] = 100 + Math.sin(i / 37) * 5;
    }
    const events = [x[413] as number, x[2_222] as number, x[5_101] as number];

    const result = decimateMinMax({ x, y, maxPoints: 150, preserveX: events });

    for (const eventX of events) {
      expect(result.x, `event at ${eventX} must survive`).toContain(eventX);
      const at = result.x.indexOf(eventX);
      expect(result.y[at]).toBe(y[x.indexOf(eventX)]);
    }
  });

  it('keeps named indices exactly', () => {
    const { x, y } = flatSeries(2_000);
    const result = decimateMinMax({ x, y, maxPoints: 40, preserveIndices: [7, 1_500] });
    expect(result.indices).toContain(7);
    expect(result.indices).toContain(1_500);
  });

  it('preserves a gap rather than bridging it', () => {
    const { x, y } = flatSeries(1_000);
    const withGap: (number | null)[] = [...y];
    for (let i = 400; i < 460; i += 1) {
      withGap[i] = null;
    }
    const result = decimateMinMax({ x, y: withGap, maxPoints: 100 });
    expect(result.y.some((v) => v === null)).toBe(true);
  });

  it('returns the source untouched when it already fits', () => {
    const { x, y } = flatSeries(50);
    const result = decimateMinMax({ x, y, maxPoints: 900 });
    expect(result.decimated).toBe(false);
    expect(result.x).toEqual(x);
    expect(result.y).toEqual(y);
  });

  it('reports the original sampling resolution and sample count', () => {
    const { x, y } = flatSeries(4_000);
    const result = decimateMinMax({ x, y, maxPoints: 100 });
    expect(result.nativeResolution).toBeCloseTo(10, 9);
    expect(result.sourceSampleCount).toBe(4_000);
  });

  it('handles an empty series without throwing', () => {
    const result = decimateMinMax({ x: [], y: [], maxPoints: 10 });
    expect(result.x).toEqual([]);
    expect(result.decimated).toBe(false);
  });
});

describe('nearestIndex', () => {
  it('finds the closest sample on either side', () => {
    const x = [0, 10, 20, 30];
    expect(nearestIndex(x, 0)).toBe(0);
    expect(nearestIndex(x, 11)).toBe(1);
    expect(nearestIndex(x, 16)).toBe(2);
    expect(nearestIndex(x, 30)).toBe(3);
  });
});

describe('interpolateAt', () => {
  it('marks an exact sample as exact', () => {
    const result = interpolateAt([0, 10, 20], [1, 2, 3], 10);
    expect(result.value).toBe(2);
    expect(result.exact).toBe(true);
  });

  it('interpolates between samples and says it did', () => {
    const result = interpolateAt([0, 10], [0, 100], 2.5);
    expect(result.value).toBeCloseTo(25, 9);
    expect(result.exact).toBe(false);
  });

  it('returns null outside the span rather than extrapolating', () => {
    expect(interpolateAt([0, 10], [0, 100], 50).value).toBeNull();
    expect(interpolateAt([0, 10], [0, 100], -1).value).toBeNull();
  });

  it('does not bridge a null with a straight line', () => {
    expect(interpolateAt([0, 10, 20], [0, null, 100], 5).value).toBeNull();
  });
});
