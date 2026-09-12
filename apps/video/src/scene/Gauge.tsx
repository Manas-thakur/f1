import { anchorAt } from "../three/camera";
import type { Basis } from "../three/camera";
import { K, T } from "../theme";

export const Gauge = ({
  basis,
  x,
  z,
  level,
  band,
  colour,
  opacity,
}: {
  readonly basis: Basis;
  readonly x: number;
  readonly z: number;
  readonly level: number;
  readonly band: readonly [number, number] | null;
  readonly colour: string;
  readonly opacity: number;
}) => {
  if (opacity <= 0) return null;
  const p = anchorAt(basis, x, z, 2.7);
  if (!p.visible) return null;
  const w = 200 * K;
  const h = 24 * K;
  const left = p.x - w / 2;
  const top = p.y;
  return (
    <g opacity={opacity}>
      <rect x={left} y={top} width={w} height={h} fill="#0d1117" opacity={0.72} rx={2 * K} />
      {band ? (
        <g>
          <rect
            x={left + w * band[0]}
            y={top}
            width={w * (band[1] - band[0])}
            height={h}
            fill={colour}
            opacity={0.4}
          />
          <rect x={left + w * band[0]} y={top} width={2.4 * K} height={h} fill={colour} />
          <rect x={left + w * band[1]} y={top} width={2.4 * K} height={h} fill={colour} />
        </g>
      ) : (
        <rect x={left} y={top} width={w * level} height={h} fill={colour} />
      )}
      <rect
        x={left}
        y={top}
        width={w}
        height={h}
        fill="none"
        stroke={colour}
        strokeWidth={1.6 * K}
        rx={2 * K}
      />
    </g>
  );
};

export const Gate = ({
  basis,
  x,
  state,
  opacity,
}: {
  readonly basis: Basis;
  readonly x: number;
  readonly state: "pass" | "unknown";
  readonly opacity: number;
}) => {
  if (opacity <= 0) return null;
  const colour = state === "pass" ? T.recover : T.unknown;
  const a = anchorAt(basis, x, -7.4, 0);
  const b = anchorAt(basis, x, 7.4, 0);
  const at = anchorAt(basis, x, -7.4, 3.1);
  const bt = anchorAt(basis, x, 7.4, 3.1);
  if (!a.visible || !b.visible) return null;
  return (
    <g opacity={opacity}>
      <polygon
        points={`${a.x},${a.y} ${b.x},${b.y} ${bt.x},${bt.y} ${at.x},${at.y}`}
        fill={colour}
        fillOpacity={state === "pass" ? 0.12 : 0.06}
      />
      <line x1={a.x} y1={a.y} x2={at.x} y2={at.y} stroke={colour} strokeWidth={3 * K} />
      <line x1={b.x} y1={b.y} x2={bt.x} y2={bt.y} stroke={colour} strokeWidth={3 * K} />
      <line
        x1={at.x}
        y1={at.y}
        x2={bt.x}
        y2={bt.y}
        stroke={colour}
        strokeWidth={3 * K}
        strokeDasharray={state === "unknown" ? `${14 * K} ${10 * K}` : undefined}
      />
    </g>
  );
};

export const Checkpoint = ({
  basis,
  x,
  opacity,
}: {
  readonly basis: Basis;
  readonly x: number;
  readonly opacity: number;
}) => {
  if (opacity <= 0) return null;
  if (x < basis.eye[0] + 6) return null;
  const cells = 16;
  const half = 7.4;
  const step = (half * 2) / cells;
  const quad = (z0: number, z1: number) => {
    const a = anchorAt(basis, x, z0, 0);
    const b = anchorAt(basis, x + 2.8, z0, 0);
    const c = anchorAt(basis, x + 2.8, z1, 0);
    const d = anchorAt(basis, x, z1, 0);
    if (!a.visible || !c.visible) return null;
    return `${a.x},${a.y} ${b.x},${b.y} ${c.x},${c.y} ${d.x},${d.y}`;
  };
  return (
    <g opacity={opacity}>
      {Array.from({ length: cells }, (_, i) => {
        const pts = quad(-half + i * step, -half + (i + 1) * step);
        if (!pts) return null;
        return <polygon key={i} points={pts} fill={i % 2 === 0 ? "#ffffff" : "#11161b"} />;
      })}
    </g>
  );
};
