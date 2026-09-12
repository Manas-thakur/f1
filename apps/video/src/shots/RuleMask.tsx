import { interpolate, useCurrentFrame } from "remotion";
import { planeCorners } from "../three/camera";
import type { Camera } from "../three/camera";
import { GroundEllipse, GroundPlate } from "../three/Ground";
import { Chip } from "../ui/Chip";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE, VIDEO } from "../theme";

const BILLBOARD: Camera = {
  eye: [0, 0, 26],
  target: [0, 0, 0],
  up: [0, 1, 0],
  fov: 0.6,
  width: VIDEO.width,
  height: VIDEO.height,
};

const GROUND: Camera = {
  eye: [0, 1.7, 0],
  target: [0, 0, -12],
  up: [0, 1, 0],
  fov: 0.82,
  width: VIDEO.width,
  height: VIDEO.height,
};

const CLAUSES: readonly string[] = [
  "SEASON REVISION → EVENT PACK → TIMESTAMPED RACE-CONTROL STATE",
  "ELIGIBILITY OBSERVED AT DETECTION · ACTIVATED AT THE CROSSING",
  "MISSING INFORMATION RESOLVES TO UNKNOWN, NEVER TO A DEFAULT",
];

const BOX = planeCorners([2.226, 4.185, 0], 7.48, 1.772, -0.055, 0);

const skew = (yaw: number, pitch: number): string =>
  `perspective(2600px) rotateY(${yaw}deg) rotateX(${pitch}deg)`;

export const RuleMask = () => {
  const frame = useCurrentFrame();

  const fields = interpolate(frame, [4, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const hud = interpolate(frame, [8, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const box = interpolate(frame, [24, 46], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stamp = interpolate(frame, [44, 62], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [124, 134], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const flicker = 0.92 + 0.08 * Math.sin(frame / 3.1);

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <Scrim left={0} top={606} width={1920} height={330} strength={0.4} blur={20} shape="linear" opacity={hud} />
      <Scrim left={540} top={96} width={1160} height={350} strength={0.34} blur={18} opacity={hud} />
      <Scrim left={1200} top={886} width={720} height={112} strength={0.4} blur={13} opacity={stamp} />

      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <radialGradient id="mask-gold">
            <stop offset="0.05" stopColor="rgba(236,164,36,0.52)" />
            <stop offset="0.62" stopColor="rgba(236,164,36,0.17)" />
            <stop offset="1" stopColor="rgba(236,164,36,0)" />
          </radialGradient>
          <radialGradient id="mask-teal">
            <stop offset="0.05" stopColor="rgba(60,205,220,0.54)" />
            <stop offset="0.62" stopColor="rgba(60,205,220,0.18)" />
            <stop offset="1" stopColor="rgba(60,205,220,0)" />
          </radialGradient>
        </defs>

        <g opacity={fields}>
          <GroundEllipse
            camera={GROUND}
            center={[-2.02, -7.35]}
            radius={[1.86 * fields, 2.05 * fields]}
            fill="url(#mask-gold)"
          />
          <GroundEllipse
            camera={GROUND}
            center={[-2.02, -7.35]}
            radius={[1.86 * fields, 2.05 * fields]}
            stroke="rgba(236,164,36,0.3)"
            strokeWidth={2}
          />
          <GroundEllipse
            camera={GROUND}
            center={[2.24, -7.35]}
            radius={[1.66 * fields, 1.95 * fields]}
            fill="url(#mask-teal)"
          />
          <GroundEllipse
            camera={GROUND}
            center={[2.24, -7.35]}
            radius={[1.66 * fields, 1.95 * fields]}
            stroke="rgba(60,205,220,0.34)"
            strokeWidth={2}
          />
        </g>
      </svg>

      <div style={{ position: "absolute", inset: 0, opacity: box }}>
        <GroundPlate camera={BILLBOARD} corners={BOX} width={1005} height={238}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              border: `3px solid rgba(255,58,45,${0.98 * flicker})`,
              boxShadow: `0 0 30px rgba(255,45,34,${0.8 * flicker}), 0 0 96px rgba(255,45,34,0.3), inset 0 0 44px rgba(255,45,34,0.14)`,
            }}
          />
          <div style={{ position: "absolute", left: 0, right: 0, top: -19, textAlign: "center" }}>
            <span
              style={{
                background: "rgba(5,7,9,0.96)",
                padding: "0 22px",
                fontFamily: FONT.display,
                fontWeight: 600,
                fontSize: 31,
                letterSpacing: "0.1em",
                color: PALETTE.paper,
              }}
            >
              RULE PACK
            </span>
          </div>
          <div style={{ padding: "46px 48px 0" }}>
            {CLAUSES.map((clause, i) => (
              <div
                key={clause}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 11,
                  marginBottom: 9,
                  opacity: interpolate(frame, [32 + i * 5, 46 + i * 5], [0, 1], {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  }),
                }}
              >
                <span style={{ width: 3, height: 15, background: PALETTE.attack }} />
                <span
                  style={{
                    fontFamily: FONT.display,
                    fontWeight: 500,
                    fontSize: 17,
                    letterSpacing: "0.04em",
                    color: "rgba(255,170,162,0.94)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {clause}
                </span>
              </div>
            ))}
          </div>
        </GroundPlate>
      </div>

      <div style={{ position: "absolute", inset: 0, opacity: hud }}>
        <div
          style={{
            position: "absolute",
            left: 56,
            top: 636,
            transform: skew(-11, 4),
            transformOrigin: "left center",
          }}
        >
          <div
            style={{
              fontFamily: FONT.display,
              fontWeight: 500,
              fontSize: 23,
              letterSpacing: "0.02em",
              color: PALETTE.paper,
              whiteSpace: "nowrap",
            }}
          >
            BATTERY 4.1 MJ
          </div>
          <div style={{ marginTop: 3 }}>
            <Chip tone="amber" fontSize={17}>
              MEASURED
            </Chip>
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            left: 216,
            top: 632,
            transform: skew(-13, 5),
            transformOrigin: "left center",
          }}
        >
          <div
            style={{
              fontFamily: FONT.display,
              fontWeight: 500,
              fontSize: 42,
              letterSpacing: "0.015em",
              color: PALETTE.paper,
              whiteSpace: "nowrap",
            }}
          >
            GAP / CLOSING SPEED / TRACK SEGMENT
          </div>
        </div>

        <div style={{ position: "absolute", left: 224, top: 798, transform: skew(-13, 5) }}>
          <Chip tone="dark" fontSize={16}>
            OBSERVED
          </Chip>
        </div>

        <div
          style={{
            position: "absolute",
            left: 620,
            top: 752,
            transform: skew(-13, 5),
            transformOrigin: "left center",
          }}
        >
          <div
            style={{
              fontFamily: FONT.display,
              fontWeight: 500,
              fontSize: 35,
              letterSpacing: "0.015em",
              color: "rgba(255,255,255,0.95)",
              whiteSpace: "nowrap",
            }}
          >
            RIVAL BELIEF: CONSERVE / NORMAL / ATTACK / DEFEND
          </div>
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          right: 126,
          top: 928,
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 31,
          letterSpacing: "0.03em",
          color: "rgba(255,255,255,0.96)",
          opacity: stamp,
        }}
      >
        OBSERVED. INFERRED. NEVER INVENTED.
      </div>
    </div>
  );
};
