export type Vec3 = readonly [number, number, number];
export type Vec2 = readonly [number, number];

export type Camera = {
  readonly eye: Vec3;
  readonly target: Vec3;
  readonly up: Vec3;
  readonly fov: number;
  readonly width: number;
  readonly height: number;
};

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: Vec3): Vec3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

export type Basis = {
  readonly eye: Vec3;
  readonly right: Vec3;
  readonly up: Vec3;
  readonly forward: Vec3;
  readonly focal: number;
  readonly width: number;
  readonly height: number;
};

export const basisOf = (camera: Camera): Basis => {
  const forward = norm(sub(camera.target, camera.eye));
  const right = norm(cross(forward, camera.up));
  const up = cross(right, forward);
  const focal = camera.height / 2 / Math.tan(camera.fov / 2);
  return {
    eye: camera.eye,
    right,
    up,
    forward,
    focal,
    width: camera.width,
    height: camera.height,
  };
};

export type Projected = {
  readonly x: number;
  readonly y: number;
  readonly depth: number;
  readonly visible: boolean;
};

export const project = (basis: Basis, point: Vec3): Projected => {
  const rel = sub(point, basis.eye);
  const depth = dot(rel, basis.forward);
  const safe = Math.abs(depth) < 1e-4 ? 1e-4 : depth;
  return {
    x: basis.width / 2 + (basis.focal * dot(rel, basis.right)) / safe,
    y: basis.height / 2 - (basis.focal * dot(rel, basis.up)) / safe,
    depth,
    visible: depth > 1e-3,
  };
};

export const projectAll = (basis: Basis, points: readonly Vec3[]): readonly Projected[] =>
  points.map((p) => project(basis, p));

export const toPointsAttr = (points: readonly Projected[]): string =>
  points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");

export const ground = (x: number, z: number, y = 0): Vec3 => [x, y, z];

export const groundRing = (
  cx: number,
  cz: number,
  radiusX: number,
  radiusZ: number,
  segments = 72,
  y = 0,
): readonly Vec3[] =>
  Array.from({ length: segments }, (_, i) => {
    const a = (i / segments) * Math.PI * 2;
    return ground(cx + Math.cos(a) * radiusX, cz + Math.sin(a) * radiusZ, y);
  });
