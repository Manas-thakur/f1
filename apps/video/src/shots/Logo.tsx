import { interpolate, useCurrentFrame } from "remotion";
import { FONT, PALETTE, VIDEO } from "../theme";

export const Logo = () => {
  const frame = useCurrentFrame();

  const spark = interpolate(frame, [0, 10, 20], [0, 1, 0.2], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const sweep = interpolate(frame, [6, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const word = interpolate(frame, [18, 38], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tagline = interpolate(frame, [32, 48], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0, background: PALETTE.ink }}>
      <div
        style={{
          position: "absolute",
          left: VIDEO.width / 2,
          top: 496,
          transform: "translate(-50%, -50%)",
          width: 760 * sweep,
          height: 3,
          background: `linear-gradient(90deg, rgba(255,51,39,0) 0%, ${PALETTE.attack} 50%, rgba(255,51,39,0) 100%)`,
          filter: "blur(1.5px)",
          opacity: 0.9 - 0.6 * word,
          boxShadow: `0 0 ${40 * spark}px ${20 * spark}px rgba(255,51,39,0.45)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 458,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: FONT.caption,
            fontWeight: 300,
            fontSize: 52,
            letterSpacing: "0.22em",
            color: PALETTE.paper,
            opacity: word,
            transform: `scale(${0.98 + 0.02 * word})`,
          }}
        >
          APEXLEDGER
        </div>
        <div
          style={{
            marginTop: 12,
            marginLeft: 152,
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 34,
            letterSpacing: "0.08em",
            color: "rgba(255,255,255,0.92)",
            opacity: tagline,
          }}
        >
          PRICE THE PASS.
        </div>
      </div>
    </div>
  );
};
