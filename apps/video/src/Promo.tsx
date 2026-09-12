import { AbsoluteFill, Sequence } from "remotion";
import { loadFont as loadDisplay } from "@remotion/google-fonts/Oswald";
import { loadFont as loadCaption } from "@remotion/google-fonts/Poppins";
import { GRADES, Plate } from "./Plate";
import { SHOTS } from "./timeline";
import { PALETTE } from "./theme";
import { Caption } from "./ui/Caption";
import { Microtext } from "./ui/Microtext";
import { Corridor } from "./shots/Corridor";
import { Decision } from "./shots/Decision";
import { EnergyDebt } from "./shots/EnergyDebt";
import { Ghost } from "./shots/Ghost";
import { Logo } from "./shots/Logo";
import { RuleMask } from "./shots/RuleMask";
import { Title } from "./shots/Title";
import { Verdict } from "./shots/Verdict";

loadDisplay();
loadCaption();

const OVERLAYS: Record<string, () => React.ReactNode> = {
  beam: Title,
  debt: EnergyDebt,
  mask: RuleMask,
  corridor: Corridor,
  decision: Decision,
  ghost: Ghost,
  verdict: Verdict,
  logo: Logo,
};

export const Promo = () => (
  <AbsoluteFill style={{ backgroundColor: PALETTE.ink }}>
    <AbsoluteFill>
      {SHOTS.map((s) => {
        const grade = GRADES[s.id];
        if (!grade) return null;
        return (
          <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} layout="none">
            <Plate grade={grade} />
          </Sequence>
        );
      })}
    </AbsoluteFill>

    <Sequence from={0} durationInFrames={97} layout="none">
      <Title />
    </Sequence>

    {SHOTS.filter((s) => s.id !== "openA" && s.id !== "openB" && s.id !== "beam").map((s) => {
      const Overlay = OVERLAYS[s.id];
      if (!Overlay) return null;
      return (
        <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} layout="none">
          <Overlay />
        </Sequence>
      );
    })}

    <Sequence from={323} durationInFrames={619} layout="none">
      <Microtext />
    </Sequence>

    <Caption />
  </AbsoluteFill>
);
