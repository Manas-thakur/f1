

export interface DecimateInput {
  readonly x: readonly number[];
  readonly y: readonly (number | null)[];
  
  readonly maxPoints: number;
  
  readonly preserveX?: readonly number[];
  
  readonly preserveIndices?: readonly number[];
}

export interface DecimateResult {
  readonly x: number[];
  readonly y: (number | null)[];
  
  readonly indices: number[];
  readonly decimated: boolean;
  
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
    if (minIndex >= 0) {keep.add(minIndex);}
    if (maxIndex >= 0) {keep.add(maxIndex);}
    if (sawNull) {

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

    return { value: null, exact: false, nearestX };
  }
  if (x1 === x0) {
    return { value: y0, exact: false, nearestX };
  }
  const t = (target - x0) / (x1 - x0);
  return { value: y0 + t * (y1 - y0), exact: false, nearestX };
}
