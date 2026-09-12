import { interpolate, useCurrentFrame } from "remotion";
import { DecisionCard } from "../ui/DecisionCard";
import { Scrim } from "../ui/Scrim";

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
  const out = interpolate(frame, [128, 137], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const reframed = frame >= 121;
  const shift = reframed ? "translate(186px, -206px)" : "translate(0px, 0px)";

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <Scrim left={reframed ? 1074 : 800} top={reframed ? 4 : 216} width={1080} height={470} strength={0.2} blur={22} opacity={card} />

      <DecisionCard
        reveal={card}
        bodyReveal={body}
        style={{
          left: 868,
          top: 266,
          transform: `${shift} perspective(2000px) rotateY(-6deg) translateX(${(1 - card) * 34}px)`,
          transformOrigin: "left center",
        }}
      />

    </div>
  );
};
