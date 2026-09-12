import { interpolate, useCurrentFrame } from "remotion";
import { FONT, PALETTE, VIDEO } from "../theme";

export const Logo = () => {
  const frame = useCurrentFrame();

  const spark = interpolate(frame, [4, 10, 20], [0, 1, 0.35], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const sweep = interpolate(frame, [7, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const word = interpolate(frame, [5, 42], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tagline = interpolate(frame, [30, 44], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0, background: "transparent" }}>
      <div
        style={{
          position: "absolute",
          left: VIDEO.width / 2,
          top: 506,
          transform: "translate(-50%, -50%)",
          width: 880 * sweep * sweep,
          height: 3,
          background: `linear-gradient(90deg, rgba(255,51,39,0) 0%, ${PALETTE.attack} 50%, rgba(255,51,39,0) 100%)`,
          filter: "blur(1.6px)",
          opacity: 0.95 - 0.7 * word,
          boxShadow: `0 0 ${52 * spark}px ${26 * spark}px rgba(255,51,39,0.4)`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 454, textAlign: "center" }}>
        <div
          style={{
            fontFamily: FONT.caption,
            fontWeight: 300,
            fontSize: 74,
            letterSpacing: "0.105em",
            color: PALETTE.paper,
            opacity: word,
            WebkitMaskImage: `linear-gradient(90deg, #000 0%, #000 ${word * 100}%, rgba(0,0,0,0.06) ${
              word * 100 + 6
            }%, rgba(0,0,0,0) 100%)`,
            maskImage: `linear-gradient(90deg, #000 0%, #000 ${word * 100}%, rgba(0,0,0,0.06) ${
              word * 100 + 6
            }%, rgba(0,0,0,0) 100%)`,
          }}
        >
          AFTERLAP
        </div>
        <div
          style={{
            marginTop: 4,
            marginLeft: 234,
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 50,
            letterSpacing: "0.03em",
            color: "rgba(255,255,255,0.94)",
            opacity: tagline,
          }}
        >
          PRICE THE PASS.
        </div>
      </div>
    </div>
  );
};
