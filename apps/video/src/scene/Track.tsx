import { ground, projectAll, toPointsAttr } from "../three/camera";
import type { Basis } from "../three/camera";
import { T } from "../theme";

const HALF = 7.4;

export const Track = ({ basis, nearX }: { readonly basis: Basis; readonly nearX: number }) => {
  const from = nearX;
  const to = nearX + 230;
  const quad = (x0: number, z0: number, x1: number, z1: number) =>
    toPointsAttr(
      projectAll(basis, [ground(x0, z0), ground(x1, z0), ground(x1, z1), ground(x0, z1)]),
    );

  const period = 14;
  const first = Math.ceil(from / period) * period;
  const dashes: number[] = [];
  for (let x = first; x <= to; x += period) dashes.push(x);

  const kerbStep = 4;
  const kerbFirst = Math.ceil(from / kerbStep) * kerbStep;
  const kerbs: number[] = [];
  for (let x = kerbFirst; x <= to; x += kerbStep) kerbs.push(x);

  return (
    <g>
      <polygon points={quad(from, -HALF - 14, to, HALF + 14)} fill={T.deep} />
      <polygon points={quad(from, -HALF, to, HALF)} fill={T.asphalt} />
      {kerbs.map((x, i) => (
        <g key={x}>
          <polygon
            points={quad(x, -HALF - 1.4, x + kerbStep, -HALF)}
            fill={i % 2 === 0 ? T.kerbA : T.kerbB}
          />
          <polygon
            points={quad(x, HALF, x + kerbStep, HALF + 1.4)}
            fill={i % 2 === 0 ? T.kerbB : T.kerbA}
          />
        </g>
      ))}
      {dashes.map((x) => (
        <polygon key={`d${x}`} points={quad(x, -0.16, x + 6, 0.16)} fill={T.line} opacity={0.42} />
      ))}
    </g>
  );
};
