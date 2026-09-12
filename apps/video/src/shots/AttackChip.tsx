import { interpolate, useCurrentFrame } from "remotion";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const AttackChip = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tick = interpolate(frame, [14, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [40, 48], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const jitter = frame > 8 && frame < 16 ? (Math.floor(frame / 2) % 2 === 0 ? 0.62 : 1) : 1;
  return (
    <>
    <Scrim left={1206} top={40} width={600} height={260} strength={0.24} blur={17} opacity={rise * out} />
    <div
      style={{
        position: "absolute",
        left: 1294,
        top: 104,
        display: "flex",
        alignItems: "center",
        gap: 12,
        background: "rgba(26,29,32,0.88)",
        backdropFilter: "blur(9px)",
        borderRadius: 8,
        padding: "7px 18px 9px",
        opacity: rise * out * jitter,
        transform: `scale(${0.92 + 0.08 * rise})`,
      }}
    >
      <span
        style={{
          fontFamily: FONT.display,
          fontWeight: 700,
          fontSize: 88,
          letterSpacing: "0.015em",
          color: PALETTE.paper,
          lineHeight: "90px",
        }}
      >
        ATTACK
      </span>
      <span
        style={{
          fontSize: 62,
          lineHeight: "66px",
          color: PALETTE.green,
          opacity: tick,
          transform: `scale(${0.6 + 0.4 * tick})`,
        }}
      >
        ✓
      </span>
    </div>
    </>
  );
};
