import { interpolate, useCurrentFrame } from "remotion";
import { FONT, PALETTE } from "../theme";

export const DurableChip = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [42, 50], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: 1132,
        top: 264,
        background: "rgba(35,168,52,0.97)",
        borderRadius: 6,
        padding: "6px 16px 8px",
        opacity: rise * out,
        transform: `translateY(${(1 - rise) * 12}px)`,
        boxShadow: "0 0 38px rgba(84,223,89,0.34)",
      }}
    >
      <span
        style={{
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 34,
          letterSpacing: "0.03em",
          color: PALETTE.paper,
        }}
      >
        DURABLE POSITION
      </span>
    </div>
  );
};
