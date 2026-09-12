import type { CSSProperties } from "react";
import { FONT, PALETTE } from "../theme";

const OPTIONS: readonly string[] = ["ATTACK NOW", "DELAY", "DEFEND", "RECHARGE"];

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
  <div style={{ position: "absolute", width: 920, ...style }}>
    <div
      style={{
        background: PALETTE.panel,
        borderRadius: 20,
        border: `1px solid ${PALETTE.panelEdge}`,
        padding: "20px 26px 26px",
        backdropFilter: "blur(3px)",
        transform: `scaleY(${0.86 + 0.14 * reveal})`,
        transformOrigin: "top center",
        opacity: reveal,
      }}
    >
      <div style={{ display: "inline-block", background: PALETTE.chip, padding: "3px 12px 4px" }}>
        <span
          style={{
            fontFamily: FONT.display,
            fontWeight: 600,
            fontSize: 25,
            letterSpacing: "0.07em",
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
          fontSize: 82,
          lineHeight: "86px",
          marginTop: 8,
          letterSpacing: "0.005em",
          opacity: bodyReveal,
        }}
      >
        <span style={{ color: PALETTE.paper }}>WAIT </span>
        <span style={{ color: PALETTE.green, textShadow: "0 0 26px rgba(84,223,89,0.45)" }}>
          ONE WINDOW
        </span>
      </div>
      <div style={{ marginTop: 10, opacity: bodyReveal }}>
        {["Lower future energy debt", "Reduced re-pass exposure", "Action legal under current rule state"].map(
          (line) => (
            <div
              key={line}
              style={{
                fontFamily: FONT.display,
                fontWeight: 400,
                fontSize: 31,
                lineHeight: "40px",
                color: "rgba(255,255,255,0.93)",
              }}
            >
              {line}
            </div>
          ),
        )}
      </div>
    </div>
    <div
      style={{
        marginTop: 10,
        background: PALETTE.panel,
        borderRadius: 14,
        border: `1px solid ${PALETTE.panelEdge}`,
        padding: "8px 18px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        width: "fit-content",
        opacity: optionsReveal,
      }}
    >
      {OPTIONS.map((option, i) => (
        <span key={option} style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {i > 0 ? <span style={{ color: "rgba(255,255,255,0.42)", fontSize: 22 }}>·</span> : null}
          <span
            style={{
              fontFamily: FONT.display,
              fontWeight: 600,
              fontSize: 30,
              letterSpacing: "0.035em",
              padding: "3px 12px 4px",
              background: option === highlight ? "rgba(222,229,232,0.82)" : "transparent",
              color: option === highlight ? "#11151a" : "rgba(255,255,255,0.9)",
            }}
          >
            {option}
          </span>
        </span>
      ))}
    </div>
  </div>
);
