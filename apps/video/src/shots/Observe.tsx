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

const ROWS: readonly (readonly [string, string, string])[] = [
  ["OWN BATTERY", "4.12", "MJ · measured"],
  ["RIVAL BATTERY", "2.4 – 3.0", "MJ · interval"],
  ["GAP", "0.82", "s · observed"],
  ["OBSERVATION AGE", "0.27", "s"],
];

export const Observe = () => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const drift = interpolate(frame, [0, 190], [-11, 9], {
    extrapolateRight: "clamp",
  });
  return (
    <Frame step="01" title="Observe">
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0, opacity: enter }}
      >
        <Track camera={CAMERA} from={-30} to={30} halfWidth={8} lanes={1} />
        <Car camera={CAMERA} x={drift} z={-3.1} fill={T.soft} stroke={T.accent} />
        <Car camera={CAMERA} x={drift - 9.2} z={3.1} fill={T.surface} stroke={T.aqua} />
      </svg>

      <div style={{ position: "absolute", left: 96, top: 704 }}>
        {ROWS.map(([label, value, unit], i) => {
          const a = interpolate(frame, [18 + i * 6, 38 + i * 6], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: ease,
          });
          return (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 24,
                padding: "8px 0",
                borderTop: `1px solid ${T.rule}`,
                width: 880,
                opacity: a,
              }}
            >
              <span
                style={{
                  fontFamily: FONT.body,
                  fontSize: 20,
                  color: T.muted,
                  width: 260,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 30,
                  color: T.ink,
                  width: 200,
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {value}
              </span>
              <span style={{ fontFamily: FONT.body, fontSize: 20, color: T.muted }}>{unit}</span>
            </div>
          );
        })}
      </div>
    </Frame>
  );
};
