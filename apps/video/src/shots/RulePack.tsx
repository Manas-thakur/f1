import { fade } from "../motion";
import { FONT, T } from "../theme";

const ROWS: readonly (readonly [string, string, string])[] = [
  ["Season revision", "2026.08", "pass"],
  ["Event pack", "r3 · 4f21ac", "pass"],
  ["Race-control state", "green · lap 34", "pass"],
  ["Deployment window", "2 / sector", "pass"],
  ["Rival lateral position", "not supplied", "unknown"],
];

export const RulePack = ({ frame }: { readonly frame: number }) => {
  const live = fade(frame, 344, 372, 476, 500);
  if (live <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        right: 88,
        top: 300,
        width: 640,
        background: T.surface,
        border: `1px solid ${T.rule}`,
        padding: 28,
        opacity: live,
      }}
    >
      {ROWS.map(([label, value, status], i) => {
        const a = fade(frame, 352 + i * 12, 372 + i * 12, 476, 500);
        return (
          <div
            key={label}
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 20,
              padding: "11px 0",
              borderBottom: i === ROWS.length - 1 ? "none" : `1px solid ${T.rule}`,
              opacity: a,
            }}
          >
            <span style={{ fontFamily: FONT.body, fontSize: 20, color: T.ink, flex: 1 }}>
              {label}
            </span>
            <span style={{ fontFamily: FONT.mono, fontSize: 19, color: T.muted }}>{value}</span>
            <span
              style={{
                fontFamily: FONT.body,
                fontSize: 18,
                color: status === "pass" ? T.good : T.muted,
                width: 78,
                textAlign: "right",
              }}
            >
              {status}
            </span>
          </div>
        );
      })}
    </div>
  );
};
