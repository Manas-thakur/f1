import { interpolate, useCurrentFrame } from "remotion";
import { Chip } from "../ui/Chip";
import { Scrim } from "../ui/Scrim";
import { FONT, PALETTE } from "../theme";

export const EnergyDebt = () => {
  const frame = useCurrentFrame();
  const tag = interpolate(frame, [30, 46], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [80, 89], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <Scrim
        left={772}
        top={512}
        width={480}
        height={186}
        strength={0.3}
        blur={16}
        opacity={tag}
      />
      <div
        style={{
          position: "absolute",
          left: 838,
          top: 552,
          opacity: tag,
          transform: `translateX(${(1 - tag) * 22}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT.display,
            fontWeight: 500,
            fontSize: 39,
            letterSpacing: "0.035em",
            color: PALETTE.paper,
            whiteSpace: "nowrap",
          }}
        >
          ENERGY DEBT →
        </div>
        <div style={{ marginTop: 4, marginLeft: -6 }}>
          <Chip tone="amber" fontSize={31}>
            NEXT WINDOW
          </Chip>
        </div>
      </div>
    </div>
  );
};
