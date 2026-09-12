'use client';

import { useState } from 'react';
import type { SubmitEvent } from 'react';

import { useRace } from './Connection';
import { Transport } from './RaceView';
import styles from './race.module.css';

export function Control() {
  const { frame, circuits, send, connected, selected, select, history } = useRace();
  const [profile, setProfile] = useState('neutral');
  const [manual, setManual] = useState(false);
  function reset(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    send('reset', {
      settings: {
        circuit: data.get('circuit'),
        variability: { preset: data.get('variability') },
        seed: Number(data.get('seed')),
        cars: Number(data.get('cars')),
        laps: Number(data.get('laps')),
        dt_s: 0.01,
        wetness: Number(data.get('wetness')),
        temperature_k: Number(data.get('temperature')) + 273.15,
        wind_mps: Number(data.get('wind')),
        time_limit_s: Number(data.get('duration')),
        wake: data.get('wake') === 'on',
      },
    });
  }
  function apply(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    send('control', {
      car_id: selected,
      action: {
        profile,
        pace_scale: Number(data.get('pace')),
        target_lateral_d_m: Number(data.get('lane')),
        low_drag: data.get('aero') === 'on',
        throttle: manual ? Number(data.get('throttle')) : null,
        brake: manual ? Number(data.get('brake')) : null,
      },
    });
  }
  function download() {
    const payload = { kind: 'recent-observed-telemetry', frames: history, frame_limit: 200 };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload)], { type: 'application/json' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = `race-telemetry-${frame?.settings.seed ?? 0}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <main className={styles.main}>
      <div className={styles.heading}>
        <div>
          <p>EXPERIMENT SETUP</p>
          <h1>Race control</h1>
        </div>
        <span>Seeded scenarios · shared engine · headless training</span>
      </div>
      <Transport />
      <div className={styles.controlGrid}>
        <section className={styles.panel}>
          <h2>Configure a race</h2>
          <p className={styles.caption}>
            Reset applies these settings and creates a new paused race.
          </p>
          <form onSubmit={reset} key={frame?.generation} className={styles.form}>
            <label className={styles.wide}>
              Circuit
              <select name="circuit" defaultValue={frame?.settings.circuit}>
                {circuits.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.wide}>
              Variability
              <select name="variability" defaultValue={frame?.settings.variability.preset ?? 'mild'}>
                <option value="baseline">Deterministic baseline</option>
                <option value="mild">Mild variability</option>
                <option value="training">Broad training variation</option>
                <option value="stress">Stress testing</option>
              </select>
              <span>Driver traits, car setup, surface and wind. Synthetic scenario ranges.</span>
            </label>
            <label>
              Seed
              <input
                name="seed"
                type="number"
                min="0"
                max="4294967295"
                required
                defaultValue={frame?.settings.seed ?? 42}
              />
            </label>
            <label>
              Cars
              <input
                name="cars"
                type="number"
                min="1"
                max="20"
                required
                defaultValue={frame?.settings.cars ?? 20}
              />
            </label>
            <label>
              Laps
              <input
                name="laps"
                type="number"
                min="1"
                max="80"
                required
                defaultValue={frame?.settings.laps ?? 3}
              />
            </label>
            <label>
              Time limit (s)
              <input
                name="duration"
                type="number"
                min="1"
                max="14400"
                required
                defaultValue={frame?.settings.time_limit_s ?? 1800}
              />
            </label>
            <label>
              Wetness (0 dry, 1 wet)
              <input
                name="wetness"
                type="number"
                min="0"
                max="1"
                step="0.1"
                defaultValue={frame?.settings.wetness ?? 0}
                required
              />
            </label>
            <label>
              Ambient (°C)
              <input
                name="temperature"
                type="number"
                min="0"
                max="50"
                step="0.1"
                defaultValue={Number(
                  ((frame?.settings.temperature_k ?? 303.15) - 273.15).toFixed(1),
                )}
                required
              />
            </label>
            <label>
              Wind (m/s)
              <input
                name="wind"
                type="number"
                min="-20"
                max="20"
                step="0.1"
                defaultValue={frame?.settings.wind_mps ?? 0}
                required
              />
            </label>
            <label className={styles.checkbox}>
              <input name="wake" type="checkbox" defaultChecked={frame?.settings.wake ?? true} />{' '}
              Wake interactions
            </label>
            <button type="submit" className={styles.primary} disabled={!connected}>
              Reset race
            </button>
          </form>
        </section>
        <section className={styles.panel}>
          <h2>Driver & battery controls</h2>
          <p className={styles.caption}>
            Commands include driver delay. Physical energy and tyre limits still apply.
          </p>
          <form onSubmit={apply} className={styles.form}>
            <label>
              Car
              <select value={selected} onChange={(event) => select(event.target.value)}>
                {frame?.cars.map((car) => (
                  <option key={car.id}>{car.id}</option>
                ))}
              </select>
            </label>
            <label>
              Battery profile
              <select value={profile} onChange={(event) => setProfile(event.target.value)}>
                {['harvest', 'conserve', 'neutral', 'push', 'overtake'].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Pace fraction
              <input
                name="pace"
                type="number"
                min="0.7"
                max="1"
                step="0.01"
                defaultValue="0.94"
                required
              />
            </label>
            <label>
              Lateral target (m)
              <input
                name="lane"
                type="number"
                min="-5"
                max="5"
                step="0.1"
                defaultValue="-2.5"
                required
              />
            </label>
            <label className={styles.checkbox}>
              <input name="aero" type="checkbox" /> Low-drag aero
            </label>
            <label className={styles.checkbox}>
              <input
                type="checkbox"
                checked={manual}
                onChange={(event) => setManual(event.target.checked)}
              />{' '}
              Manual pedals
            </label>
            <label>
              Throttle
              <input
                name="throttle"
                type="number"
                min="0"
                max="1"
                step="0.05"
                defaultValue="0.5"
                disabled={!manual}
                required={manual}
              />
            </label>
            <label>
              Brake
              <input
                name="brake"
                type="number"
                min="0"
                max="1"
                step="0.05"
                defaultValue="0"
                disabled={!manual}
                required={manual}
              />
            </label>
            <button type="submit" className={styles.primary} disabled={!connected}>
              Apply driver command
            </button>
            <button
              type="button"
              disabled={!connected}
              onClick={() => send('control', { car_id: selected, action: null })}
            >
              Return to automatic
            </button>
          </form>
        </section>
        <section className={styles.panel}>
          <h2>Replay & export</h2>
          <p className={styles.caption}>
            Save a complete internal checkpoint, then compare another intervention from the same
            state.
          </p>
          <div className={styles.actions}>
            <button type="button" disabled={!connected} onClick={() => send('checkpoint')}>
              Save checkpoint
            </button>
            <button
              type="button"
              disabled={!connected || !frame?.has_checkpoint}
              onClick={() => send('restore')}
            >
              Restore checkpoint
            </button>
            <button type="button" disabled={!history.length} onClick={download}>
              Download recent telemetry
            </button>
          </div>
          <p className={styles.caption}>
            Telemetry export contains the latest 200 observed frames. Full training transitions come
            from the generator.
          </p>
        </section>
        <section className={styles.panel}>
          <h2>Headless generator</h2>
          <p className={styles.caption}>
            Run seeded episodes without opening a browser. Each record has the observation, action,
            reward, next observation and termination flags.
          </p>
          <pre>make race-generate CIRCUIT=monza SEED=42</pre>
          <pre>make race-train CIRCUIT=monza STEPS=10000</pre>
          <p className={styles.caption}>
            Independent training interface: race-bms-v1. Training does not promote or deploy a
            model.
          </p>
        </section>
      </div>
    </main>
  );
}
