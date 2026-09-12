import { FONT } from "../theme";

const LINE =
  "ILLUSTRATIVE CONCEPT RENDER · NOT AFFILIATED WITH FORMULA 1 · SCORING METHODS SHOWN ARE INDICATIVE · NO TRAINED WEIGHTS · NO CERTIFICATION CLAIMED · ALL FIGURES ARE SYNTHETIC · V1.0";

export type MicrotextProps = {
  readonly opacity?: number | undefined;
};

export const Microtext = ({ opacity }: MicrotextProps) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 20,
      textAlign: "center",
      fontFamily: FONT.display,
      fontWeight: 500,
      fontSize: 13,
      letterSpacing: "0.06em",
      color: "rgba(255,255,255,0.34)",
      opacity: opacity ?? 1,
      pointerEvents: "none",
    }}
  >
    {LINE}
  </div>
);
