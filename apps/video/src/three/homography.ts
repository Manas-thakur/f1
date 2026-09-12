import type { Projected } from "./camera";

const solve8 = (m: number[][], v: number[]): number[] | null => {
  const n = 8;
  const a = m.map((row, i) => [...row, v[i] as number]);
  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < n; row += 1) {
      if (Math.abs((a[row] as number[])[col] as number) > Math.abs((a[pivot] as number[])[col] as number)) {
        pivot = row;
      }
    }
    const pr = a[pivot] as number[];
    const cr = a[col] as number[];
    a[pivot] = cr;
    a[col] = pr;
    const lead = (a[col] as number[])[col] as number;
    if (Math.abs(lead) < 1e-12) return null;
    for (let k = col; k <= n; k += 1) {
      (a[col] as number[])[k] = ((a[col] as number[])[k] as number) / lead;
    }
    for (let row = 0; row < n; row += 1) {
      if (row === col) continue;
      const factor = (a[row] as number[])[col] as number;
      if (factor === 0) continue;
      for (let k = col; k <= n; k += 1) {
        (a[row] as number[])[k] =
          ((a[row] as number[])[k] as number) - factor * ((a[col] as number[])[k] as number);
      }
    }
  }
  return a.map((row) => row[n] as number);
};

export const quadMatrix3d = (
  width: number,
  height: number,
  corners: readonly [Projected, Projected, Projected, Projected],
): string | null => {
  const src: readonly [number, number][] = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ];
  const rows: number[][] = [];
  const rhs: number[] = [];
  for (let i = 0; i < 4; i += 1) {
    const s = src[i] as [number, number];
    const d = corners[i] as Projected;
    rows.push([s[0], s[1], 1, 0, 0, 0, -s[0] * d.x, -s[1] * d.x]);
    rhs.push(d.x);
    rows.push([0, 0, 0, s[0], s[1], 1, -s[0] * d.y, -s[1] * d.y]);
    rhs.push(d.y);
  }
  const h = solve8(rows, rhs);
  if (!h) return null;
  const [a, b, c, d, e, f, g, i] = h as [
    number,
    number,
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  return `matrix3d(${a},${d},0,${g},${b},${e},0,${i},0,0,1,0,${c},${f},0,1)`;
};
