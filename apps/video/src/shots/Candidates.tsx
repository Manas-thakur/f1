import { Easing, interpolate, useCurrentFrame } from "remotion";
import { ground, projectAll, basisOf, toPointsAttr } from "../three/camera";
import type { Camera, Vec3 } from "../three/camera";
import { Car } from "../three/Car";
import { Frame } from "../ui/Frame";
import { EASE_OUT, FONT, T, VIDEO } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

const CAMERA: Camera = {
  eye: [1, 5.45894, 0],
  target: [0, 0, 0],
  up: [0, 0, 1],
  fov: 1.3722,
  width: VIDEO.width,
  height: VIDEO.height,
};

const APEX = 0.99355;
const UP_SLOPE = 0.3455;
const DOWN_SLOPE = 0.43342;

type Band = {
  readonly id: string;
  readonly label: string;
  readonly from: number;
  readonly to: number;
  readonly labelX: number;
  readonly color: string;
  readonly at: number;
};

const BANDS: readonly Band[] = [
  { id: "prepare", label: "PREPARE", from: APEX, to: -2.21965, labelX: 1081, color: T.accent, at: 20 },
  { id: "defend", label: "DEFEND", from: -2.21965, to: -5.282, labelX: 1343, color: T.aqua, at: 30 },
  { id: "recover", label: "RECOVER", from: -5.282, to: -9.53467, labelX: 1624, color: T.good, at: 40 },
];

const half = (x: number, slope: number): number => Math.abs(x - APEX) * slope;

const wedge = (from: number, to: number, slope: number): readonly Vec3[] => [
  ground(from, -half(from, slope)),
  ground(to, -half(to, slope)),
  ground(to, half(to, slope)),
  ground(from, half(from, slope)),
];

export const Candidates = () => {
  const frame = useCurrentFrame();
  const basis = basisOf(CAMERA);
  const attack = interpolate(frame, [4, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });

  const poly = (pts: readonly Vec3[]) => toPointsAttr(projectAll(basis, pts));

  return (
    <Frame step="03" title="Score the candidates">
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <g opacity={attack}>
          <polygon
            points={poly(wedge(APEX, 7.2, UP_SLOPE))}
            fill={T.bad}
            fillOpacity={0.14}
            stroke={T.bad}
            strokeWidth={2}
          />
        </g>
        {BANDS.map((b) => {
          const a = interpolate(frame, [b.at, b.at + 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: ease,
          });
          return (
            <polygon
              key={b.id}
              points={poly(wedge(b.from, b.to, DOWN_SLOPE))}
              fill={b.color}
              fillOpacity={0.12 * a}
              stroke={b.color}
              strokeWidth={2}
              strokeOpacity={a}
            />
          );
        })}
        <Car camera={CAMERA} x={2.0} z={-0.62} scale={0.17} fill={T.surface} stroke={T.ink} opacity={attack} />
        <Car camera={CAMERA} x={1.3} z={0.62} scale={0.17} fill={T.surface} stroke={T.muted} opacity={attack} />
      </svg>

      <div
        style={{
          position: "absolute",
          left: 19,
          top: 512,
          width: 600,
          textAlign: "center",
          fontFamily: FONT.body,
          fontSize: 30,
          letterSpacing: "0.06em",
          color: T.bad,
          opacity: attack,
        }}
      >
        ATTACK
      </div>
      {BANDS.map((b) => {
        const a = interpolate(frame, [b.at + 8, b.at + 26], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: ease,
        });
        return (
          <div
            key={b.id}
            style={{
              position: "absolute",
              left: b.labelX - 300,
              top: 512,
              width: 600,
              textAlign: "center",
              fontFamily: FONT.body,
              fontSize: 30,
              letterSpacing: "0.06em",
              color: b.color,
              opacity: a,
            }}
          >
            {b.label}
          </div>
        );
      })}

    </Frame>
  );
};
