'use client';

import { SPEED_SCALE_KPH, clamp01, fixed } from './readouts';
import styles from './telemetry.module.css';

const TICKS = 46;
const START_DEG = -120;
const SWEEP_DEG = 240;
const INNER_R = 88;
const OUTER_R = 118;
const CENTRE = 130;
const AMBER_FROM = 0.72;

function place(centre: number, unit: number, radius: number) {
  return Math.round((centre + unit * radius) * 1000) / 1000;
}

function tickLine(fraction: number) {
  const radians = ((START_DEG + fraction * SWEEP_DEG) * Math.PI) / 180;
  const sin = Math.sin(radians);
  const cos = Math.cos(radians);
  return {
    x1: place(CENTRE, sin, INNER_R),
    y1: place(CENTRE, -cos, INNER_R),
    x2: place(CENTRE, sin, OUTER_R),
    y2: place(CENTRE, -cos, OUTER_R),
  };
}

export function Dial({
  speed_kph, power_kw, profile,
}: {
  readonly speed_kph: number | undefined;
  readonly power_kw: number | undefined;
  readonly profile: string;
}) {
  const level = clamp01(speed_kph === undefined ? undefined : speed_kph / SPEED_SCALE_KPH);
  return (
    <section className={styles.dial} aria-label="Speed, electrical power and deployment profile">
      <svg viewBox="0 0 260 260" role="presentation" focusable="false">
        {Array.from({ length: TICKS }, (_, index) => {
          const fraction = index / (TICKS - 1);
          const line = tickLine(fraction);
          const lit = speed_kph !== undefined && fraction <= level;
          return (
            <line key={index} {...line} strokeWidth={7} strokeLinecap="butt"
              data-lit={lit ? (fraction >= AMBER_FROM ? 'high' : 'on') : 'off'} />
          );
        })}
      </svg>
      <div className={styles.dialPower}>
        <strong>{power_kw === undefined ? '--' : `${power_kw > 0 ? '+' : ''}${fixed(power_kw, 0)}`}</strong>
        <small>KW ELECTRICAL</small>
      </div>
      <div className={styles.dialSpeed}>
        <strong>{fixed(speed_kph, 0)}</strong>
        <small>KM/H</small>
      </div>
      <div className={styles.dialProfile}>
        <strong>{profile}</strong>
        <small>PROFILE</small>
      </div>
    </section>
  );
}
