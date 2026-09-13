'use client';

import { useState } from 'react';

import { clamp01, fixed, ratioPercent } from './readouts';
import { useTelemetry } from './useTelemetry';
import styles from './telemetry.module.css';

function Pedal({ label, value, tone }: {
  readonly label: string;
  readonly value: number | undefined;
  readonly tone: 'throttle' | 'brake';
}) {
  return (
    <div className={styles.racePedal} data-pedal={tone}>
      <div><span>{label}</span><strong>{ratioPercent(value)}</strong></div>
      <div className={styles.racePedalTrack}><i style={{ width: `${clamp01(value) * 100}%` }} /></div>
    </div>
  );
}

export function TelemetryOverlay({ carId, visible }: {
  readonly carId: string;
  readonly visible: boolean;
}) {
  const { car, flag, frame, connected, boost } = useTelemetry(carId);
  const [boosting, setBoosting] = useState(false);
  const recommendation = frame?.recommendations[carId];
  const boostActive = car.mode === 'BOOST';
  const boostable = connected && frame?.status === 'running' && car.present && !boosting
    && Boolean(recommendation?.can_apply);
  async function applyBoost() {
    setBoosting(true);
    await boost();
    setBoosting(false);
  }
  return (
    <div className={styles.overlay} hidden={!visible} aria-label={`Race telemetry for ${carId}`}>
      <header className={styles.raceTelemetryHeader}>
        <div>
          <small>RACE TELEMETRY</small>
          <strong>{carId.toUpperCase()}</strong>
        </div>
        <span className={styles.raceFlag} data-tone={flag.tone}>{flag.label}</span>
        <button type="button" className={styles.raceBoost} disabled={!boostable}
          data-active={boostActive} aria-label={`Apply boost to ${carId}`}
          onClick={() => void applyBoost()}>
          {boosting ? 'WAIT' : boostActive ? 'BOOST ON' : 'BOOST'}
        </button>
        <a href={`/tel/${encodeURIComponent(carId)}`} target="_blank" rel="noreferrer"
          aria-label={`Open full telemetry for ${carId} in a new tab`}>
          OPEN IN NEW TAB ↗
        </a>
      </header>

      <div className={styles.raceTelemetryBody}>
        <section className={styles.raceSpeed} aria-label="Current speed">
          <strong>{fixed(car.speed_kph, 0)}</strong>
          <span>KM/H</span>
        </section>

        <section className={styles.raceBattery} aria-label="Battery charge">
          <div><small>BATTERY</small><strong>{ratioPercent(car.energy_percent)}</strong></div>
          <progress className={styles.raceBatteryTrack} max={100}
            value={car.energy_percent === undefined ? undefined : clamp01(car.energy_percent) * 100}
            data-energy-mode={car.mode} aria-label="Usable battery charge" />
          <footer>
            <span>{fixed(car.energy_mj, 2)} MJ</span>
            <b data-energy-mode={car.mode}>{car.mode}</b>
          </footer>
        </section>

        <section className={styles.raceEssentials} aria-label="Race position, lap and power">
          <div><small>POSITION</small><strong>{car.position === undefined ? '--' : `P${car.position}`}</strong>
            <span>OF {car.field || '--'}</span></div>
          <div><small>LAP</small><strong>{car.lap ?? '--'}</strong><span>OF {car.laps || '--'}</span></div>
          <div><small>POWER</small><strong>{fixed(car.power_kw, 0)}</strong><span>KW</span></div>
        </section>

        <section className={styles.racePedals} aria-label="Throttle and brake">
          <Pedal label="THROTTLE" value={car.throttle} tone="throttle" />
          <Pedal label="BRAKE" value={car.brake} tone="brake" />
        </section>
      </div>
    </div>
  );
}
