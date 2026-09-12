'use client';

import { Circuit } from './Circuit';
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
      <span className={styles.muted}>Compute rate {number(frame?.actual_rate, 2)}×</span>
    </div>
  );
}

export function RaceView() {
  const { frame, selected, select, history } = useRace();
  const car = frame?.cars.find((item) => item.id === selected);
  const ch = car?.channels ?? {};
  const lapProgress =
    car?.finish_time_s !== undefined && car.finish_time_s !== null
      ? 100
      : ch['s_m'] === undefined || !frame
        ? undefined
        : Math.max(0, Math.min(100, (ch['s_m'] / frame.circuit_map.length_m) * 100));
  const speeds = history.map(
    (tick) => tick.cars.find((item) => item.id === selected)?.channels['speed_mps'],
  );
  const trace = speeds.map(
    (speed, i) => `${(i * 600) / Math.max(1, speeds.length - 1)},${100 - (speed ?? 0) * 0.8}`,
  );
  const ranking = frame?.cars ?? [];
  return (
    <main className={styles.main}>
      <div className={styles.heading}>
        <div>
          <p>ENERGY & RACE DYNAMICS</p>
          <h1>Race simulator</h1>
        </div>
        <span>
          SEED {frame?.settings.seed ?? '...'} · {Math.round(1 / (frame?.settings.dt_s ?? 0.01))}{' '}
          Hz reference dynamics
        </span>
      </div>
      <Transport />
      <div className={styles.workspace}>
        <aside className={styles.timing}>
          <h2>
            Classification <span>{ranking.length}</span>
          </h2>
          <div className={styles.tableScroll}>
            <table>
              <thead>
                <tr>
                  <th>POS</th>
                  <th>CAR</th>
                  <th>LAP</th>
                  <th>KM/H</th>
                  <th>ENERGY</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((item, index) => (
                  <tr key={item.id} data-selected={item.id === selected}>
                    <td>{index + 1}</td>
                    <td>
                      <button type="button" onClick={() => select(item.id)}>
                        {item.id}
                      </button>
                    </td>
                    <td>{number(lapNumber(item, frame?.settings.laps ?? 1), 0)}</td>
                    <td>
                      {number(
                        item.channels['speed_mps'] === undefined
                          ? undefined
                          : item.channels['speed_mps'] * 3.6,
                        0,
                      )}
                    </td>
                    <td>
                      {number(
                        item.channels['battery_energy_j'] === undefined
                          ? undefined
                          : item.channels['battery_energy_j'] / 1e6,
                        2,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.caption}>MJ battery energy · delayed simulated sensors</p>
        </aside>
        <Circuit />
      </div>
      <section className={styles.inspector}>
        <div>
          <p>CAR INSPECTOR</p>
          <h2>{selected}</h2>
          <span className={styles.muted}>
            Age {number(frame && car ? frame.time_s - car.observed_at_s : undefined, 2)} s
          </span>
          <p aria-label="Selected car lap">
            {car?.finish_time_s !== undefined && car.finish_time_s !== null ? 'FINISHED' : 'LAP'}{' '}
            {number(lapNumber(car, frame?.settings.laps ?? 1), 0)} / {frame?.settings.laps ?? '?'}
          </p>
          <progress aria-label="Selected car lap progress" max={100} value={lapProgress} />
          <span className={styles.muted}>{number(lapProgress)}% of lap</span>
        </div>
        <div>
          <p>SPEED</p>
          <strong>
            {number(ch['speed_mps'] === undefined ? undefined : ch['speed_mps'] * 3.6)}
          </strong>
          <small> km/h</small>
        </div>
        <div>
          <p>ACCELERATION</p>
          <strong>{number(ch['acceleration_mps2'])}</strong>
          <small> m/s²</small>
        </div>
        <div>
          <p>BATTERY</p>
          <strong>
            {number(
              ch['battery_energy_j'] === undefined ? undefined : ch['battery_energy_j'] / 1e6,
              2,
            )}
          </strong>
          <small> MJ</small>
        </div>
        <div>
          <p>TEMPERATURE</p>
          <strong>
            {number(
              ch['battery_temperature_k'] === undefined
                ? undefined
                : ch['battery_temperature_k'] - 273.15,
            )}
          </strong>
          <small> °C</small>
        </div>
        <div>
          <p>ELECTRICAL POWER</p>
          <strong>
            {number(
              ch['electrical_power_w'] === undefined ? undefined : ch['electrical_power_w'] / 1000,
              0,
            )}
          </strong>
          <small> kW</small>
        </div>
      </section>
      <div className={styles.bottom}>
        <section className={styles.panel}>
          <h2>
            Speed trace <span>recent {selected} telemetry</span>
          </h2>
          <svg
            viewBox="0 0 600 110"
            className={styles.trace}
            role="img"
            aria-label="Recent car speed trace"
          >
            <path d="M0 25H600 M0 50H600 M0 75H600 M0 100H600" stroke="#29323d" />
            <polyline points={trace.join(' ')} fill="none" stroke="#55d9ae" strokeWidth="2" />
          </svg>
        </section>
        <section className={styles.panel}>
          <h2>Race events</h2>
          <div className={styles.events}>
            {frame?.events
              .slice(-5)
              .reverse()
              .map((event, index) => (
                <p key={`${event.session_time_s}-${index}`}>
                  {event.session_time_s.toFixed(2)}s · {event.overtaking_car_id}
                  {' / '}
                  {event.overtaken_car_id} · {event.kind.replaceAll('_', ' ')}
                </p>
              ))}
            {!frame?.events.length && <p>No battle events recorded yet.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}
