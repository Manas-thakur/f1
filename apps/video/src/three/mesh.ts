import type { Basis, Vec3 } from "./camera";
import { project } from "./camera";

export type Face = {
  readonly pts: readonly Vec3[];
  readonly rgb: readonly [number, number, number];
  readonly flat?: number | undefined;
};

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const normalise = (a: Vec3): Vec3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

const LIGHT = normalise([-0.42, 0.86, -0.3]);

const shade = (face: Face): string => {
  const [a, b, c] = face.pts as readonly [Vec3, Vec3, Vec3];
  const n = normalise(cross(sub(b, a), sub(c, a)));
  const lambert = Math.abs(n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]);
  const k = face.flat ?? 0.34 + 0.66 * lambert;
  const [r, g, bl] = face.rgb;
  return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(bl * k)})`;
};

export const box = (
  centre: Vec3,
  size: Vec3,
  rgb: readonly [number, number, number],
): readonly Face[] => {
  const [cx, cy, cz] = centre;
  const [sx, sy, sz] = size;
  const x0 = cx - sx / 2;
  const x1 = cx + sx / 2;
  const y0 = cy - sy / 2;
  const y1 = cy + sy / 2;
  const z0 = cz - sz / 2;
  const z1 = cz + sz / 2;
  const p = (x: number, y: number, z: number): Vec3 => [x, y, z];
  return [
    { pts: [p(x0, y1, z0), p(x1, y1, z0), p(x1, y1, z1), p(x0, y1, z1)], rgb },
    { pts: [p(x0, y0, z1), p(x1, y0, z1), p(x1, y0, z0), p(x0, y0, z0)], rgb },
    { pts: [p(x1, y0, z0), p(x1, y0, z1), p(x1, y1, z1), p(x1, y1, z0)], rgb },
    { pts: [p(x0, y0, z1), p(x0, y0, z0), p(x0, y1, z0), p(x0, y1, z1)], rgb },
    { pts: [p(x0, y0, z0), p(x1, y0, z0), p(x1, y1, z0), p(x0, y1, z0)], rgb },
    { pts: [p(x1, y0, z1), p(x0, y0, z1), p(x0, y1, z1), p(x1, y1, z1)], rgb },
  ];
};

export const taper = (
  x0: number,
  x1: number,
  centre: readonly [number, number],
  frontHalf: readonly [number, number],
  backHalf: readonly [number, number],
  rgb: readonly [number, number, number],
): readonly Face[] => {
  const [cy, cz] = centre;
  const [fy, fz] = frontHalf;
  const [by, bz] = backHalf;
  const f = {
    tl: [x0, cy + fy, cz - fz] as Vec3,
    tr: [x0, cy + fy, cz + fz] as Vec3,
    br: [x0, cy - fy, cz + fz] as Vec3,
    bl: [x0, cy - fy, cz - fz] as Vec3,
  };
  const b = {
    tl: [x1, cy + by, cz - bz] as Vec3,
    tr: [x1, cy + by, cz + bz] as Vec3,
    br: [x1, cy - by, cz + bz] as Vec3,
    bl: [x1, cy - by, cz - bz] as Vec3,
  };
  return [
    { pts: [f.tl, b.tl, b.tr, f.tr], rgb },
    { pts: [f.br, b.br, b.bl, f.bl], rgb },
    { pts: [f.tr, b.tr, b.br, f.br], rgb },
    { pts: [f.tl, f.bl, b.bl, b.tl], rgb },
    { pts: [f.tl, f.tr, f.br, f.bl], rgb },
    { pts: [b.tr, b.tl, b.bl, b.br], rgb },
  ];
};

export const wheel = (
  cx: number,
  cy: number,
  cz: number,
  radius: number,
  half: number,
  rgb: readonly [number, number, number],
  segments = 16,
): readonly Face[] => {
  const faces: Face[] = [];
  const ring = (z: number): Vec3[] =>
    Array.from({ length: segments }, (_, i) => {
      const a = (i / segments) * Math.PI * 2;
      return [cx + Math.cos(a) * radius, cy + Math.sin(a) * radius, z] as Vec3;
    });
  const inner = ring(cz - half);
  const outer = ring(cz + half);
  for (let i = 0; i < segments; i += 1) {
    const j = (i + 1) % segments;
    faces.push({
      pts: [
        inner[i] as Vec3,
        inner[j] as Vec3,
        outer[j] as Vec3,
        outer[i] as Vec3,
      ],
      rgb,
    });
  }
  faces.push({ pts: outer, rgb, flat: 0.5 });
  faces.push({ pts: [...inner].reverse(), rgb, flat: 0.3 });
  return faces;
};

export const paint = (basis: Basis, faces: readonly Face[]): readonly string[] => {
  const drawn = faces
    .map((f) => {
      const ps = f.pts.map((p) => project(basis, p));
      if (ps.some((p) => !p.visible)) return null;
      const depth = ps.reduce((s, p) => s + p.depth, 0) / ps.length;
      const pts = ps.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
      return { depth, pts, fill: shade(f) };
    })
    .filter((v): v is { depth: number; pts: string; fill: string } => v !== null)
    .sort((a, b) => b.depth - a.depth);
  return drawn.map((d) => `${d.pts}|${d.fill}`);
};
