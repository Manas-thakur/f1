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
    <Scrim left={1216} top={54} width={520} height={228} strength={0.24} blur={17} opacity={rise * out} />
    <div
      style={{
        position: "absolute",
        left: 1313,
        top: 121,
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
          fontSize: 56,
          letterSpacing: "0.015em",
          color: PALETTE.paper,
          lineHeight: "58px",
        }}
      >
        ATTACK
      </span>
      <span
        style={{
          fontSize: 44,
          lineHeight: "48px",
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
