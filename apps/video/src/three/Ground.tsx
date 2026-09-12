import type { CSSProperties, ReactNode } from "react";
import { basisOf, groundRing, project, projectAll, toPointsAttr } from "./camera";
import type { Camera, Projected, Vec3 } from "./camera";
import { quadMatrix3d } from "./homography";

export type GroundPolygonProps = {
  readonly camera: Camera;
  readonly points: readonly Vec3[];
  readonly fill?: string | undefined;
  readonly stroke?: string | undefined;
  readonly strokeWidth?: number | undefined;
  readonly opacity?: number | undefined;
  readonly filter?: string | undefined;
};

export const GroundPolygon = ({
  camera,
  points,
  fill,
  stroke,
  strokeWidth,
  opacity,
  filter,
}: GroundPolygonProps) => {
  const basis = basisOf(camera);
  const projected = projectAll(basis, points);
  if (projected.some((p) => !p.visible)) return null;
  return (
    <polygon
      points={toPointsAttr(projected)}
      fill={fill ?? "none"}
      stroke={stroke ?? "none"}
      strokeWidth={strokeWidth ?? 0}
      opacity={opacity ?? 1}
      filter={filter ?? undefined}
      strokeLinejoin="round"
    />
  );
};

export type GroundEllipseProps = {
  readonly camera: Camera;
  readonly center: readonly [number, number];
  readonly radius: readonly [number, number];
  readonly fill?: string | undefined;
  readonly stroke?: string | undefined;
  readonly strokeWidth?: number | undefined;
  readonly opacity?: number | undefined;
  readonly height?: number | undefined;
};

export const GroundEllipse = ({
  camera,
  center,
  radius,
  fill,
  stroke,
  strokeWidth,
  opacity,
  height,
}: GroundEllipseProps) => (
  <GroundPolygon
    camera={camera}
    points={groundRing(center[0], center[1], radius[0], radius[1], 84, height ?? 0)}
    fill={fill}
    stroke={stroke}
    strokeWidth={strokeWidth}
    opacity={opacity}
  />
);

export type GroundPlateProps = {
  readonly camera: Camera;
  readonly corners: readonly [Vec3, Vec3, Vec3, Vec3];
  readonly width: number;
  readonly height: number;
  readonly style?: CSSProperties | undefined;
  readonly children: ReactNode;
};

export const GroundPlate = ({
  camera,
  corners,
  width,
  height,
  style,
  children,
}: GroundPlateProps) => {
  const basis = basisOf(camera);
  const projected = corners.map((c) => project(basis, c)) as [
    Projected,
    Projected,
    Projected,
    Projected,
  ];
  if (projected.some((p) => !p.visible)) return null;
  const matrix = quadMatrix3d(width, height, projected);
  if (!matrix) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width,
        height,
        transformOrigin: "0 0",
        transform: matrix,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export type WireBoxProps = {
  readonly camera: Camera;
  readonly min: Vec3;
  readonly max: Vec3;
  readonly stroke: string;
  readonly strokeWidth: number;
  readonly opacity?: number | undefined;
};

export const WireBox = ({ camera, min, max, stroke, strokeWidth, opacity }: WireBoxProps) => {
  const basis = basisOf(camera);
  const [x0, y0, z0] = min;
  const [x1, y1, z1] = max;
  const corners: Vec3[] = [
    [x0, y0, z0],
    [x1, y0, z0],
    [x1, y1, z0],
    [x0, y1, z0],
    [x0, y0, z1],
    [x1, y0, z1],
    [x1, y1, z1],
    [x0, y1, z1],
  ];
  const p = corners.map((c) => project(basis, c));
  if (p.some((q) => !q.visible)) return null;
  const edges: readonly [number, number][] = [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 0],
    [4, 5],
    [5, 6],
    [6, 7],
    [7, 4],
    [0, 4],
    [1, 5],
    [2, 6],
    [3, 7],
  ];
  return (
    <g opacity={opacity ?? 1}>
      {edges.map(([a, b]) => {
        const pa = p[a] as Projected;
        const pb = p[b] as Projected;
        return (
          <line
            key={`${a}-${b}`}
            x1={pa.x}
            y1={pa.y}
            x2={pb.x}
            y2={pb.y}
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
        );
      })}
    </g>
  );
};
