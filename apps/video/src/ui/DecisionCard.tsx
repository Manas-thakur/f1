import type { CSSProperties } from "react";
import { FONT, PALETTE } from "../theme";

const OPTIONS: readonly string[] = ["ATTACK NOW", "DELAY", "DEFEND", "RECHARGE"];

const BODY: readonly string[] = [
  "Lower future energy debt",
  "Reduced re-pass exposure",
  "Action legal under current rule state",
];

export type DecisionCardProps = {
  readonly reveal: number;
  readonly bodyReveal: number;
  readonly optionsReveal: number;
  readonly highlight: string;
  readonly style?: CSSProperties | undefined;
};

export const DecisionCard = ({
  reveal,
  bodyReveal,
  optionsReveal,
  highlight,
  style,
}: DecisionCardProps) => (
  <div style={{ position: "absolute", width: 748, ...style }}>
    <div
      style={{
        background: "rgba(14,17,20,0.86)",
        backdropFilter: "blur(10px)",
        borderRadius: 16,
        border: `1px solid ${PALETTE.panelEdge}`,
        padding: "14px 22px 20px",
        transform: `scaleY(${0.88 + 0.12 * reveal})`,
        transformOrigin: "top center",
        opacity: reveal,
      }}
    >
      <div style={{ display: "inline-block", background: PALETTE.chip, padding: "2px 10px 3px" }}>
        <span
          style={{
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 22,
            letterSpacing: "0.06em",
            color: PALETTE.paper,
          }}
        >
          APEXLEDGER · LIVE DECISION
        </span>
      </div>
      <div
        style={{
          fontFamily: FONT.display,
          fontWeight: 700,
          fontSize: 67,
          lineHeight: "72px",
          marginTop: 4,
          opacity: bodyReveal,
        }}
      >
        <span style={{ color: PALETTE.paper }}>WAIT </span>
        <span style={{ color: PALETTE.green, textShadow: "0 0 24px rgba(84,223,89,0.42)" }}>
          ONE WINDOW
        </span>
      </div>
      <div style={{ marginTop: 6, opacity: bodyReveal }}>
        {BODY.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: FONT.display,
              fontWeight: 400,
              fontSize: 29,
              lineHeight: "37px",
              color: "rgba(255,255,255,0.94)",
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
    <div
      style={{
        marginTop: 8,
        background: "rgba(14,17,20,0.86)",
        backdropFilter: "blur(10px)",
        borderRadius: 12,
        border: `1px solid ${PALETTE.panelEdge}`,
        padding: "6px 16px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "fit-content",
        opacity: optionsReveal,
      }}
    >
      {OPTIONS.map((option, i) => (
        <span key={option} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {i > 0 ? <span style={{ color: "rgba(255,255,255,0.4)", fontSize: 20 }}>·</span> : null}
          <span
            style={{
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 28,
              letterSpacing: "0.03em",
              padding: "2px 10px 3px",
              background: option === highlight ? "rgba(222,229,232,0.84)" : "transparent",
              color: option === highlight ? "#11151a" : "rgba(255,255,255,0.92)",
            }}
          >
            {option}
          </span>
        </span>
      ))}
    </div>
  </div>
);
