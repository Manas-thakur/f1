import type { Basis, Vec3 } from "./camera";
import { box, paint, taper, wheel } from "./mesh";
import type { Face } from "./mesh";

const TYRE: readonly [number, number, number] = [26, 28, 32];
const RIM: readonly [number, number, number] = [120, 132, 144];

const shift = (faces: readonly Face[], dx: number, dz: number): readonly Face[] =>
  faces.map((f) => ({
    ...f,
    pts: f.pts.map((p) => [p[0] + dx, p[1], p[2] + dz] as Vec3),
  }));

const build = (
  body: readonly [number, number, number],
  accent: readonly [number, number, number],
): readonly Face[] => {
  const faces: Face[] = [];
  const push = (f: readonly Face[]) => faces.push(...f);
  const dark: readonly [number, number, number] = [20, 23, 27];

  push(box([2.55, 0.11, 0], [0.64, 0.05, 2.0], accent));
  push(box([2.55, 0.2, 0.98], [0.62, 0.28, 0.05], body));
  push(box([2.55, 0.2, -0.98], [0.62, 0.28, 0.05], body));
  push(box([2.2, 0.2, 0], [0.1, 0.2, 0.16], body));

  push(taper(2.3, 1.15, [0.34, 0], [0.07, 0.09], [0.15, 0.2], body));
  push(taper(1.15, 0.15, [0.37, 0], [0.15, 0.2], [0.23, 0.33], body));
  push(taper(0.15, -0.85, [0.4, 0], [0.25, 0.35], [0.29, 0.35], body));
  push(taper(-0.85, -2.0, [0.42, 0], [0.29, 0.35], [0.17, 0.17], accent));
  push(taper(-2.0, -2.5, [0.36, 0], [0.17, 0.17], [0.07, 0.08], accent));

  push(box([0.12, 0.32, 0.73], [1.55, 0.32, 0.34], body));
  push(box([0.12, 0.32, -0.73], [1.55, 0.32, 0.34], body));
  push(box([0.1, 0.06, 0], [4.3, 0.05, 1.5], dark));

  push(box([0.16, 0.6, 0], [0.52, 0.15, 0.4], dark));
  push(box([0.56, 0.73, 0], [0.42, 0.05, 0.78], [86, 94, 104]));
  push(box([0.86, 0.6, 0], [0.06, 0.3, 0.06], [86, 94, 104]));

  push(box([-2.46, 0.94, 0], [0.44, 0.06, 1.58], accent));
  push(box([-2.38, 0.68, 0.73], [0.07, 0.5, 0.05], body));
  push(box([-2.38, 0.68, -0.73], [0.07, 0.5, 0.05], body));
  push(box([-1.55, 0.62, 0], [0.5, 0.2, 0.2], dark));

  const tyre = (x: number, z: number, r: number) => {
    push(wheel(x, r, z, r, 0.2, TYRE));
    push(wheel(x, r, z + (z > 0 ? 0.1 : -0.1), r * 0.5, 0.1, RIM, 12));
  };
  tyre(1.66, 0.82, 0.36);
  tyre(1.66, -0.82, 0.36);
  tyre(-1.7, 0.86, 0.42);
  tyre(-1.7, -0.86, 0.42);

  return faces;
};

export type Car3DProps = {
  readonly basis: Basis;
  readonly x: number;
  readonly z: number;
  readonly body: readonly [number, number, number];
  readonly accent: readonly [number, number, number];
  readonly opacity?: number | undefined;
};

export const Car3D = ({ basis, x, z, body, accent, opacity }: Car3DProps) => {
  const faces = shift(build(body, accent), x, z);
  const polys = paint(basis, faces);
  return (
    <g opacity={opacity ?? 1}>
      {polys.map((p, i) => {
        const [pts, fill] = p.split("|") as [string, string];
        return <polygon key={`${i}-${fill}`} points={pts} fill={fill} />;
      })}
    </g>
  );
};
