import { useCurrentFrame } from "remotion";
import { CAPTIONS, CAPTION_END } from "../timeline";
import { FONT, PALETTE } from "../theme";

export const Caption = () => {
  const frame = useCurrentFrame();
  if (frame >= CAPTION_END) return null;
  let index = -1;
  for (let i = 0; i < CAPTIONS.length; i += 1) {
    const entry = CAPTIONS[i];
    if (entry && entry.frame <= frame) index = i;
  }
  if (index < 0) return null;
  const active = CAPTIONS[index];
  if (!active) return null;
  const age = frame - active.frame;
  const pop = Math.min(1, age / 3);
  const scale = 0.955 + 0.045 * (1 - (1 - pop) * (1 - pop));
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: 862,
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        pointerEvents: "none",
      }}
    >
      <span
        style={{
          fontFamily: FONT.caption,
          fontWeight: 600,
          fontSize: 96,
          lineHeight: "104px",
          color: PALETTE.paper,
          letterSpacing: "-0.012em",
          transform: `scale(${scale})`,
          opacity: pop,
          textShadow: "0 3px 22px rgba(0,0,0,0.62), 0 1px 3px rgba(0,0,0,0.5)",
        }}
      >
        {active.word}
      </span>
    </div>
  );
};
