import { Easing, interpolate, useCurrentFrame } from "remotion";
import { Frame } from "../ui/Frame";
import { EASE_OUT, FONT, T } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

const FIELDS: readonly (readonly [string, string])[] = [
  ["trigger", "detection line · lap 34"],
  ["end condition", "counterattack checkpoint"],
  ["expiry", "2.0 s"],
  ["checked by", "independent plan checker"],
];

export const Recommend = () => {
  const frame = useCurrentFrame();
  const card = interpolate(frame, [4, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const note = interpolate(frame, [64, 86], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  return (
    <Frame step="04" title="Recommend, do not execute">
      <div
        style={{
          position: "absolute",
          left: 96,
          top: 240,
          width: 1160,
          background: T.surface,
          border: `1px solid ${T.rule}`,
          padding: 48,
          opacity: card,
          transform: `translateY(${(1 - card) * 12}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT.mono,
            fontSize: 20,
            letterSpacing: "0.08em",
            color: T.muted,
          }}
        >
          RECOMMENDATION · proposed
        </div>
        <div
          style={{
            fontFamily: FONT.body,
            fontSize: 72,
            color: T.accent,
            margin: "16px 0 8px",
          }}
        >
          Prepare attack
        </div>
        <div style={{ marginTop: 24 }}>
          {FIELDS.map(([k, v], i) => {
            const a = interpolate(frame, [20 + i * 7, 40 + i * 7], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: ease,
            });
            return (
              <div
                key={k}
                style={{
                  display: "flex",
                  gap: 32,
                  padding: "12px 0",
                  borderTop: `1px solid ${T.rule}`,
                  opacity: a,
                }}
              >
                <span style={{ fontFamily: FONT.body, fontSize: 22, color: T.muted, width: 280 }}>
                  {k}
                </span>
                <span style={{ fontFamily: FONT.mono, fontSize: 24, color: T.ink }}>{v}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 96,
          top: 848,
          fontFamily: FONT.body,
          fontSize: 30,
          color: T.ink,
          opacity: note,
        }}
      >
        The engineer selects. The driver executes. Selection is not execution.
      </div>
    </Frame>
  );
};
