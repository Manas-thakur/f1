import { Easing, interpolate, useCurrentFrame } from "remotion";
import { Frame } from "../ui/Frame";
import { EASE_OUT, FONT, T } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

const CLAUSES: readonly (readonly [string, string, string])[] = [
  ["Season revision", "2026.08", "pass"],
  ["Event pack", "r3 · hash 4f21ac", "pass"],
  ["Race-control state", "green · lap 34", "pass"],
  ["Deployment window", "2 activations / sector", "pass"],
  ["Rival lateral position", "not supplied", "unknown"],
];

const TONE = { pass: T.good, unknown: T.muted } as const;

export const RuleCheck = () => {
  const frame = useCurrentFrame();
  return (
    <Frame step="02" title="Check against the rule pack">
      <div style={{ position: "absolute", left: 96, top: 232, width: 1360 }}>
        {CLAUSES.map(([label, value, status], i) => {
          const a = interpolate(frame, [6 + i * 8, 26 + i * 8], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: ease,
          });
          return (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 32,
                padding: "20px 0",
                borderBottom: `1px solid ${T.rule}`,
                opacity: a,
                transform: `translateY(${(1 - a) * 8}px)`,
              }}
            >
              <span style={{ fontFamily: FONT.body, fontSize: 26, color: T.ink, width: 460 }}>
                {label}
              </span>
              <span
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 24,
                  color: T.muted,
                  flex: 1,
                }}
              >
                {value}
              </span>
              <span
                style={{
                  fontFamily: FONT.body,
                  fontSize: 22,
                  color: TONE[status as keyof typeof TONE],
                }}
              >
                {status}
              </span>
            </div>
          );
        })}
        <div
          style={{
            marginTop: 40,
            fontFamily: FONT.body,
            fontSize: 26,
            color: T.muted,
            opacity: interpolate(frame, [52, 74], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: ease,
            }),
          }}
        >
          Missing information stays unknown. It never becomes a default.
        </div>
      </div>
    </Frame>
  );
};
