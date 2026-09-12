import { Easing, interpolate, useCurrentFrame } from "remotion";
import { EASE_OUT, FONT, T } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

export const Open = () => {
  const frame = useCurrentFrame();
  const mark = interpolate(frame, [4, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const line = interpolate(frame, [16, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const rule = interpolate(frame, [12, 36], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  return (
    <div style={{ position: "absolute", left: 96, top: 380 }}>
      <div
        style={{
          fontFamily: FONT.body,
          fontSize: 76,
          letterSpacing: "0.14em",
          color: T.ink,
          opacity: mark,
          transform: `translateY(${(1 - mark) * 14}px)`,
        }}
      >
        AFTERLAP
      </div>
      <div
        style={{
          width: 1160 * rule,
          height: 1,
          background: T.rule,
          margin: "24px 0",
        }}
      />
      <div
        style={{
          fontFamily: FONT.body,
          fontSize: 34,
          lineHeight: "46px",
          color: T.muted,
          maxWidth: 1160,
          opacity: line,
          transform: `translateY(${(1 - line) * 10}px)`,
        }}
      >
        Energy spent overtaking is energy you cannot spend defending.
      </div>
    </div>
  );
};
