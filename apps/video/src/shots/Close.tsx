import { Easing, interpolate, useCurrentFrame } from "remotion";
import { EASE_OUT, FONT, T } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

export const Close = () => {
  const frame = useCurrentFrame();
  const a = interpolate(frame, [2, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const b = interpolate(frame, [14, 36], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  return (
    <div style={{ position: "absolute", left: 96, top: 440 }}>
      <div
        style={{
          fontFamily: FONT.body,
          fontSize: 76,
          letterSpacing: "0.14em",
          color: T.ink,
          opacity: a,
        }}
      >
        AFTERLAP
      </div>
      <div style={{ width: 1160 * b, height: 1, background: T.rule, margin: "24px 0" }} />
      <div style={{ fontFamily: FONT.body, fontSize: 32, color: T.muted, opacity: b }}>
        Decision support for electrical energy and racing battles.
      </div>
    </div>
  );
};
