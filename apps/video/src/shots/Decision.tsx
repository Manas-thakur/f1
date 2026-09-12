import { interpolate, useCurrentFrame } from "remotion";
import { DecisionCard } from "../ui/DecisionCard";
import { FONT, PALETTE } from "../theme";

export const Decision = () => {
  const frame = useCurrentFrame();
  const ghost = interpolate(frame, [0, 9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const ghostOut = interpolate(frame, [12, 22], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const card = interpolate(frame, [14, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const body = interpolate(frame, [22, 36], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const options = interpolate(frame, [30, 44], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const abstain = interpolate(frame, [40, 56], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [118, 128], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      {ghostOut > 0 ? (
        <div
          style={{
            position: "absolute",
            left: 820,
            top: 268,
            width: 900,
            height: 300,
            background: "rgba(150,158,163,0.30)",
            borderRadius: 16,
            opacity: ghost * ghostOut,
            transform: `scale(${0.9 + 0.1 * ghost})`,
            transformOrigin: "left top",
          }}
        >
          <span
            style={{
              position: "absolute",
              left: 30,
              top: 6,
              fontFamily: FONT.display,
              fontWeight: 700,
              fontSize: 96,
              color: PALETTE.paper,
            }}
          >
            WAIT
          </span>
        </div>
      ) : null}

      <DecisionCard
        reveal={card}
        bodyReveal={body}
        optionsReveal={options}
        highlight="DELAY"
        style={{
          left: 855,
          top: 272,
          transform: `perspective(1800px) rotateY(-7deg) rotateX(1.5deg) translateX(${(1 - card) * 40}px)`,
          transformOrigin: "left center",
        }}
      />

      <div
        style={{
          position: "absolute",
          left: 1502,
          top: 296,
          background: PALETTE.panel,
          border: `1px solid ${PALETTE.panelEdge}`,
          borderRadius: 16,
          padding: "14px 20px 18px",
          opacity: abstain,
          transform: `perspective(1800px) rotateY(-7deg) translateX(${(1 - abstain) * 30}px)`,
          transformOrigin: "left center",
        }}
      >
        {["ABSTAIN", "IF FUTURES", "DISAGREE"].map((line) => (
          <div
            key={line}
            style={{
              fontFamily: FONT.display,
              fontWeight: 700,
              fontSize: 54,
              lineHeight: "56px",
              color: PALETTE.paper,
              letterSpacing: "0.01em",
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
};
