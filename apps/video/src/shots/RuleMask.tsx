import { interpolate, useCurrentFrame } from "remotion";
import type { Camera } from "../three/camera";
import { GroundEllipse, GroundPlate, WireBox } from "../three/Ground";
import { Chip } from "../ui/Chip";
import { FONT, PALETTE, VIDEO } from "../theme";

const CAMERA: Camera = {
  eye: [0, 6.2, -21],
  target: [0.4, 1.1, 8],
  up: [0, 1, 0],
  fov: 0.7,
  width: VIDEO.width,
  height: VIDEO.height,
};

const CLAUSES: readonly string[] = [
  "ANNEX 4 · DEPLOYMENT WINDOW LIMITED TO 2 ACTIVATIONS PER LAP SECTOR",
  "ART. 12.3 · OVERTAKE ASSIST DISABLED WITHIN 100 M OF A YELLOW SECTOR",
  "APP. 9B · HARVEST CREDIT MUST SETTLE BEFORE THE NEXT CONTROL LINE",
];

export const RuleMask = () => {
  const frame = useCurrentFrame();

  const fields = interpolate(frame, [10, 34], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const hud = interpolate(frame, [22, 44], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const box = interpolate(frame, [42, 66], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stamp = interpolate(frame, [62, 78], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [126, 136], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const boxTop = 3.35;
  const boxBottom = 1.62;
  const boxLeft = -4.1;
  const boxRight = 4.35;
  const boxZ = 9.2;

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <radialGradient id="mask-gold">
            <stop offset="0.1" stopColor="rgba(233,169,44,0.26)" />
            <stop offset="0.7" stopColor="rgba(233,169,44,0.1)" />
            <stop offset="1" stopColor="rgba(233,169,44,0)" />
          </radialGradient>
          <radialGradient id="mask-teal">
            <stop offset="0.1" stopColor="rgba(66,207,219,0.28)" />
            <stop offset="0.7" stopColor="rgba(66,207,219,0.11)" />
            <stop offset="1" stopColor="rgba(66,207,219,0)" />
          </radialGradient>
          <filter id="mask-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g opacity={fields}>
          <GroundEllipse
            camera={CAMERA}
            center={[-2.5, 6.6]}
            radius={[3.5 * fields, 2.5 * fields]}
            fill="url(#mask-gold)"
          />
          <GroundEllipse
            camera={CAMERA}
            center={[-2.5, 6.6]}
            radius={[3.5 * fields, 2.5 * fields]}
            stroke="rgba(233,169,44,0.5)"
            strokeWidth={1.8}
          />
          <GroundEllipse
            camera={CAMERA}
            center={[2.9, 6.2]}
            radius={[3.5 * fields, 2.5 * fields]}
            fill="url(#mask-teal)"
          />
          <GroundEllipse
            camera={CAMERA}
            center={[2.9, 6.2]}
            radius={[3.5 * fields, 2.5 * fields]}
            stroke="rgba(66,207,219,0.55)"
            strokeWidth={1.8}
          />
        </g>

        <g opacity={box} filter="url(#mask-glow)">
          <WireBox
            camera={CAMERA}
            min={[boxLeft, boxBottom, boxZ]}
            max={[boxRight, boxTop, boxZ + 0.02]}
            stroke={PALETTE.attack}
            strokeWidth={2.6}
          />
        </g>
      </svg>

      <div style={{ position: "absolute", inset: 0, opacity: box }}>
        <GroundPlate
          camera={CAMERA}
          corners={[
            [boxLeft, boxTop, boxZ],
            [boxRight, boxTop, boxZ],
            [boxRight, boxBottom, boxZ],
            [boxLeft, boxBottom, boxZ],
          ]}
          width={900}
          height={190}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: -17,
              textAlign: "center",
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 30,
              letterSpacing: "0.1em",
              color: PALETTE.paper,
            }}
          >
            <span style={{ background: "rgba(6,8,10,0.92)", padding: "0 16px" }}>RULE MASK</span>
          </div>
          <div style={{ padding: "44px 34px 0" }}>
            {CLAUSES.map((clause, i) => (
              <div
                key={clause}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginBottom: 9,
                  opacity: interpolate(frame, [50 + i * 5, 62 + i * 5], [0, 1], {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  }),
                }}
              >
                <span
                  style={{
                    width: 3,
                    height: 15,
                    background: PALETTE.attack,
                    display: "inline-block",
                  }}
                />
                <span
                  style={{
                    fontFamily: FONT.display,
                    fontWeight: 500,
                    fontSize: 15,
                    letterSpacing: "0.05em",
                    color: "rgba(255,190,184,0.92)",
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
        <GroundPlate
          camera={CAMERA}
          corners={[
            [-7.6, 0.02, 4.1],
            [7.6, 0.02, 4.1],
            [7.6, 0.02, 1.2],
            [-7.6, 0.02, 1.2],
          ]}
          width={1180}
          height={230}
        >
          <div style={{ position: "absolute", left: 0, top: 6 }}>
            <div
              style={{
                fontFamily: FONT.display,
                fontWeight: 500,
                fontSize: 26,
                letterSpacing: "0.04em",
                color: PALETTE.paper,
                whiteSpace: "nowrap",
              }}
            >
              ENERGY 2.4–3.0 MJ
            </div>
            <div style={{ marginTop: 4 }}>
              <Chip tone="amber" fontSize={19}>
                INFERRED RANGE
              </Chip>
            </div>
          </div>
          <div style={{ position: "absolute", left: 180, top: 74 }}>
            <div
              style={{
                fontFamily: FONT.display,
                fontWeight: 500,
                fontSize: 28,
                letterSpacing: "0.04em",
                color: PALETTE.paper,
                whiteSpace: "nowrap",
              }}
            >
              GAP / CLOSING SPEED / TRACK SEGMENT
            </div>
            <div style={{ marginTop: 4 }}>
              <Chip tone="dark" fontSize={18}>
                OBSERVED
              </Chip>
            </div>
          </div>
          <div style={{ position: "absolute", left: 400, top: 168 }}>
            <div
              style={{
                fontFamily: FONT.display,
                fontWeight: 500,
                fontSize: 26,
                letterSpacing: "0.04em",
                color: "rgba(255,255,255,0.92)",
                whiteSpace: "nowrap",
              }}
            >
              RIVAL: SAVE / NEUTRAL / DEFEND / COUNTERATTACK
            </div>
          </div>
        </GroundPlate>
      </div>

      <div
        style={{
          position: "absolute",
          right: 96,
          top: 928,
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 30,
          letterSpacing: "0.045em",
          color: PALETTE.paper,
          opacity: stamp,
        }}
      >
        OBSERVED. INFERRED. NEVER INVENTED.
      </div>
    </div>
  );
};
