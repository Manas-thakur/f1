import { ground } from "../three/camera";
import type { Camera, Vec3 } from "../three/camera";
import { GroundShape } from "../three/Ground";
import { anchor } from "../three/anchor";
import { fade } from "../motion";
import { FONT, T } from "../theme";

const SLOPE = 0.24;

type Band = {
  readonly id: string;
  readonly label: string;
  readonly from: number;
  readonly to: number;
  readonly color: string;
  readonly at: number;
};

const BANDS: readonly Band[] = [
  { id: "attack", label: "ATTACK", from: 3, to: 12, color: T.bad, at: 505 },
  { id: "prepare", label: "PREPARE", from: 12, to: 21, color: T.accent, at: 525 },
  { id: "defend", label: "DEFEND", from: 21, to: 30, color: T.aqua, at: 545 },
  { id: "recover", label: "RECOVER", from: 30, to: 40, color: T.good, at: 565 },
];

const wedge = (originX: number, from: number, to: number): readonly Vec3[] => [
  ground(originX + from, -from * SLOPE),
  ground(originX + to, -to * SLOPE),
  ground(originX + to, to * SLOPE),
  ground(originX + from, from * SLOPE),
];

export type CorridorProps = {
  readonly camera: Camera;
  readonly frame: number;
  readonly originX: number;
};

export const Corridor = ({ camera, frame, originX }: CorridorProps) => {
  const live = fade(frame, 500, 528, 648, 672);
  if (live <= 0) return null;
  const chosen = frame > 600 ? "prepare" : "";
  return (
    <>
      {BANDS.map((b) => {
        const a = fade(frame, b.at, b.at + 22, 648, 672);
        const on = chosen === "" || chosen === b.id;
        return (
          <GroundShape
            key={b.id}
            camera={camera}
            points={wedge(originX, b.from, b.to)}
            fill={b.color}
            fillOpacity={(on ? 0.15 : 0.05) * a}
            stroke={b.color}
            strokeWidth={2}
            strokeOpacity={(on ? 0.9 : 0.25) * a}
          />
        );
      })}
    </>
  );
};

export const CorridorLabels = ({
  camera,
  frame,
  originX,
}: CorridorProps) => (
  <>
    {BANDS.map((b) => {
      const a = fade(frame, b.at + 6, b.at + 26, 648, 672);
      if (a <= 0) return null;
      const mid = (b.from + b.to) / 2;
      const p = anchor(camera, originX + mid, 0);
      const on = frame <= 600 || b.id === "prepare";
      return (
        <div
          key={b.id}
          style={{
            position: "absolute",
            left: p.x - 160,
            top: p.y - 18,
            width: 320,
            textAlign: "center",
            fontFamily: FONT.body,
            fontSize: 23,
            letterSpacing: "0.06em",
            color: b.color,
            opacity: a * (on ? 1 : 0.35),
          }}
        >
          {b.label}
        </div>
      );
    })}
  </>
);
