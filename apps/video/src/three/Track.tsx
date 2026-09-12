import { basisOf, ground, projectAll, toPointsAttr } from "./camera";
import type { Camera } from "./camera";
import { T } from "../theme";

export type TrackProps = {
  readonly camera: Camera;
  readonly from: number;
  readonly to: number;
  readonly halfWidth: number;
  readonly lanes?: number | undefined;
};

export const Track = ({ camera, from, to, halfWidth, lanes }: TrackProps) => {
  const basis = basisOf(camera);
  const surface = projectAll(basis, [
    ground(from, -halfWidth),
    ground(to, -halfWidth),
    ground(to, halfWidth),
    ground(from, halfWidth),
  ]);
  if (surface.some((p) => !p.visible)) return null;
  const n = lanes ?? 0;
  return (
    <g>
      <polygon points={toPointsAttr(surface)} fill={T.raised} />
      <polygon points={toPointsAttr(surface)} fill="none" stroke={T.rule} strokeWidth={2} />
      {Array.from({ length: n }, (_, i) => {
        const z = -halfWidth + ((i + 1) * (halfWidth * 2)) / (n + 1);
        const line = projectAll(basis, [ground(from, z), ground(to, z)]);
        return (
          <polyline
            key={z}
            points={toPointsAttr(line)}
            fill="none"
            stroke={T.track}
            strokeWidth={1.5}
            strokeDasharray="16 14"
          />
        );
      })}
    </g>
  );
};
