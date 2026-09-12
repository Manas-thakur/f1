import type { ReactNode } from "react";
import { FONT, T } from "../theme";

export type FrameProps = {
  readonly step: string;
  readonly title: string;
  readonly children?: ReactNode | undefined;
};

export const Frame = ({ step, title, children }: FrameProps) => (
  <>
    <div
      style={{
        position: "absolute",
        left: 96,
        top: 72,
        display: "flex",
        alignItems: "baseline",
        gap: 24,
      }}
    >
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: 20,
          letterSpacing: "0.08em",
          color: T.muted,
        }}
      >
        {step}
      </span>
      <span style={{ fontFamily: FONT.body, fontSize: 29, color: T.ink }}>{title}</span>
    </div>
    <div
      style={{
        position: "absolute",
        left: 96,
        right: 96,
        top: 128,
        height: 1,
        background: T.rule,
      }}
    />
    {children}
  </>
);
