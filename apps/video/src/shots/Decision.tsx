import { fade } from "../motion";
import { FONT, T } from "../theme";

const FIELDS: readonly (readonly [string, string])[] = [
  ["trigger", "detection line · lap 34"],
  ["end condition", "counterattack checkpoint"],
  ["expiry", "2.0 s"],
  ["checked by", "independent plan checker"],
];

export const Decision = ({ frame }: { readonly frame: number }) => {
  const live = fade(frame, 664, 692, 776, 800);
  if (live <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        right: 88,
        top: 288,
        width: 680,
        background: T.surface,
        border: `1px solid ${T.rule}`,
        padding: 32,
        opacity: live,
      }}
    >
      <div style={{ fontFamily: FONT.mono, fontSize: 17, color: T.muted, letterSpacing: "0.08em" }}>
        RECOMMENDATION · proposed
      </div>
      <div style={{ fontFamily: FONT.body, fontSize: 52, color: T.accent, margin: "10px 0 18px" }}>
        Prepare attack
      </div>
      {FIELDS.map(([k, v], i) => {
        const a = fade(frame, 676 + i * 10, 696 + i * 10, 776, 800);
        return (
          <div
            key={k}
            style={{
              display: "flex",
              gap: 24,
              padding: "9px 0",
              borderTop: `1px solid ${T.rule}`,
              opacity: a,
            }}
          >
            <span style={{ fontFamily: FONT.body, fontSize: 19, color: T.muted, width: 220 }}>
              {k}
            </span>
            <span style={{ fontFamily: FONT.mono, fontSize: 19, color: T.ink }}>{v}</span>
          </div>
        );
      })}
    </div>
  );
};
