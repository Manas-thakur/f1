import { OffthreadVideo, interpolate, staticFile, useCurrentFrame } from "remotion";
import { VIDEO } from "./theme";

export type Grade = {
  readonly saturate: number;
  readonly brightness: number;
  readonly contrast: number;
};

type GradeStop = Grade & { readonly frame: number };

const STOPS: readonly GradeStop[] = [
  { frame: 0, saturate: 1, brightness: 1, contrast: 1 },
  { frame: 92, saturate: 1, brightness: 1, contrast: 1 },
  { frame: 108, saturate: 0.44, brightness: 0.9, contrast: 1.08 },
  { frame: 182, saturate: 0.44, brightness: 0.9, contrast: 1.08 },
  { frame: 196, saturate: 0.3, brightness: 0.8, contrast: 1.16 },
  { frame: 318, saturate: 0.3, brightness: 0.8, contrast: 1.16 },
  { frame: 330, saturate: 0.1, brightness: 0.76, contrast: 1.2 },
  { frame: 552, saturate: 0.1, brightness: 0.76, contrast: 1.2 },
  { frame: 566, saturate: 0.5, brightness: 0.8, contrast: 1.1 },
  { frame: 682, saturate: 0.5, brightness: 0.8, contrast: 1.1 },
  { frame: 694, saturate: 0.86, brightness: 0.96, contrast: 1.03 },
  { frame: 860, saturate: 0.86, brightness: 0.96, contrast: 1.03 },
  { frame: 868, saturate: 0, brightness: 0, contrast: 1 },
  { frame: 942, saturate: 0, brightness: 0, contrast: 1 },
];

const track = (frame: number, key: keyof Grade): number =>
  interpolate(
    frame,
    STOPS.map((s) => s.frame),
    STOPS.map((s) => s[key]),
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

export const Plate = () => {
  const frame = useCurrentFrame();
  return (
    <OffthreadVideo
      src={staticFile("plate.mp4")}
      muted
      pauseWhenBuffering={false}
      style={{
        position: "absolute",
        width: VIDEO.width,
        height: VIDEO.height,
        objectFit: "cover",
        filter: `saturate(${track(frame, "saturate")}) brightness(${track(
          frame,
          "brightness",
        )}) contrast(${track(frame, "contrast")})`,
      }}
    />
  );
};
