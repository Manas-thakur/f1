import { basisOf, ground, projectAll, toPointsAttr } from "./camera";
import type { Camera } from "./camera";

const LENGTH = 5.4;
const WIDTH = 1.9;

const body: readonly (readonly [number, number])[] = [
  [0.5, 0],
  [0.34, 0.13],
  [0.1, 0.17],
  [-0.06, 0.3],
  [-0.26, 0.3],
  [-0.32, 0.17],
  [-0.5, 0.14],
  [-0.5, -0.14],
  [-0.32, -0.17],
  [-0.26, -0.3],
  [-0.06, -0.3],
  [0.1, -0.17],
  [0.34, -0.13],
];

const wings: readonly (readonly [number, number, number, number])[] = [
  [0.46, 0, 0.06, 0.92],
  [-0.47, 0, 0.07, 0.8],
];

const wheels: readonly (readonly [number, number])[] = [
  [0.27, 0.4],
  [0.27, -0.4],
  [-0.28, 0.44],
  [-0.28, -0.44],
];

export type CarProps = {
  readonly camera: Camera;
  readonly x: number;
  readonly z: number;
  readonly fill: string;
  readonly stroke: string;
  readonly opacity?: number | undefined;
  readonly scale?: number | undefined;
};

export const Car = ({ camera, x, z, fill, stroke, opacity, scale }: CarProps) => {
  const basis = basisOf(camera);
  const k = scale ?? 1;
  const at = (u: number, v: number) => ground(x + u * LENGTH * k, z + v * WIDTH * k);
  const shell = projectAll(basis, body.map(([u, v]) => at(u, v)));
  if (shell.some((p) => !p.visible)) return null;
  return (
    <g opacity={opacity ?? 1}>
      {wings.map(([u, v, hu, hv]) => {
        const q = projectAll(basis, [
          at(u - hu / 2, v - hv / 2),
          at(u + hu / 2, v - hv / 2),
          at(u + hu / 2, v + hv / 2),
          at(u - hu / 2, v + hv / 2),
        ]);
        return <polygon key={`w${u}`} points={toPointsAttr(q)} fill={stroke} />;
      })}
      {wheels.map(([u, v]) => {
        const q = projectAll(basis, [
          at(u - 0.09, v - 0.09),
          at(u + 0.09, v - 0.09),
          at(u + 0.09, v + 0.09),
          at(u - 0.09, v + 0.09),
        ]);
        return <polygon key={`t${u}${v}`} points={toPointsAttr(q)} fill={stroke} opacity={0.85} />;
      })}
      <polygon points={toPointsAttr(shell)} fill={fill} stroke={stroke} strokeWidth={Math.max(1.2, 2 * k)} />
    </g>
  );
};
