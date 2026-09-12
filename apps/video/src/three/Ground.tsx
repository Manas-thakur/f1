import { basisOf, ground, groundRing, projectAll, toPointsAttr } from "./camera";
import type { Camera, Vec3 } from "./camera";

export type GroundShapeProps = {
  readonly camera: Camera;
  readonly points: readonly Vec3[];
  readonly fill?: string | undefined;
  readonly fillOpacity?: number | undefined;
  readonly stroke?: string | undefined;
  readonly strokeWidth?: number | undefined;
  readonly strokeOpacity?: number | undefined;
  readonly dash?: string | undefined;
};

export const GroundShape = ({
  camera,
  points,
  fill,
  fillOpacity,
  stroke,
  strokeWidth,
  strokeOpacity,
  dash,
}: GroundShapeProps) => {
  const p = projectAll(basisOf(camera), points);
  if (p.some((q) => !q.visible)) return null;
  return (
    <polygon
      points={toPointsAttr(p)}
      fill={fill ?? "none"}
      fillOpacity={fillOpacity ?? 1}
      stroke={stroke ?? "none"}
      strokeWidth={strokeWidth ?? 0}
      strokeOpacity={strokeOpacity ?? 1}
      strokeDasharray={dash ?? undefined}
      strokeLinejoin="round"
    />
  );
};

export const GroundRing = ({
  camera,
  cx,
  cz,
  rx,
  rz,
  ...rest
}: Omit<GroundShapeProps, "points"> & {
  readonly cx: number;
  readonly cz: number;
  readonly rx: number;
  readonly rz: number;
}) => <GroundShape camera={camera} points={groundRing(cx, cz, rx, rz, 64)} {...rest} />;

export const GroundLine = ({
  camera,
  x1,
  z1,
  x2,
  z2,
  stroke,
  strokeWidth,
  strokeOpacity,
  dash,
}: Omit<GroundShapeProps, "points" | "fill" | "fillOpacity"> & {
  readonly x1: number;
  readonly z1: number;
  readonly x2: number;
  readonly z2: number;
}) => {
  const p = projectAll(basisOf(camera), [ground(x1, z1), ground(x2, z2)]);
  if (p.some((q) => !q.visible)) return null;
  return (
    <polyline
      points={toPointsAttr(p)}
      fill="none"
      stroke={stroke ?? "none"}
      strokeWidth={strokeWidth ?? 1}
      strokeOpacity={strokeOpacity ?? 1}
      strokeDasharray={dash ?? undefined}
    />
  );
};
