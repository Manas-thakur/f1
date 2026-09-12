import type { CSSProperties, ReactNode } from "react";
import { FONT, PALETTE } from "../theme";

export type ChipProps = {
  readonly children: ReactNode;
  readonly tone?: "dark" | "light" | "green" | "amber" | undefined;
  readonly fontSize?: number | undefined;
  readonly style?: CSSProperties | undefined;
};

const TONES = {
  dark: { background: "rgba(18,21,24,0.76)", color: PALETTE.paper },
  light: { background: "rgba(214,222,226,0.86)", color: "#101317" },
  green: { background: "rgba(30,150,44,0.92)", color: PALETTE.paper },
  amber: { background: PALETTE.amber, color: "#140d02" },
} as const;

export const Chip = ({ children, tone, fontSize, style }: ChipProps) => {
  const t = TONES[tone ?? "dark"];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px 4px",
        borderRadius: 4,
        fontFamily: FONT.display,
        fontWeight: 600,
        fontSize: fontSize ?? 26,
        lineHeight: 1.16,
        letterSpacing: "0.045em",
        background: t.background,
        color: t.color,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
};
