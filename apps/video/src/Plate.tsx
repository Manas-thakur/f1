import { OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { VIDEO } from "./theme";

export type Grade = {
  readonly saturate: number;
  readonly brightness: number;
  readonly contrast: number;
};

export const GRADES: Record<string, Grade> = {
  openA: { saturate: 1, brightness: 1, contrast: 1 },
  openB: { saturate: 1, brightness: 1, contrast: 1 },
  beam: { saturate: 1, brightness: 1, contrast: 1 },
  debt: { saturate: 0.42, brightness: 0.92, contrast: 1.08 },
  mask: { saturate: 0.34, brightness: 0.84, contrast: 1.14 },
  corridor: { saturate: 0.12, brightness: 0.6, contrast: 1.3 },
  decision: { saturate: 0.62, brightness: 0.9, contrast: 1.06 },
  ghost: { saturate: 0.8, brightness: 0.95, contrast: 1.04 },
  verdict: { saturate: 0.86, brightness: 0.97, contrast: 1.02 },
  logo: { saturate: 0, brightness: 0, contrast: 1 },
};

export type PlateProps = {
  readonly grade: Grade;
};

export const Plate = ({ grade }: PlateProps) => {
  const frame = useCurrentFrame();
  return (
    <OffthreadVideo
      src={staticFile("plate.mp4")}
      startFrom={0}
      muted
      style={{
        position: "absolute",
        width: VIDEO.width,
        height: VIDEO.height,
        objectFit: "cover",
        filter: `saturate(${grade.saturate}) brightness(${grade.brightness}) contrast(${grade.contrast})`,
      }}
      pauseWhenBuffering={false}
      key={`plate-${frame < 0 ? 0 : 0}`}
    />
  );
};
