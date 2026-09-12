import type { ReactNode } from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Plate } from "./Plate";
import { BEATS } from "./timeline";
import { PALETTE } from "./theme";
import { Caption } from "./ui/Caption";
import { Microtext } from "./ui/Microtext";
import { Scrim } from "./ui/Scrim";
import { AttackChip } from "./shots/AttackChip";
import { Corridor } from "./shots/Corridor";
import { Decision } from "./shots/Decision";
import { DurableChip } from "./shots/DurableChip";
import { EnergyDebt } from "./shots/EnergyDebt";
import { Logo } from "./shots/Logo";
import { RuleMask } from "./shots/RuleMask";
import { Title } from "./shots/Title";
import { WaitGhost } from "./shots/WaitGhost";

const OVERLAYS: Record<string, () => ReactNode> = {
  title: Title,
  debt: EnergyDebt,
  mask: RuleMask,
  corridor: Corridor,
  decision: Decision,
  waitGhost: WaitGhost,
  attackChip: AttackChip,
  durable: DurableChip,
  logo: Logo,
};

export const Promo = () => (
  <AbsoluteFill style={{ backgroundColor: PALETTE.ink }}>
    <Plate />

    <Sequence from={120} durationInFrames={812} layout="none">
      <Scrim left={0} top={790} width={1920} height={290} strength={0.7} blur={22} shape="linear" />
    </Sequence>

    {BEATS.map((b) => {
      const Overlay = OVERLAYS[b.id];
      if (!Overlay) return null;
      return (
        <Sequence key={b.id} from={b.from} durationInFrames={b.durationInFrames} layout="none">
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
