import { interpolate, useCurrentFrame } from "remotion";
import { FONT, PALETTE } from "../theme";

export const Verdict = () => {
  const frame = useCurrentFrame();

  const attackIn = interpolate(frame, [4, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const attackOut = interpolate(frame, [44, 52], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const strobe = frame > 20 && frame < 46 ? (Math.floor(frame / 2) % 2 === 0 ? 1 : 0.55) : 1;

  const durableIn = interpolate(frame, [62, 74], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const durableOut = interpolate(frame, [98, 107], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div
        style={{
          position: "absolute",
          left: 648,
          top: 62,
          display: "flex",
          alignItems: "center",
          gap: 14,
          background: "rgba(22,25,28,0.80)",
          borderRadius: 10,
          padding: "8px 20px 10px",
          opacity: attackIn * attackOut * strobe,
          transform: `scale(${0.9 + 0.1 * attackIn})`,
          transformOrigin: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONT.display,
            fontWeight: 700,
            fontSize: 58,
            letterSpacing: "0.02em",
            color: PALETTE.paper,
          }}
        >
          ATTACK
        </span>
        <span style={{ fontSize: 46, color: PALETTE.green, lineHeight: 1 }}>✓</span>
      </div>

      <div
        style={{
          position: "absolute",
          left: 1268,
          top: 640,
          background: "rgba(33,163,49,0.94)",
          borderRadius: 8,
          padding: "8px 20px 10px",
          opacity: durableIn * durableOut,
          transform: `translateY(${(1 - durableIn) * 14}px)`,
          boxShadow: "0 0 40px rgba(84,223,89,0.32)",
        }}
      >
        <span
          style={{
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 38,
            letterSpacing: "0.035em",
            color: PALETTE.paper,
          }}
        >
          DURABLE POSITION
        </span>
      </div>
    </div>
  );
};
