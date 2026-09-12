import { interpolate, useCurrentFrame } from "remotion";
import type { Camera } from "../three/camera";
import { GroundEllipse } from "../three/Ground";
import { Chip } from "../ui/Chip";
import { FONT, PALETTE, VIDEO } from "../theme";

const CAMERA: Camera = {
  eye: [0, 7.4, -17],
  target: [1.5, 0, 6],
  up: [0, 1, 0],
  fov: 0.72,
  width: VIDEO.width,
  height: VIDEO.height,
};

export const EnergyDebt = () => {
  const frame = useCurrentFrame();
  const field = interpolate(frame, [8, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tag = interpolate(frame, [58, 74], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [80, 90], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pulse = 0.82 + 0.18 * Math.sin(frame / 7);

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <radialGradient id="debt-field">
            <stop offset="0.1" stopColor="rgba(66,207,219,0.30)" />
            <stop offset="0.72" stopColor="rgba(66,207,219,0.12)" />
            <stop offset="1" stopColor="rgba(66,207,219,0)" />
          </radialGradient>
        </defs>
        <g opacity={field}>
          <GroundEllipse
            camera={CAMERA}
            center={[1.2, 5.5]}
            radius={[7.4 * field, 6.2 * field]}
            fill="url(#debt-field)"
          />
          <GroundEllipse
            camera={CAMERA}
            center={[1.2, 5.5]}
            radius={[7.4 * field, 6.2 * field]}
            stroke="rgba(66,207,219,0.55)"
            strokeWidth={2}
            opacity={pulse}
          />
          <GroundEllipse
            camera={CAMERA}
            center={[1.2, 5.5]}
            radius={[4.3 * field, 3.5 * field]}
            stroke="rgba(66,207,219,0.28)"
            strokeWidth={1.6}
          />
        </g>
      </svg>

      <div
        style={{
          position: "absolute",
          left: 1300,
          top: 812,
          opacity: tag,
          transform: `translateX(${(1 - tag) * 26}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 25,
            letterSpacing: "0.06em",
            color: PALETTE.paper,
            marginBottom: 5,
          }}
        >
          ENERGY DEBT →
        </div>
        <Chip tone="amber" fontSize={23}>
          NEXT WINDOW
        </Chip>
      </div>
    </div>
  );
};
