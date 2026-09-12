import { interpolate, useCurrentFrame } from "remotion";
import { DecisionCard } from "../ui/DecisionCard";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const Decision = () => {
  const frame = useCurrentFrame();
  const card = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const body = interpolate(frame, [8, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const options = interpolate(frame, [16, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const abstain = interpolate(frame, [26, 42], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [128, 142], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <Scrim left={800} top={216} width={1080} height={470} strength={0.2} blur={22} opacity={card} />

      <DecisionCard
        reveal={card}
        bodyReveal={body}
        optionsReveal={options}
        highlight="DELAY"
        style={{
          left: 868,
          top: 266,
          transform: `perspective(2000px) rotateY(-6deg) translateX(${(1 - card) * 34}px)`,
          transformOrigin: "left center",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 1534,
          top: 330,
          background: "rgba(14,17,20,0.86)",
          backdropFilter: "blur(10px)",
          border: `1px solid ${PALETTE.panelEdge}`,
          borderRadius: 14,
          padding: "12px 18px 16px",
          opacity: abstain,
          transform: `perspective(2000px) rotateY(-6deg) translateX(${(1 - abstain) * 26}px)`,
          transformOrigin: "left center",
        }}
      >
        {["ABSTAIN", "IF FUTURES", "DISAGREE"].map((line) => (
          <div
            key={line}
            style={{
              fontFamily: FONT.display,
              fontWeight: 700,
              fontSize: 46,
              lineHeight: "51px",
              color: PALETTE.paper,
              letterSpacing: "0.005em",
            }}
          >
            {line}
          </div>
        ))}
      </div>

    </div>
  );
};
