import { interpolate, useCurrentFrame } from "remotion";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const DurableChip = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [44, 47], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <>
    <Scrim left={634} top={140} width={660} height={250} strength={0.2} blur={16} opacity={rise * out} />
    <div
      style={{
        position: "absolute",
        left: 726,
        top: 206,
        background: "rgba(35,168,52,0.97)",
        borderRadius: 10,
        padding: "12px 34px 16px 42px",
        opacity: rise * out,
        transform: `translateY(${(1 - rise) * 12}px)`,
        boxShadow: "0 0 38px rgba(84,223,89,0.34)",
      }}
    >
      <span
        style={{
          fontFamily: FONT.display,
          fontWeight: 600,
          fontSize: 59,
          letterSpacing: "0.03em",
          color: PALETTE.paper,
        }}
      >
        DURABLE POSITION
      </span>
    </div>
    </>
  );
};
