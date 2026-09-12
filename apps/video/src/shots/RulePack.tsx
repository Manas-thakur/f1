import { fade } from "../motion";
import { FONT, T } from "../theme";

const ROWS: readonly (readonly [string, string])[] = [
  ["deployment window", "2 / sector"],
  ["rival lateral position", "unknown"],
];

export const RulePack = ({ frame }: { readonly frame: number }) => {
  const live = fade(frame, 344, 372, 476, 500);
  if (live <= 0) return null;
  return (
    <div style={{ position: "absolute", left: 88, top: 932, opacity: live }}>
      {ROWS.map(([label, value], i) => {
        const a = fade(frame, 352 + i * 16, 376 + i * 16, 476, 500);
        const unknown = value === "unknown";
        return (
          <div
            key={label}
            style={{ display: "flex", alignItems: "baseline", gap: 18, marginTop: i === 0 ? 0 : 10, opacity: a }}
          >
            <span style={{ fontFamily: FONT.body, fontSize: 26, color: T.muted }}>{label}</span>
            <span
              style={{
                fontFamily: FONT.mono,
                fontSize: 28,
                color: unknown ? T.muted : T.ink,
                fontStyle: unknown ? "italic" : "normal",
              }}
            >
              {value}
            </span>
          </div>
        );
      })}
    </div>
  );
};
