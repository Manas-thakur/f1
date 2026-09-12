import { ground, projectAll, toPointsAttr } from "../three/camera";
import type { Basis } from "../three/camera";
import { T } from "../theme";

export type Lane = {
  readonly id: string;
  readonly label: string;
  readonly colour: string;
  readonly z: number;
};

export const LANES: readonly Lane[] = [
  { id: "attack", label: "ATTACK", colour: T.attack, z: -4.6 },
  { id: "prepare", label: "PREPARE", colour: T.prepare, z: -1.55 },
  { id: "defend", label: "DEFEND", colour: T.defend, z: 1.55 },
  { id: "recover", label: "RECOVER", colour: T.recover, z: 4.6 },
];

export const Corridors = ({
  basis,
  originX,
  reach,
  alpha,
  chosen,
}: {
  readonly basis: Basis;
  readonly originX: number;
  readonly reach: number;
  readonly alpha: (id: string) => number;
  readonly chosen: string | null;
}) => (
  <g>
    {LANES.map((lane) => {
      const a = alpha(lane.id);
      if (a <= 0) return null;
      const dim = chosen !== null && chosen !== lane.id ? 0.22 : 1;
      const half = 1.35;
      const pts = toPointsAttr(
        projectAll(basis, [
          ground(originX + 4, lane.z - half),
          ground(originX + 4 + reach, lane.z - half),
          ground(originX + 4 + reach, lane.z + half),
          ground(originX + 4, lane.z + half),
        ]),
      );
      return (
        <g key={lane.id} opacity={a * dim}>
          <polygon points={pts} fill={lane.colour} fillOpacity={0.16} />
          <polygon points={pts} fill="none" stroke={lane.colour} strokeWidth={3} opacity={0.8} />
        </g>
      );
    })}
  </g>
);
