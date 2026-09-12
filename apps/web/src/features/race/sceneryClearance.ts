import type { CircuitMap } from './types';
import { trackPose } from './worldGeometry';

type Point = readonly [number, number];
interface Segment { a: Point; b: Point; error: number }
const midpoint = (a: Point, b: Point): Point => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

function pointDistance(p: Point, a: Point, b: Point) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

function segmentDistance(a: Point, b: Point, c: Point, d: Point) {
  const cross = (p: Point, q: Point, r: Point) =>
    (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  if (Math.max(a[0], b[0]) >= Math.min(c[0], d[0]) && Math.max(c[0], d[0]) >= Math.min(a[0], b[0])
    && Math.max(a[1], b[1]) >= Math.min(c[1], d[1]) && Math.max(c[1], d[1]) >= Math.min(a[1], b[1])
    && cross(a, b, c) * cross(a, b, d) <= 0 && cross(c, d, a) * cross(c, d, b) <= 0) {
    return 0;
  }
  return Math.min(pointDistance(a, c, d), pointDistance(b, c, d),
    pointDistance(c, a, b), pointDistance(d, a, b));
}

export class SceneryClearance {
  private readonly cells = new Map<string, Segment[]>();
  private readonly cellSize = 64;

  constructor(map: CircuitMap, private readonly corridorRadius = 8) {
    for (let i = 0; i < map.points.length; i++) {
      const a = map.points[i] ?? [0, 0];
      const b = map.points[(i + 1) % map.points.length] ?? a;
      const previous = map.points[(i - 1 + map.points.length) % map.points.length] ?? a;
      const following = map.points[(i + 2) % map.points.length] ?? b;
      this.flatten(a, [a[0] + (b[0] - previous[0]) / 6, a[1] + (b[1] - previous[1]) / 6],
        [b[0] - (following[0] - a[0]) / 6, b[1] - (following[1] - a[1]) / 6], b, 0);
    }
  }

  private flatten(a: Point, b: Point, c: Point, d: Point, depth: number) {
    const error = Math.max(pointDistance(b, a, d), pointDistance(c, a, d));
    if (error <= 0.1 || depth >= 12) {
      const segment = { a, b: d, error };
      this.visitCells(a, d, this.corridorRadius + error, (key) => {
        const cell = this.cells.get(key) ?? [];
        cell.push(segment);
        this.cells.set(key, cell);
      });
      return;
    }
    const ab = midpoint(a, b);
    const bc = midpoint(b, c);
    const cd = midpoint(c, d);
    const abc = midpoint(ab, bc);
    const bcd = midpoint(bc, cd);
    const center = midpoint(abc, bcd);
    this.flatten(a, ab, abc, center, depth + 1);
    this.flatten(center, bcd, cd, d, depth + 1);
  }

  private visitCells(a: Point, b: Point, radius: number, visit: (key: string) => void) {
    for (let x = Math.floor((Math.min(a[0], b[0]) - radius) / this.cellSize);
      x <= Math.floor((Math.max(a[0], b[0]) + radius) / this.cellSize); x++) {
      for (let y = Math.floor((Math.min(a[1], b[1]) - radius) / this.cellSize);
        y <= Math.floor((Math.max(a[1], b[1]) + radius) / this.cellSize); y++) {
        visit(`${x}:${y}`);
      }
    }
  }

  circleClear(center: Point, radius: number) {
    return this.segmentClear(center, center, radius);
  }

  segmentClear(a: Point, b: Point, radius: number) {
    const candidates = new Set<Segment>();
    this.visitCells(a, b, radius, (key) =>
      this.cells.get(key)?.forEach((segment) => candidates.add(segment)));
    for (const segment of candidates) {
      if (segmentDistance(a, b, segment.a, segment.b) <= radius + this.corridorRadius + segment.error) {
        return false;
      }
    }
    return true;
  }

  place(map: CircuitMap, progress: number, lateral: number, radius: number) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const offset = lateral + (Math.sign(lateral) || 1) * attempt * Math.max(12, radius * 0.7);
      const pose = trackPose(map, progress * map.length_m, offset);
      if (this.circleClear([pose.position.x, pose.position.z], radius)) {
        return pose;
      }
    }
    return null;
  }
}
