import { ground } from "./camera";
import type { Camera } from "./camera";
import { GroundLine, GroundShape } from "./Ground";
import { T } from "../theme";

const HALF = 10.5;

export type TrackProps = {
  readonly camera: Camera;
  readonly centre: number;
  readonly span?: number | undefined;
};

export const Track = ({ camera, centre, span }: TrackProps) => {
  const reach = span ?? 130;
  const from = centre - reach;
  const to = centre + reach;
  const step = 12;
  const first = Math.ceil(from / step) * step;
  const marks: number[] = [];
  for (let x = first; x <= to; x += step) marks.push(x);
  return (
    <g>
      <GroundShape
        camera={camera}
        points={[ground(from, -HALF), ground(to, -HALF), ground(to, HALF), ground(from, HALF)]}
        fill={T.raised}
      />
      <GroundLine camera={camera} x1={from} z1={-HALF} x2={to} z2={-HALF} stroke={T.rule} strokeWidth={2} />
      <GroundLine camera={camera} x1={from} z1={HALF} x2={to} z2={HALF} stroke={T.rule} strokeWidth={2} />
      <GroundLine
        camera={camera}
        x1={from}
        z1={0}
        x2={to}
        z2={0}
        stroke={T.track}
        strokeWidth={1.5}
        dash="18 16"
      />
      {marks.map((x) => (
        <GroundLine
          key={x}
          camera={camera}
          x1={x}
          z1={-HALF}
          x2={x}
          z2={-HALF + 1.6}
          stroke={T.track}
          strokeWidth={1.5}
        />
      ))}
    </g>
  );
};
