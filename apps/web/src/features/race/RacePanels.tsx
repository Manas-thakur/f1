'use client';

import { EnergyTelemetry } from './Energy';
import { energyMode } from './energyStatus';
import { useRace } from './Connection';
import styles from './race.module.css';
import type { RaceCar } from './types';

export function number(value: number | undefined, digits = 1) {
  return value === undefined ? 'Unavailable' : value.toFixed(digits);
}

function lapNumber(car: RaceCar | undefined, total: number) {
  if (car?.finish_time_s !== undefined && car.finish_time_s !== null) {
    return total;
  }
  const completed = car?.channels['lap'];
  return completed === undefined ? undefined : Math.min(total, Math.floor(completed) + 1);
}

export function Transport() {
  const { frame, send, connected } = useRace();
  return (
    <div className={styles.transport}>
      <span className={styles.status}>{frame?.status.toUpperCase() ?? 'OFFLINE'}</span>
      <strong>
        {number(frame?.time_s)} <small>SIM SECONDS</small>
      </strong>
      <span aria-label="Race lap" className={styles.lapCounter}>
        LAP {number(lapNumber(frame?.cars[0], frame?.settings.laps ?? 1), 0)} /{' '}
        {frame?.settings.laps ?? '?'}
      </span>
      <button
        type="button"
        className={styles.primary}
        disabled={!connected}
        onClick={() => send(frame?.status === 'running' ? 'pause' : 'start')}
      >
        {frame?.status === 'running' ? 'Pause race' : 'Start race'}
      </button>
      <button
        type="button"
        disabled={!connected || frame?.status !== 'paused'}
        onClick={() => send('step')}
      >
        Step {frame?.settings.dt_s ?? 0.01}s
      </button>
      <label>
        Playback{' '}
        <select
          value={frame?.requested_rate ?? 1}
          disabled={!connected}
          onChange={(event) => send('speed', { speed: Number(event.target.value) })}
        >
          {[0.25, 0.5, 1, 2, 4, 8].map((speed) => (
            <option key={speed} value={speed}>
              {speed}×
            </option>
          ))}
        </select>
      </label>
      
    </div>
  );
}


export function Classification() {
  const { frame, selected, select } = useRace();
  return <aside className={styles.classification} aria-label="Classification">
    <div className={styles.classificationTitle}>CLASSIFICATION <span>{frame?.cars.length ?? 0}</span></div>
    <div className={styles.classificationScroll}>
      {frame?.cars.map((car, index) => <button key={car.id} type="button"
        aria-label={car.id} aria-pressed={selected === car.id} onClick={() => select(car.id)}>
        <b>{index + 1}</b><span>{car.id.toUpperCase()}
          <em className={styles.classificationEnergy} data-energy-mode={energyMode(car)}>
            {energyMode(car)}</em></span>
        <small>{number(car.channels['speed_mps'] === undefined ? undefined : car.channels['speed_mps'] * 3.6, 0)}</small>
      </button>)}
    </div>
  </aside>;
}

export function Telemetry() {
  const { frame, selected } = useRace();
  const car = frame?.cars.find((item) => item.id === selected);
  const ch = car?.channels ?? {};
  const progress = ch['s_m'] === undefined || !frame ? undefined : ch['s_m'] / frame.circuit_map.length_m * 100;
  return <section className={styles.panel}>
    <h2>{selected}</h2>
    <p aria-label="Selected car lap">LAP {number(lapNumber(car, frame?.settings.laps ?? 1), 0)} / {frame?.settings.laps ?? '?'}</p>
    <progress aria-label="Selected car lap progress" max={100} value={progress} />
    <dl className={styles.telemetryGrid}>
      <dt>Acceleration</dt><dd>{number(ch['acceleration_mps2'])} m/s²</dd>
      <dt>Battery</dt><dd>{number(ch['battery_energy_j'] === undefined ? undefined : ch['battery_energy_j'] / 1e6, 2)} MJ</dd>
      <dt>Temperature</dt><dd>{number(ch['battery_temperature_k'] === undefined ? undefined : ch['battery_temperature_k'] - 273.15)} °C</dd>
      <dt>Electrical power</dt><dd>{number(ch['electrical_power_w'] === undefined ? undefined : ch['electrical_power_w'] / 1000, 0)} kW</dd>
    </dl>
    <EnergyTelemetry />
    <details><summary>Race events</summary>{frame?.events.slice(-10).reverse().map((event, i) =>
      <p key={i}>{event.session_time_s.toFixed(1)}s · {event.overtaking_car_id} / {event.overtaken_car_id} · {event.kind.replaceAll('_', ' ')}</p>)}</details>
  </section>;
}
