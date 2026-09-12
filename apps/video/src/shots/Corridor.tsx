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
    edge: "#e6eef1",
    rgb: "230,238,241",
    appear: 16,
  },
  {
    id: "defend",
    label: "DEFEND",
    from: -2.21965,
    to: -5.282,
    labelX: 1343,
    edge: PALETTE.defend,
    rgb: "66,207,219",
    appear: 24,
  },
  {
    id: "recharge",
    label: "RECOVER",
    from: -5.282,
    to: -9.53467,
    labelX: 1624,
    edge: PALETTE.recharge,
    rgb: "233,169,44",
    appear: 32,
  },
];

const halfWidth = (x: number, slope: number): number => Math.abs(x - APEX_X) * slope;

const wedge = (from: number, to: number, slope: number): readonly Vec3[] => {
  const a = halfWidth(from, slope);
  const b = halfWidth(to, slope);
  return [ground(from, -a), ground(to, -b), ground(to, b), ground(from, a)];
};

const TICKS: readonly (readonly [number, number, number])[] = [
  [118, 392, 1],
  [118, 640, -1],
  [520, 400, 1],
  [520, 660, -1],
  [949, 372, 1],
  [1292, 380, 1],
  [1292, 648, -1],
  [1596, 392, 1],
  [1596, 636, -1],
];

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
  const sweep = interpolate(frame, [188, 202], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const collapse = interpolate(frame, [202, 214], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const chipIn = interpolate(frame, [206, 218], [0, 1], {
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
            <stop offset="0" stopColor="rgba(216,40,28,0.86)" />
            <stop offset="0.62" stopColor="rgba(214,44,32,0.44)" />
            <stop offset="1" stopColor="rgba(214,44,32,0.05)" />
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
                stroke="rgba(255,74,58,0.95)"
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

          <g opacity={rails * 0.85}>
            {TICKS.map(([x, y, dir]) => (
              <path
                key={`${x}-${y}`}
                d={`M ${x} ${y + dir * 34} L ${x} ${y} L ${x + 46} ${y}`}
                stroke={PALETTE.amber}
                strokeWidth={2}
                fill="none"
              />
            ))}
          </g>
        </g>

        <line
          x1={0}
          y1={BAND_TOP}
          x2={VIDEO.width * rails}
          y2={BAND_TOP}
          stroke="rgba(222,240,233,0.92)"
          strokeWidth={2}
        />
        <line
          x1={0}
          y1={BAND_BOTTOM}
          x2={VIDEO.width * rails}
          y2={BAND_BOTTOM}
          stroke="rgba(222,240,233,0.92)"
          strokeWidth={2}
        />

        {sweep > 0 ? (
          <rect
            x={1180}
            y={BAND_TOP - 214}
            width={634}
            height={BAND_BOTTOM - BAND_TOP + 222}
            fill="rgba(226,60,45,0.12)"
            stroke={PALETTE.attack}
            strokeWidth={3}
            opacity={sweep * (1 - chipIn)}
          />
        ) : null}
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

      {chipIn > 0 ? (
        <div
          style={{
            position: "absolute",
            left: 1418,
            top: 78,
            opacity: chipIn,
            transform: `translate(${(1 - chipIn) * -120}px, ${(1 - chipIn) * 340}px) scale(${
              0.7 + 0.3 * chipIn
            })`,
            transformOrigin: "center",
            textAlign: "center",
          }}
        >
          <div style={{ display: "flex", gap: 2 }}>
            {BANDS.map((b) => (
              <span
                key={b.id}
                style={{
                  fontFamily: FONT.display,
                  fontWeight: 600,
                  fontSize: 27,
                  letterSpacing: "0.03em",
                  padding: "4px 12px 5px",
                  color: "#0d1114",
                  background: b.edge,
                }}
              >
                {b.label}
              </span>
            ))}
          </div>
          <div
            style={{
              marginTop: 7,
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 23,
              letterSpacing: "0.06em",
              color: PALETTE.paper,
            }}
          >
            RE-CHECKED EACH TICK
          </div>
        </div>
      ) : null}

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

      <div
        style={{
          position: "absolute",
          left: 1838,
          top: 540,
          transform: "translate(-50%, -50%) rotate(-90deg)",
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 20,
          letterSpacing: "0.08em",
          color: "rgba(255,255,255,0.82)",
          whiteSpace: "nowrap",
          opacity: rails,
        }}
      >
        EVALUATION HORIZON
      </div>
    </>
  );
};
