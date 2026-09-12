import { OffthreadVideo, interpolate, staticFile, useCurrentFrame } from "remotion";
import { VIDEO } from "./theme";

export type Grade = {
  readonly saturate: number;
  readonly brightness: number;
  readonly contrast: number;
  readonly blur: number;
};

type GradeStop = Grade & { readonly frame: number };

const STOPS: readonly GradeStop[] = [
  { frame: 0, saturate: 1, brightness: 1, contrast: 1, blur: 0 },
  { frame: 92, saturate: 1, brightness: 1, contrast: 1, blur: 0 },
  { frame: 112, saturate: 0.62, brightness: 0.96, contrast: 1.04, blur: 0 },
  { frame: 182, saturate: 0.62, brightness: 0.96, contrast: 1.04, blur: 0 },
  { frame: 212, saturate: 0.4, brightness: 0.9, contrast: 1.1, blur: 7 },
  { frame: 318, saturate: 0.4, brightness: 0.9, contrast: 1.1, blur: 7 },
  { frame: 332, saturate: 0.1, brightness: 0.84, contrast: 1.2, blur: 15 },
  { frame: 548, saturate: 0.1, brightness: 0.84, contrast: 1.2, blur: 15 },
  { frame: 562, saturate: 0.1, brightness: 0.8, contrast: 1.2, blur: 26 },
  { frame: 576, saturate: 0.4, brightness: 0.88, contrast: 1.1, blur: 20 },
  { frame: 582, saturate: 0.66, brightness: 0.94, contrast: 1.04, blur: 13 },
  { frame: 700, saturate: 0.66, brightness: 0.94, contrast: 1.04, blur: 13 },
  { frame: 726, saturate: 0.8, brightness: 0.96, contrast: 1.03, blur: 13 },
  { frame: 762, saturate: 0.96, brightness: 1, contrast: 1.02, blur: 0 },
  { frame: 866, saturate: 0.96, brightness: 1, contrast: 1.02, blur: 0 },
  { frame: 870, saturate: 0.8, brightness: 0.72, contrast: 1.02, blur: 0 },
  { frame: 874, saturate: 0.5, brightness: 0.39, contrast: 1.02, blur: 0 },
  { frame: 876, saturate: 0.2, brightness: 0.1, contrast: 1.02, blur: 0 },
  { frame: 878, saturate: 0, brightness: 0.02, contrast: 1, blur: 0 },
  { frame: 942, saturate: 0, brightness: 0, contrast: 1, blur: 0 },
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
        )}) contrast(${track(frame, "contrast")}) blur(${track(frame, "blur")}px)`,
        transform: "scale(1.045)",
      }}
    />
  );
};
