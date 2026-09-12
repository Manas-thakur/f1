import { interpolate, useCurrentFrame } from "remotion";
import { ground } from "../three/camera";
import type { Camera, Vec3 } from "../three/camera";
import { GroundPolygon } from "../three/Ground";
import { FONT, PALETTE, VIDEO } from "../theme";

const CAMERA: Camera = {
  eye: [1, 5.45894, 0],
  target: [0, 0, 0],
  up: [0, 0, 1],
  fov: 1.3722,
  width: VIDEO.width,
  height: VIDEO.height,
};

const APEX_X = 0.99355;
const UPSTREAM_SLOPE = 0.3455;
const DOWNSTREAM_SLOPE = 0.43342;
const UPSTREAM_END = 7.2;

const BAND_TOP = 295;
const BAND_BOTTOM = 778;

type Band = {
  readonly id: string;
  readonly label: string;
  readonly from: number;
  readonly to: number;
  readonly labelX: number;
  readonly edge: string;
  readonly rgb: string;
  readonly appear: number;
};

const BANDS: readonly Band[] = [
  {
    id: "delay",
    label: "PREPARE",
    from: APEX_X,
    to: -2.21965,
    labelX: 1081,
    edge: PALETTE.delay,
    rgb: "240,198,90",
    appear: 16,
  },
  {
    id: "defend",
    label: "DEFEND",
    from: -2.21965,
    to: -5.282,
    labelX: 1343,
    edge: PALETTE.defend,
    rgb: "141,204,242",
    appear: 24,
  },
  {
    id: "recharge",
    label: "RECOVER",
    from: -5.282,
    to: -9.53467,
    labelX: 1624,
    edge: PALETTE.recharge,
    rgb: "138,205,158",
    appear: 32,
  },
];

const halfWidth = (x: number, slope: number): number => Math.abs(x - APEX_X) * slope;

const wedge = (from: number, to: number, slope: number): readonly Vec3[] => {
  const a = halfWidth(from, slope);
  const b = halfWidth(to, slope);
  return [ground(from, -a), ground(to, -b), ground(to, b), ground(from, a)];
};

export const Corridor = () => {
  const frame = useCurrentFrame();

  const attackIn = interpolate(frame, [2, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rails = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const collapse = interpolate(frame, [202, 214], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <>
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <clipPath id="corridor-band">
            <rect x={0} y={BAND_TOP} width={VIDEO.width} height={BAND_BOTTOM - BAND_TOP} />
          </clipPath>
          <linearGradient id="grad-attack" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="rgba(255,133,138,0.72)" />
            <stop offset="0.62" stopColor="rgba(255,133,138,0.34)" />
            <stop offset="1" stopColor="rgba(255,133,138,0.04)" />
          </linearGradient>
          <filter id="wedge-glow" x="-25%" y="-40%" width="150%" height="180%">
            <feGaussianBlur stdDeviation="9" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {BANDS.map((b) => (
            <linearGradient key={b.id} id={`grad-${b.id}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor={`rgba(${b.rgb},0.07)`} />
              <stop offset="1" stopColor={`rgba(${b.rgb},0.6)`} />
            </linearGradient>
          ))}
        </defs>

        <g clipPath="url(#corridor-band)">
          <g opacity={attackIn}>
            <GroundPolygon
              camera={CAMERA}
              points={wedge(APEX_X, UPSTREAM_END, UPSTREAM_SLOPE)}
              fill="url(#grad-attack)"
            />
            <g filter="url(#wedge-glow)">
              <GroundPolygon
                camera={CAMERA}
                points={wedge(APEX_X, UPSTREAM_END, UPSTREAM_SLOPE)}
                stroke="rgba(255,133,138,0.95)"
                strokeWidth={2.4}
              />
            </g>
          </g>

          {BANDS.map((b) => {
            const alive = interpolate(frame, [b.appear, b.appear + 12], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const w = halfWidth(b.to, DOWNSTREAM_SLOPE);
            return (
              <g key={b.id} opacity={alive * (1 - collapse)}>
                <GroundPolygon
                  camera={CAMERA}
                  points={wedge(b.from, b.to, DOWNSTREAM_SLOPE)}
                  fill={`url(#grad-${b.id})`}
                />
                <g filter="url(#wedge-glow)">
                  <GroundPolygon
                    camera={CAMERA}
                    points={[ground(b.to, -w), ground(b.to, w)]}
                    stroke={b.edge}
                    strokeWidth={2.6}
                  />
                </g>
              </g>
            );
          })}
        </g>

        <line
          x1={0}
          y1={BAND_TOP}
          x2={VIDEO.width * rails}
          y2={BAND_TOP}
          stroke="rgba(175,185,194,0.8)"
          strokeWidth={2}
        />
        <line
          x1={0}
          y1={BAND_BOTTOM}
          x2={VIDEO.width * rails}
          y2={BAND_BOTTOM}
          stroke="rgba(175,185,194,0.8)"
          strokeWidth={2}
        />
      </svg>

      <div
        style={{
          position: "absolute",
          left: 319 - 300,
          top: 497,
          width: 600,
          textAlign: "center",
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 50,
          letterSpacing: "0.025em",
          color: PALETTE.paper,
          opacity: attackIn,
        }}
      >
        ATTACK
      </div>

      {BANDS.map((b) => {
        const alive = interpolate(frame, [b.appear + 6, b.appear + 18], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={b.id}
            style={{
              position: "absolute",
              left: b.labelX - 300,
              top: 497,
              width: 600,
              textAlign: "center",
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 50,
              letterSpacing: "0.025em",
              color: PALETTE.paper,
              opacity: alive * (1 - collapse),
            }}
          >
            {b.label}
          </div>
        );
      })}

      <div
        style={{
          position: "absolute",
          left: 143,
          top: 780,
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 20,
          letterSpacing: "0.055em",
          color: "rgba(255,255,255,0.88)",
          opacity: rails,
        }}
      >
        TELEMETRY → ESTIMATE → RULE CHECK → SCENARIOS → RECOMMENDATION
      </div>
    </>
  );
};
