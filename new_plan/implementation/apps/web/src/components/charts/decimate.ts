/**
 * Min/max envelope decimation.
 *
 * The only reason to decimate is that a browser cannot usefully paint 200 000
 * points. It is never allowed to change what the operator can see:
 *
 *   - the minimum and the maximum of every bucket are kept, so a one-sample
 *     power spike survives at its exact x and y;
 *   - the first and last samples are kept, so the span does not shrink;
 *   - any index named in `preserveIndices`, and any sample at an x named in
 *     `preserveX` (checkpoints, rule transitions, flag changes), is kept
 *     exactly;
 *   - nulls are preserved as gaps rather than being interpolated away.
 *
 * A power-limit violation cannot be smoothed out of view by this function.
 */

export interface DecimateInput {
  readonly x: readonly number[];
  readonly y: readonly (number | null)[];
  /** Upper bound on the number of output points. Minimum honoured value is 4. */
  readonly maxPoints: number;
  /** X positions that must appear in the output exactly. */
  readonly preserveX?: readonly number[];
  /** Sample indices that must appear in the output exactly. */
  readonly preserveIndices?: readonly number[];
}

export interface DecimateResult {
  readonly x: number[];
  readonly y: (number | null)[];
  /** Indices into the source arrays, ascending. */
  readonly indices: number[];
  readonly decimated: boolean;
  /** Original spacing in x units, or null when it cannot be determined. */
  readonly nativeResolution: number | null;
  readonly sourceSampleCount: number;
}

function nativeResolution(x: readonly number[]): number | null {
  if (x.length < 2) {
    return null;
  }
  const first = x[0] as number;
  const last = x[x.length - 1] as number;
  const spacing = (last - first) / (x.length - 1);
  return Number.isFinite(spacing) ? spacing : null;
}

/** Nearest sample index to an x value, using a binary search on sorted x. */
export function nearestIndex(x: readonly number[], target: number): number {
  if (x.length === 0) {
    return -1;
  }
  let low = 0;
  let high = x.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((x[mid] as number) < target) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  const candidate = low;
  const previous = Math.max(0, low - 1);
  const dCandidate = Math.abs((x[candidate] as number) - target);
  const dPrevious = Math.abs((x[previous] as number) - target);
  return dPrevious <= dCandidate ? previous : candidate;
}

export function decimateMinMax(input: DecimateInput): DecimateResult {
  const { x, y } = input;
  const n = x.length;
  const resolution = nativeResolution(x);
  const maxPoints = Math.max(4, Math.floor(input.maxPoints));

  const forced = new Set<number>();
  if (n > 0) {
    forced.add(0);
    forced.add(n - 1);
  }
  for (const index of input.preserveIndices ?? []) {
    if (Number.isInteger(index) && index >= 0 && index < n) {
      forced.add(index);
    }
  }
  for (const target of input.preserveX ?? []) {
    const index = nearestIndex(x, target);
    if (index >= 0) {
      forced.add(index);
    }
  }

  if (n <= maxPoints) {
    return {
      x: [...x],
      y: [...y],
      indices: Array.from({ length: n }, (_unused, i) => i),
      decimated: false,
      nativeResolution: resolution,
      sourceSampleCount: n,
    };
  }

  // Two points per bucket (the min and the max), plus the forced points.
  const budget = Math.max(2, maxPoints - forced.size);
  const buckets = Math.max(1, Math.floor(budget / 2));
  const bucketSize = n / buckets;

  const keep = new Set<number>(forced);

  for (let b = 0; b < buckets; b += 1) {
    const start = Math.floor(b * bucketSize);
    const end = Math.min(n, Math.floor((b + 1) * bucketSize));
    if (end <= start) {
      continue;
    }
    let minIndex = -1;
    let maxIndex = -1;
    let minValue = Number.POSITIVE_INFINITY;
    let maxValue = Number.NEGATIVE_INFINITY;
    let sawNull = false;
    for (let i = start; i < end; i += 1) {
      const value = y[i];
      if (value === null || value === undefined || !Number.isFinite(value)) {
        sawNull = true;
        continue;
      }
      if (value < minValue) {
        minValue = value;
        minIndex = i;
      }
      if (value > maxValue) {
        maxValue = value;
        maxIndex = i;
      }
    }
    if (minIndex >= 0) keep.add(minIndex);
    if (maxIndex >= 0) keep.add(maxIndex);
    if (sawNull) {
      // Keep one representative gap so a data outage stays visible.
      for (let i = start; i < end; i += 1) {
        const value = y[i];
        if (value === null || value === undefined || !Number.isFinite(value)) {
          keep.add(i);
          break;
        }
      }
    }
  }

  const indices = [...keep].sort((a, b) => a - b);
  return {
    x: indices.map((i) => x[i] as number),
    y: indices.map((i) => y[i] ?? null),
    indices,
    decimated: true,
    nativeResolution: resolution,
    sourceSampleCount: n,
  };
}

/** Linear interpolation for cursor readout only. Never used for storage. */
export function interpolateAt(
  x: readonly number[],
  y: readonly (number | null)[],
  target: number,
): { value: number | null; exact: boolean; nearestX: number | null } {
  if (x.length === 0) {
    return { value: null, exact: false, nearestX: null };
  }
  const first = x[0] as number;
  const last = x[x.length - 1] as number;
  if (target < first || target > last) {
    return { value: null, exact: false, nearestX: null };
  }
  const idx = nearestIndex(x, target);
  const nearestX = x[idx] as number;
  if (nearestX === target) {
    return { value: y[idx] ?? null, exact: true, nearestX };
  }
  const lowIdx = nearestX < target ? idx : Math.max(0, idx - 1);
  const highIdx = Math.min(x.length - 1, lowIdx + 1);
  const x0 = x[lowIdx] as number;
  const x1 = x[highIdx] as number;
  const y0 = y[lowIdx];
  const y1 = y[highIdx];
  if (y0 === null || y0 === undefined || y1 === null || y1 === undefined) {
    // A gap is a gap. Do not bridge it with a straight line.
    return { value: null, exact: false, nearestX };
  }
  if (x1 === x0) {
    return { value: y0, exact: false, nearestX };
  }
  const t = (target - x0) / (x1 - x0);
  return { value: y0 + t * (y1 - y0), exact: false, nearestX };
}
