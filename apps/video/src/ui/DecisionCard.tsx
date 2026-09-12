import type { CSSProperties } from "react";
import { FONT, PALETTE } from "../theme";


const BODY: readonly string[] = [
  "Trigger: detection line · end: counterattack checkpoint",
  "Lower future energy debt, less re-pass exposure",
  "Legal under ruleset 2026.08 · checked independently",
];

export type DecisionCardProps = {
  readonly reveal: number;
  readonly bodyReveal: number;
  readonly style?: CSSProperties | undefined;
};

export const DecisionCard = ({
  reveal,
  bodyReveal,
  style,
}: DecisionCardProps) => (
  <div style={{ position: "absolute", width: 726, ...style }}>
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
          AFTERLAP · RECOMMENDATION
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
        <span style={{ color: PALETTE.paper }}>PREPARE </span>
        <span style={{ color: PALETTE.green, textShadow: "0 0 24px rgba(84,223,89,0.42)" }}>
          ATTACK
        </span>
      </div>
      <div style={{ marginTop: 6, opacity: bodyReveal }}>
        {BODY.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: FONT.display,
              fontWeight: 400,
              fontSize: 25,
              lineHeight: "33px",
              color: "rgba(255,255,255,0.94)",
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  </div>
);
