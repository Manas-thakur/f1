import { Easing, interpolate, useCurrentFrame } from "remotion";
import type { Camera } from "../three/camera";
import { Car } from "../three/Car";
import { Track } from "../three/Track";
import { Frame } from "../ui/Frame";
import { EASE_OUT, FONT, T, VIDEO } from "../theme";

const ease = Easing.bezier(...EASE_OUT);

const CAMERA: Camera = {
  eye: [0, 150, -50],
  target: [0, 0, 0],
  up: [0, 0, 1],
  fov: 0.62,
  width: VIDEO.width,
  height: VIDEO.height,
};

export const Outcome = () => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const pass = interpolate(frame, [16, 86], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const held = interpolate(frame, [78, 98], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const own = -19 + pass * 32;
  const rival = -10 + pass * 18;
  return (
    <Frame step="05" title="Judge at the checkpoint">
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0, opacity: enter }}
      >
        <Track camera={CAMERA} from={-30} to={30} halfWidth={8} lanes={1} />
        <Car camera={CAMERA} x={own} z={-3.1} fill={T.soft} stroke={T.accent} />
        <Car camera={CAMERA} x={rival} z={3.1} fill={T.surface} stroke={T.aqua} />
      </svg>
      <div
        style={{
          position: "absolute",
          left: 96,
          top: 800,
          opacity: held,
          transform: `translateY(${(1 - held) * 10}px)`,
        }}
      >
        <div style={{ fontFamily: FONT.body, fontSize: 44, color: T.good }}>Position retained</div>
        <div
          style={{
            marginTop: 12,
            fontFamily: FONT.body,
            fontSize: 28,
            color: T.muted,
            maxWidth: 1100,
          }}
        >
          Measured laps later at the named checkpoint, not at the moment of passing.
        </div>
      </div>
    </Frame>
  );
};
