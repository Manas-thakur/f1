import { useMemo } from 'react';

import type { CentrelineResponse } from '@/api/trackCatalogue';
import {
  OPENF1_ATTRIBUTION,
  corridorText,
  needsOpenF1Attribution,
  provenanceText,
  shortHash,
} from './readiness';
import styles from './circuits.module.css';

const PAD_FRACTION = 0.04;

export interface CircuitMapProps {
  readonly centreline: CentrelineResponse;
  readonly displayName?: string | null;
  readonly readiness?: string | null;
}

interface Projection {
  readonly points: string;
  readonly viewBox: string;
  readonly startX: number;
  readonly startY: number;
  readonly markerR: number;
  readonly spanX: number;
  readonly spanY: number;
  readonly scaleBarM: number;
  readonly scaleY: number;
}

function project(x: readonly number[], y: readonly number[]): Projection | null {
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (let i = 0; i < x.length; i += 1) {
    const px = x[i] as number;
    const py = -(y[i] as number);
    if (px < minX) minX = px;
    if (px > maxX) maxX = px;
    if (py < minY) minY = py;
    if (py > maxY) maxY = py;
  }
  const rawSpanX = maxX - minX;
  const rawSpanY = maxY - minY;
  if (!Number.isFinite(rawSpanX) || !Number.isFinite(rawSpanY)) {
    return null;
  }
  if (rawSpanX <= 0 || rawSpanY <= 0) {
    return null;
  }
  const pad = Math.max(rawSpanX, rawSpanY) * PAD_FRACTION;
  const spanX = rawSpanX + pad * 2;
  const spanY = rawSpanY + pad * 2;

  const points: string[] = [];
  for (let i = 0; i < x.length; i += 1) {
    points.push(`${((x[i] as number) - minX + pad).toFixed(1)},${(-(y[i] as number) - minY + pad).toFixed(1)}`);
  }

  const target = Math.max(rawSpanX, rawSpanY) / 5;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const scaleBarM = Math.max(magnitude, Math.round(target / magnitude) * magnitude);

  return {
    points: points.join(' '),
    viewBox: `0 0 ${spanX.toFixed(1)} ${spanY.toFixed(1)}`,
    startX: (x[0] as number) - minX + pad,
    startY: -(y[0] as number) - minY + pad,
    markerR: Math.max(rawSpanX, rawSpanY) * 0.012,
    spanX,
    spanY,
    scaleBarM,
    scaleY: spanY - pad * 0.5,
  };
}

export function CircuitMap({ centreline, displayName, readiness }: CircuitMapProps) {
  const projection = useMemo(
    () => project(centreline.x_m, centreline.y_m),
    [centreline.x_m, centreline.y_m],
  );

  const hash = shortHash(centreline.package_hash);
  const name = displayName ?? centreline.track_id;
  const drawn = centreline.x_m.length;

  if (projection === null) {
    return (
      <p className={styles.blocked} data-testid="circuit-map-unavailable">
        The centreline for {centreline.track_id} cannot be drawn: the coordinates the control
        plane returned span no area in one axis, so there is no shape to project. No substitute
        outline is drawn.
      </p>
    );
  }

  const label = [
    `Compiled centreline of ${name}`,
    hash === null ? 'no package hash reported' : `package hash ${hash}`,
    `${drawn} plotted points`,
    readiness === null || readiness === undefined ? null : `readiness ${readiness}`,
    'plan view, metric, no corridor width',
  ]
    .filter((part): part is string => part !== null)
    .join('; ');

  return (
    <div className={styles.mapFrame}>
      <div className={styles.mapSurface}>
        <svg
          className={styles.mapSvg}
          viewBox={projection.viewBox}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={label}
          data-testid="circuit-map-svg"
        >
          <polyline className={styles.mapTrace} points={projection.points} />
          <circle
            className={styles.mapStart}
            cx={projection.startX.toFixed(1)}
            cy={projection.startY.toFixed(1)}
            r={projection.markerR.toFixed(1)}
          />
          <line
            className={styles.mapScale}
            x1={0}
            y1={projection.scaleY.toFixed(1)}
            x2={projection.scaleBarM}
            y2={projection.scaleY.toFixed(1)}
          />
          {}
          <text
            className={styles.mapScaleText}
            x={0}
            y={(projection.scaleY - projection.spanY * 0.014).toFixed(1)}
            fontSize={(projection.spanY * 0.026).toFixed(1)}
          >
            {projection.scaleBarM} m
          </text>
        </svg>
      </div>

      <div className={styles.mapFoot}>
        <span>
          package hash{' '}
          {hash === null ? (
            <span className={styles.unavailable}>not reported</span>
          ) : (
            <span className={styles.hash}>{hash}</span>
          )}
        </span>
        <span>
          {drawn} of{' '}
          {centreline.source_point_count === null ? (
            <span className={styles.unavailable}>an unreported number of</span>
          ) : (
            centreline.source_point_count
          )}{' '}
          compiled samples, strided server-side at{' '}
          {centreline.stride_m === null ? (
            <span className={styles.unavailable}>an unreported stride</span>
          ) : (
            `${centreline.stride_m.toFixed(0)} m`
          )}
        </span>
        <span>
          arrays{' '}
          {shortHash(centreline.arrays_sha256) === null ? (
            <span className={styles.unavailable}>not reported</span>
          ) : (
            <span className={styles.hash}>{shortHash(centreline.arrays_sha256)}</span>
          )}
        </span>
        <span>
          length{' '}
          {centreline.length_m === null ? (
            <span className={styles.unavailable}>not reported</span>
          ) : (
            `${centreline.length_m.toFixed(1)} m`
          )}
        </span>
        <span>corridor {corridorText(centreline.corridor_quality)}</span>
        <span>marker: first sample, s = 0</span>
      </div>

      <p className={styles.attribution}>
        Provenance: {provenanceText(centreline.geometry_provenance)}. Centreline only — the
        drawing carries no track width, kerb or runoff, because the package declares no corridor.
      </p>
      {needsOpenF1Attribution(centreline.geometry_provenance) ? (
        <p className={styles.attribution} data-testid="circuit-map-attribution">
          {OPENF1_ATTRIBUTION}
        </p>
      ) : null}
      {centreline.notice === null ? null : (
        <p className={styles.attribution}>{centreline.notice}</p>
      )}
    </div>
  );
}
