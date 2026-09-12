'use client';

import { useState } from 'react';

import { useRace } from './Connection';
import styles from './race.module.css';
import type { CircuitMap, RaceCar } from './types';

const COLORS = ['#55d9ae', '#f6bd60', '#7eb7ff', '#f68089', '#ccadff'];

function carPoint(map: CircuitMap, car: RaceCar): [number, number] | null {
  const progress = car.channels['s_m'];
  if (progress === undefined) {
    return null;
  }
  const position =
    ((((progress % map.length_m) + map.length_m) % map.length_m) / map.length_m) *
    map.points.length;
  const index = Math.floor(position);
  const first = map.points[index];
  const next = map.points[(index + 1) % map.points.length];
  if (!first || !next) {
    return null;
  }
  const fraction = position - index;
  const dx = next[0] - first[0];
  const dy = next[1] - first[1];
  const norm = Math.hypot(dx, dy) || 1;
  const offset = car.channels['lateral_d_m'] ?? 0;
  return [
    first[0] + fraction * dx - (offset * dy) / norm,
    first[1] + fraction * dy + (offset * dx) / norm,
  ];
}

export function Circuit() {
  const { frame, selected, select } = useRace();
  const [zoom, setZoom] = useState(1);
  const [grid, setGrid] = useState(true);
  const map = frame?.circuit_map;
  if (!map) {
    return <div className={styles.mapEmpty}>Connect a simulator to load circuit geometry.</div>;
  }
  const xs = map.points.map((point) => point[0]);
  const ys = map.points.map((point) => point[1]);
  const minX = Math.min(...xs) - 120;
  const minY = Math.min(...ys) - 120;
  const width = Math.max(...xs) - minX + 120;
  const height = Math.max(...ys) - minY + 120;
  const path = `${map.points.map((point, index) => `${index ? 'L' : 'M'}${point.join(',')}`).join(' ')} Z`;
  return (
    <section className={styles.mapPanel} aria-label="Live circuit">
      <div className={styles.mapTools}>
        <span>{map.name.toUpperCase()}</span>
        <div>
          <button type="button" onClick={() => setGrid(!grid)}>
            Grid {grid ? 'on' : 'off'}
          </button>
          <button
            type="button"
            onClick={() => setZoom(Math.max(1, zoom - 0.5))}
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            onClick={() => setZoom(Math.min(4, zoom + 0.5))}
            aria-label="Zoom in"
          >
            +
          </button>
          <button type="button" onClick={() => setZoom(1)}>
            Fit track
          </button>
        </div>
      </div>
      <svg
        viewBox={`${minX} ${minY} ${width} ${height}`}
        className={styles.map}
        aria-label={map.name}
      >
        <defs>
          <pattern id="race-grid" width="100" height="100" patternUnits="userSpaceOnUse">
            <path d="M100 0H0V100" fill="none" stroke="#242d36" strokeWidth="1" />
          </pattern>
        </defs>
        {grid && <rect x={minX} y={minY} width={width} height={height} fill="url(#race-grid)" />}
        <g
          transform={`translate(${minX + width / 2} ${minY + height / 2}) scale(${zoom}) translate(${-minX - width / 2} ${-minY - height / 2})`}
        >
          <path d={path} fill="none" stroke="#263341" strokeWidth="48" strokeLinejoin="round" />
          <path d={path} fill="none" stroke="#627386" strokeWidth="25" strokeLinejoin="round" />
          <path d={path} fill="none" stroke="#24313f" strokeWidth="17" strokeLinejoin="round" />
          {map.points[0] && (
            <text x={map.points[0][0]} y={map.points[0][1] - 40} fill="#aeb9c5" fontSize="28">
              S / F (assumed)
            </text>
          )}
          {frame.cars.map((car) => {
            const point = carPoint(map, car);
            if (!point) {
              return null;
            }
            const number = Number(car.id.slice(-2));
            return (
              <g
                key={car.id}
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${car.id}`}
                onClick={() => select(car.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    select(car.id);
                  }
                }}
                style={{ cursor: 'pointer' }}
              >
                <circle
                  cx={point[0]}
                  cy={point[1]}
                  r={selected === car.id ? 22 : 13}
                  fill={COLORS[(number - 1) % COLORS.length]}
                  stroke="#0c131c"
                  strokeWidth="4"
                />
                <text x={point[0] + 22} y={point[1] - 18} fill="#edf3f9" fontSize="30">
                  {number}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className={styles.mapFooter}>
        <span>
          {(map.length_m / 1000).toFixed(3)} KM · {frame.settings.cars} CARS
        </span>
        <span>Artwork: ROY Jules · CC BY 4.0 · via Crowdflow</span>
      </div>
    </section>
  );
}
