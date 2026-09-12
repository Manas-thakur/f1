import type { ReactNode } from "react";
import { AbsoluteFill, Easing, Sequence, interpolate, useCurrentFrame } from "remotion";
import { FADE, SCENES } from "./timeline";
import { EASE_IN_OUT, T } from "./theme";
import { Candidates } from "./shots/Candidates";
import { Close } from "./shots/Close";
import { Observe } from "./shots/Observe";
import { Open } from "./shots/Open";
import { Outcome } from "./shots/Outcome";
import { Recommend } from "./shots/Recommend";
import { RuleCheck } from "./shots/RuleCheck";

const ease = Easing.bezier(...EASE_IN_OUT);

const SCENE_VIEWS: Record<string, () => ReactNode> = {
  open: Open,
  observe: Observe,
  rules: RuleCheck,
  candidates: Candidates,
  recommend: Recommend,
  outcome: Outcome,
  close: Close,
};

const Fade = ({ duration, children }: { duration: number; children: ReactNode }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, FADE, duration - FADE, duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease },
  );
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

export const Promo = () => (
  <AbsoluteFill style={{ backgroundColor: T.paper }}>
    {SCENES.map((s) => {
      const View = SCENE_VIEWS[s.id];
      if (!View) return null;
      return (
        <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} layout="none">
          <Fade duration={s.durationInFrames}>
            <View />
          </Fade>
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
