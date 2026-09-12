import { interpolate, useCurrentFrame } from "remotion";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const WaitGhost = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 4], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fade = interpolate(frame, [5, 11], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <>
    <Scrim left={800} top={30} width={860} height={420} strength={0.3} blur={24} opacity={rise * fade} />
    <div
      style={{
        position: "absolute",
        left: 890,
        top: 120,
        width: 578,
        height: 230,
        borderRadius: 14,
        background: "rgba(156,164,169,0.34)",
        backdropFilter: "blur(7px)",
        opacity: rise * fade,
        transform: `perspective(1800px) rotateY(-9deg) scale(${0.93 + 0.07 * rise})`,
        transformOrigin: "left top",
      }}
    >
      <span
        style={{
          position: "absolute",
          left: 22,
          top: 6,
          fontFamily: FONT.display,
          fontWeight: 700,
          fontSize: 78,
          letterSpacing: "0.015em",
          color: PALETTE.paper,
        }}
      >
        PLAN
      </span>
    </div>
    </>
  );
};
