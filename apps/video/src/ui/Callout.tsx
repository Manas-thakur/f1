import type { ReactNode } from "react";
import { FONT, T } from "../theme";

export type CalloutProps = {
  readonly x: number;
  readonly y: number;
  readonly dx: number;
  readonly dy: number;
  readonly opacity: number;
  readonly tone?: string | undefined;
  readonly children: ReactNode;
};

export const Callout = ({ x, y, dx, dy, opacity, tone, children }: CalloutProps) => {
  const color = tone ?? T.accent;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, opacity }}>
      <svg
        width={1920}
        height={1080}
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      >
        <line x1={x} y1={y} x2={x + dx} y2={y + dy} stroke={color} strokeWidth={1.5} />
        <circle cx={x} cy={y} r={3.5} fill={color} />
      </svg>
      <div
        style={{
          position: "absolute",
          left: x + dx,
          top: y + dy,
          transform: dx < 0 ? "translate(-100%, -100%)" : "translate(0, -100%)",
          paddingBottom: 8,
          fontFamily: FONT.body,
          color: T.ink,
          whiteSpace: "nowrap",
        }}
      >
        {children}
      </div>
    </div>
  );
};

export const Readout = ({
  label,
  value,
  unit,
  tone,
}: {
  readonly label: string;
  readonly value: string;
  readonly unit: string;
  readonly tone?: string | undefined;
}) => (
  <div style={{ borderBottom: `1px solid ${tone ?? T.accent}`, paddingBottom: 6 }}>
    <div style={{ fontFamily: FONT.body, fontSize: 18, color: T.muted, letterSpacing: "0.04em" }}>
      {label}
    </div>
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: 34,
          color: T.ink,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
      <span style={{ fontFamily: FONT.body, fontSize: 17, color: T.muted }}>{unit}</span>
    </div>
  </div>
);
