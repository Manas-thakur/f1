import { interpolate, useCurrentFrame } from "remotion";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const DurableChip = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [6, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const cover = interpolate(frame, [0, 5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [56, 62], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <>
    <Scrim left={520} top={80} width={900} height={300} strength={0.22} blur={14} opacity={cover * out} />
    <div
      style={{
        position: "absolute",
        left: 726,
        top: 206,
        background: PALETTE.green,
        borderRadius: 10,
        padding: "12px 34px 16px 42px",
        opacity: rise * out,
        transform: `translateY(${(1 - rise) * 12}px)`,
        boxShadow: "0 0 30px rgba(138,205,158,0.28)",
      }}
    >
      <span
        style={{
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 59,
          letterSpacing: "0.03em",
          color: PALETTE.ink,
        }}
      >
        POSITION RETAINED
      </span>
    </div>
    </>
  );
};
