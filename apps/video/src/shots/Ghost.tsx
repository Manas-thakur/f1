import { interpolate, useCurrentFrame } from "remotion";
import { DecisionCard } from "../ui/DecisionCard";
import { FONT, PALETTE } from "../theme";

export const Ghost = () => {
  const frame = useCurrentFrame();
  const card = interpolate(frame, [0, 10], [1, 0.16], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const plate = interpolate(frame, [4, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const plateOut = interpolate(frame, [48, 64], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <DecisionCard
        reveal={card}
        bodyReveal={card}
        optionsReveal={card}
        highlight="DELAY"
        style={{ left: 980, top: 250, transform: "perspective(1800px) rotateY(-9deg)" }}
      />
      <div
        style={{
          position: "absolute",
          left: 1258,
          top: 236,
          width: 560,
          height: 250,
          borderRadius: 14,
          background: "rgba(158,166,171,0.26)",
          opacity: plate * plateOut,
          transform: `perspective(1600px) rotateY(-12deg) scale(${0.94 + 0.06 * plate})`,
          transformOrigin: "left top",
        }}
      >
        <span
          style={{
            position: "absolute",
            left: 44,
            top: 2,
            fontFamily: FONT.display,
            fontWeight: 700,
            fontSize: 74,
            letterSpacing: "0.02em",
            color: PALETTE.paper,
            opacity: 0.94,
          }}
        >
          WAIT
        </span>
      </div>
    </div>
  );
};
