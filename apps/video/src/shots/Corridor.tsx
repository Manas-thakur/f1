import { interpolate, useCurrentFrame } from "remotion";
import { basisOf, ground, project } from "../three/camera";
import type { Camera, Vec3 } from "../three/camera";
import { GroundPolygon } from "../three/Ground";
import { FONT, PALETTE, VIDEO } from "../theme";

const CAMERA: Camera = {
  eye: [128, 62, 0],
  target: [0, 0, 0],
  up: [0, 0, 1],
  fov: 0.62,
  width: VIDEO.width,
  height: VIDEO.height,
};

const BAND_TOP = 295;
const BAND_BOTTOM = 776;

const UPSTREAM_ANGLE = 0.3;
const DOWNSTREAM_ANGLE = 0.62;

type Band = {
  readonly id: string;
  readonly label: string;
  readonly from: number;
  readonly to: number;
  readonly edge: string;
  readonly fill: string;
  readonly appear: number;
};

const BANDS: readonly Band[] = [
  {
    id: "delay",
    label: "DELAY",
    from: 0,
    to: 26,
    edge: PALETTE.delay,
    fill: "232,240,243",
    appear: 12,
  },
  {
    id: "defend",
    label: "DEFEND",
    from: 26,
    to: 56,
    edge: PALETTE.defend,
    fill: "66,207,219",
    appear: 18,
  },
  {
    id: "recharge",
    label: "RECHARGE",
    from: 56,
    to: 104,
    edge: PALETTE.recharge,
    fill: "233,169,44",
    appear: 24,
  },
];

const wedge = (from: number, to: number, angle: number, sign: number): readonly Vec3[] => {
  const a = Math.max(from, 0.001);
  return [
    ground(sign * a, -a * angle),
    ground(sign * to, -to * angle),
    ground(sign * to, to * angle),
    ground(sign * a, a * angle),
  ];
};

export const Corridor = () => {
  const frame = useCurrentFrame();
  const basis = basisOf(CAMERA);
  const apex = project(basis, [0, 0, 0]);

  const sweep = interpolate(frame, [190, 214], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const collapse = interpolate(frame, [214, 232], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const labelFor = (band: Band): { x: number; y: number } => {
    const mid = (band.from + band.to) / 2;
    const p = project(basis, [mid, 0, 0]);
    return { x: p.x, y: p.y };
  };

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
          <linearGradient id="grad-attack" x1="1" y1="0" x2="0" y2="0">
            <stop offset="0" stopColor="rgba(255,51,39,0)" />
            <stop offset="0.55" stopColor="rgba(255,51,39,0.34)" />
            <stop offset="1" stopColor="rgba(255,51,39,0.62)" />
          </linearGradient>
          {BANDS.map((b) => (
            <linearGradient key={b.id} id={`grad-${b.id}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor={`rgba(${b.fill},0.06)`} />
              <stop offset="1" stopColor={`rgba(${b.fill},0.42)`} />
            </linearGradient>
          ))}
        </defs>

        <g clipPath="url(#corridor-band)">
          <GroundPolygon
            camera={CAMERA}
            points={wedge(0, 150, UPSTREAM_ANGLE, -1)}
            fill="url(#grad-attack)"
          />
          <GroundPolygon
            camera={CAMERA}
            points={wedge(0, 150, UPSTREAM_ANGLE, -1)}
            stroke={PALETTE.attack}
            strokeWidth={2.5}
          />

          {BANDS.map((b) => {
            const alive = interpolate(frame, [b.appear, b.appear + 10], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const gone = 1 - collapse;
            return (
              <g key={b.id} opacity={alive * gone}>
                <GroundPolygon
                  camera={CAMERA}
                  points={wedge(b.from, b.to, DOWNSTREAM_ANGLE, 1)}
                  fill={`url(#grad-${b.id})`}
                />
                <GroundPolygon
                  camera={CAMERA}
                  points={[
                    ground(b.to, -b.to * DOWNSTREAM_ANGLE),
                    ground(b.to, b.to * DOWNSTREAM_ANGLE),
                  ]}
                  stroke={b.edge}
                  strokeWidth={2.6}
                />
              </g>
            );
          })}
        </g>

        <line
          x1={0}
          y1={BAND_TOP}
          x2={VIDEO.width}
          y2={BAND_TOP}
          stroke="rgba(214,232,226,0.72)"
          strokeWidth={2}
        />
        <line
          x1={0}
          y1={BAND_BOTTOM}
          x2={VIDEO.width}
          y2={BAND_BOTTOM}
          stroke="rgba(214,232,226,0.72)"
          strokeWidth={2}
        />

        {sweep > 0 && collapse < 1 ? (
          <rect
            x={interpolate(sweep, [0, 1], [1180, 1180])}
            y={BAND_TOP - 210}
            width={640}
            height={BAND_BOTTOM - BAND_TOP + 220}
            fill="rgba(255,51,39,0.1)"
            stroke={PALETTE.attack}
            strokeWidth={3}
            opacity={sweep * (1 - collapse * 0.2)}
          />
        ) : null}
      </svg>

      <div
        style={{
          position: "absolute",
          left: apex.x - 900,
          top: apex.y - 26,
          width: 760,
          textAlign: "center",
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 56,
          letterSpacing: "0.03em",
          color: PALETTE.paper,
        }}
      >
        ATTACK NOW
      </div>

      {BANDS.map((b) => {
        const pos = labelFor(b);
        const alive = interpolate(frame, [b.appear + 4, b.appear + 14], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={b.id}
            style={{
              position: "absolute",
              left: pos.x - 200,
              top: pos.y - 26,
              width: 400,
              textAlign: "center",
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 56,
              letterSpacing: "0.03em",
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
          left: 140,
          top: BAND_BOTTOM + 6,
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 21,
          letterSpacing: "0.07em",
          color: "rgba(255,255,255,0.86)",
        }}
      >
        TELEMETRY → BELIEF → RULE MASK → COUNTERFACTUALS → DECISION
      </div>

      <div
        style={{
          position: "absolute",
          left: 1836,
          top: 540,
          transform: "translate(-50%, -50%) rotate(-90deg)",
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 21,
          letterSpacing: "0.09em",
          color: "rgba(255,255,255,0.8)",
          whiteSpace: "nowrap",
        }}
      >
        LAP 2–3 ERS
      </div>
    </>
  );
};
