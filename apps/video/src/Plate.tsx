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
  { frame: 112, saturate: 0.62, brightness: 0.96, contrast: 1.04 },
  { frame: 182, saturate: 0.62, brightness: 0.96, contrast: 1.04 },
  { frame: 212, saturate: 0.4, brightness: 0.9, contrast: 1.1 },
  { frame: 318, saturate: 0.4, brightness: 0.9, contrast: 1.1 },
  { frame: 332, saturate: 0.1, brightness: 0.78, contrast: 1.2 },
  { frame: 552, saturate: 0.1, brightness: 0.78, contrast: 1.2 },
  { frame: 572, saturate: 0.66, brightness: 0.94, contrast: 1.04 },
  { frame: 686, saturate: 0.66, brightness: 0.94, contrast: 1.04 },
  { frame: 698, saturate: 0.96, brightness: 1, contrast: 1.02 },
  { frame: 866, saturate: 0.96, brightness: 1, contrast: 1.02 },
  { frame: 867, saturate: 0, brightness: 0, contrast: 1 },
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
