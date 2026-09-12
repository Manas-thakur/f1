import { FONT, T } from "../theme";

export type ReadoutProps = {
  readonly x: number;
  readonly y: number;
  readonly label: string;
  readonly value: string;
  readonly unit: string;
  readonly opacity: number;
  readonly tone?: string | undefined;
};

export const Readout = ({ x, y, label, value, unit, opacity, tone }: ReadoutProps) => {
  const color = tone ?? T.accent;
  if (opacity <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: "translate(-50%, -100%)",
        textAlign: "center",
        opacity,
        whiteSpace: "nowrap",
      }}
    >
      <div style={{ fontFamily: FONT.body, fontSize: 22, color: T.muted, letterSpacing: "0.04em" }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, justifyContent: "center" }}>
        <span
          style={{
            fontFamily: FONT.mono,
            fontSize: 46,
            color,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {value}
        </span>
        <span style={{ fontFamily: FONT.body, fontSize: 22, color: T.muted }}>{unit}</span>
      </div>
    </div>
  );
};
