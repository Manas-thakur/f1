'use client';

import { LATERAL_LIMIT_M, clamp01, fixed } from './readouts';
import type { CarReadout } from './readouts';
import styles from './telemetry.module.css';

const ARC = 'M3 16 A 19 19 0 0 1 41 16';

function Gauge({ label, value, fill }: {
  readonly label: string;
  readonly value: string;
  readonly fill: number;
}) {
  return (
    <div className={styles.gauge}>
      <small>{label}</small>
      <strong>{value}</strong>
      <svg viewBox="0 0 44 20" role="presentation" focusable="false">
        <path d={ARC} className={styles.gaugeTrack} pathLength={100} />
        <path d={ARC} className={styles.gaugeFill} pathLength={100}
          strokeDasharray={`${clamp01(fill) * 100} 100`} />
      </svg>
    </div>
  );
}

export function CarState({ car }: { readonly car: CarReadout }) {
  const lateral = car.lateral_m;
  const offset = lateral === undefined ? 0 : Math.max(-1, Math.min(1, lateral / LATERAL_LIMIT_M));
  return (
    <section className={styles.carState} aria-label="Observed car state">
      <Gauge label="GRIP" value={fixed(car.grip, 2)} fill={car.grip ?? 0} />
      <Gauge label={'BATT °C'} value={fixed(car.battery_c, 0)}
        fill={car.battery_c === undefined ? 0 : (car.battery_c - 20) / 60} />
      <Gauge label="LAT m" value={fixed(car.lateral_m, 2)} fill={(offset + 1) / 2} />
      <Gauge label={'ACC m/s²'} value={fixed(car.acceleration_mps2, 1)}
        fill={car.acceleration_mps2 === undefined ? 0 : (car.acceleration_mps2 + 20) / 40} />
      <svg className={styles.silhouette} viewBox="0 0 64 150" role="presentation" focusable="false">
        <rect x="20" y="6" width="24" height="138" rx="11" />
        <rect x="26" y="46" width="12" height="34" rx="5" />
        <rect x="6" y="18" width="12" height="26" rx="3" />
        <rect x="46" y="18" width="12" height="26" rx="3" />
        <rect x="6" y="102" width="12" height="28" rx="3" />
        <rect x="46" y="102" width="12" height="28" rx="3" />
        <line className={styles.silhouetteAxis} x1="32" y1="88" x2="32" y2="136" />
        <circle className={styles.silhouetteMark} cx={32 + offset * 22} cy="112" r="4" />
      </svg>
    </section>
  );
}
