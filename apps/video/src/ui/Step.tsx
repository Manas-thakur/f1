import { FONT, T } from "../theme";

export type StepProps = {
  readonly n: string;
  readonly title: string;
  readonly note: string;
  readonly opacity: number;
};

export const Step = ({ n, title, note, opacity }: StepProps) => (
  <div style={{ position: "absolute", left: 88, top: 72, opacity }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 20 }}>
      <span style={{ fontFamily: FONT.mono, fontSize: 19, color: T.muted }}>{n}</span>
      <span style={{ fontFamily: FONT.body, fontSize: 30, color: T.ink }}>{title}</span>
    </div>
    <div style={{ fontFamily: FONT.body, fontSize: 21, color: T.muted, marginTop: 6 }}>{note}</div>
  </div>
);
