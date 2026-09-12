import { interpolate, useCurrentFrame } from "remotion";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

const LINES: readonly (readonly { text: string; accent: boolean }[])[] = [
  [{ text: "THE PASS", accent: false }],
  [
    { text: "IS ", accent: false },
    { text: "NOT", accent: true },
  ],
  [{ text: "FREE.", accent: false }],
];

export const Title = () => {
  const frame = useCurrentFrame();
  const eyebrow = interpolate(frame, [2, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [88, 97], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "absolute", left: 0, top: 0, opacity: out }}>
      <Scrim left={-320} top={-300} width={1300} height={1010} strength={0.44} blur={16} />
      <div style={{ position: "absolute", left: 95, top: 50, width: 1000 }}>
      <div
        style={{
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 33,
          letterSpacing: "0.055em",
          color: PALETTE.paper,
          whiteSpace: "nowrap",
          opacity: eyebrow,
          transform: `translateY(${(1 - eyebrow) * -8}px)`,
          marginBottom: 8,
        }}
      >
        AFTERLAP · ENERGY &amp; BATTLE DECISION SUPPORT
      </div>
      {LINES.map((line, i) => {
        const t = interpolate(frame, [6 + i * 5, 20 + i * 5], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const eased = 1 - (1 - t) * (1 - t) * (1 - t);
        return (
          <div
            key={line.map((s) => s.text).join("")}
            style={{
              fontFamily: FONT.display,
              fontWeight: 700,
              fontSize: 120,
              lineHeight: "106px",
              letterSpacing: "-0.005em",
              color: PALETTE.paper,
              whiteSpace: "nowrap",
              textShadow: "0 6px 30px rgba(0,0,0,0.55)",
              opacity: eased,
              transform: `translateY(${(1 - eased) * 26}px)`,
            }}
          >
            {line.map((span) => (
              <span
                key={span.text}
                style={{ color: span.accent ? PALETTE.attack : PALETTE.paper }}
              >
                {span.text}
              </span>
            ))}
          </div>
        );
      })}
      </div>
    </div>
  );
};
