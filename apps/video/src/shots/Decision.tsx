import { fade } from "../motion";
import { FONT, T } from "../theme";

export const Decision = ({ frame }: { readonly frame: number }) => {
  const live = fade(frame, 664, 692, 776, 800);
  if (live <= 0) return null;
  const detail = fade(frame, 686, 710, 776, 800);
  return (
    <div style={{ position: "absolute", left: 88, top: 884, opacity: live }}>
      <div style={{ fontFamily: FONT.mono, fontSize: 22, color: T.muted, letterSpacing: "0.08em" }}>
        RECOMMENDATION · proposed
      </div>
      <div style={{ fontFamily: FONT.body, fontSize: 56, color: T.accent, marginTop: 4 }}>
        Prepare attack
      </div>
      <div style={{ fontFamily: FONT.body, fontSize: 26, color: T.muted, marginTop: 8, opacity: detail }}>
        through the counterattack checkpoint · expires in 2.0 s
      </div>
    </div>
  );
};
