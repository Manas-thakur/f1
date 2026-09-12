import { ground } from "./camera";
import type { Camera } from "./camera";
import { GroundLine, GroundShape } from "./Ground";
import { T } from "../theme";

const HALF = 6.2;
const DASH = 3.2;
const GAP = 3.4;

export type TrackProps = {
  readonly camera: Camera;
  readonly centre: number;
};

export const Track = ({ camera, centre }: TrackProps) => {
  const from = centre - 90;
  const to = centre + 90;
  const period = DASH + GAP;
  const first = Math.ceil(from / period) * period;
  const dashes: number[] = [];
  for (let x = first; x <= to; x += period) dashes.push(x);
  return (
    <g>
      <GroundShape
        camera={camera}
        points={[ground(from, -HALF), ground(to, -HALF), ground(to, HALF), ground(from, HALF)]}
        fill="#c9d0d7"
      />
      <GroundLine camera={camera} x1={from} z1={-HALF} x2={to} z2={-HALF} stroke="#95a1ad" strokeWidth={3} />
      <GroundLine camera={camera} x1={from} z1={HALF} x2={to} z2={HALF} stroke="#95a1ad" strokeWidth={3} />
      {dashes.map((x) => (
        <GroundLine
          key={x}
          camera={camera}
          x1={x}
          z1={0}
          x2={x + DASH}
          z2={0}
          stroke={T.surface}
          strokeWidth={3}
        />
      ))}
    </g>
  );
};
