'use client';

import { useState } from 'react';
import type { SubmitEvent } from 'react';

import { useRace } from './Connection';
import { Telemetry } from './RacePanels';
import styles from './race.module.css';
import type { CircuitSummary, RaceFrame } from './types';

function RaceSetupForm({ frame, circuits, connected, send }: {
  readonly frame: RaceFrame;
  readonly circuits: CircuitSummary[];
  readonly connected: boolean;
  readonly send: (operation: string, payload?: Record<string, unknown>) => void;
}) {
  const [circuitId, setCircuitId] = useState(frame.settings.circuit);
  const initialCircuit = circuits.find((item) => item.id === circuitId);
  const initialPreset = initialCircuit?.lap_presets.find(
    (item) => item.default_laps === frame.settings.laps,
  );
  const [lapChoice, setLapChoice] = useState(initialPreset?.id ?? 'custom');
  const [customLaps, setCustomLaps] = useState(frame.settings.laps);
  const selectedCircuit = circuits.find((item) => item.id === circuitId);
  const selectedPreset = selectedCircuit?.lap_presets.find((item) => item.id === lapChoice);
  const laps = selectedPreset?.default_laps ?? customLaps;
  function changeCircuit(id: string) {
    const next = circuits.find((item) => item.id === id);
    setCircuitId(id);
    setLapChoice(next?.lap_presets[0]?.id ?? 'custom');
    setCustomLaps(next?.lap_presets[0]?.default_laps ?? customLaps);
  }
  function reset(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    send('reset', {
      settings: {
        circuit: data.get('circuit'),
        variability: { preset: data.get('variability') },
        racing_line: {
          enabled: data.get('racing_line') === 'on',
          corner_strength: Number(data.get('corner_strength')),
          randomness: Number(data.get('line_randomness')),
          wander_m: Number(data.get('line_wander_m')),
          lookahead_m: Number(data.get('line_lookahead_m')),
          smoothing_m: Number(data.get('line_smoothing_m')),
          overtake_in_corners: data.get('corner_overtakes') === 'on',
        },
        seed: Number(data.get('seed')),
        cars: Number(data.get('cars')),
        laps: Number(data.get('laps')),
        dt_s: 0.01,
        wetness: Number(data.get('wetness')),
        weather: data.get('weather'),
        temperature_k: Number(data.get('temperature')) + 273.15,
        wind_mps: Number(data.get('wind')),
        time_limit_s: Number(data.get('duration')),
        wake: data.get('wake') === 'on',
        contact_mode: data.get('contact_mode'),
        storyline: {
          enabled: data.get('storylines') === 'on',
          pit_stops: data.get('pit-stops') === 'on',
          tyre_wear_scale: Number(data.get('tyre-wear')),
        },
      },
    });
  }
  return (
    <form onSubmit={reset} className={styles.form}>
      <label className={styles.wide}>
        Circuit
        <select name="circuit" value={circuitId} onChange={(event) => changeCircuit(event.target.value)}>
          {circuits.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.wide}>
        Lap preset
        <select aria-label="Lap preset" value={lapChoice} onChange={(event) => setLapChoice(event.target.value)}>
          {selectedCircuit?.lap_presets.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label} · {item.default_laps} laps
            </option>
          ))}
          <option value="custom">Custom</option>
        </select>
        {selectedPreset ? (
          <span>
            {laps} laps from the official 2026 circuit listing.{' '}
            <a href={selectedPreset.source_url} target="_blank" rel="noreferrer">Source</a>
          </span>
        ) : <span>Choose any race length from 1 to 80 laps.</span>}
      </label>
      {selectedPreset ? <input type="hidden" name="laps" value={laps} /> : (
        <label>
          Custom laps
          <input
            name="laps"
            type="number"
            min="1"
            max="80"
            required
            value={customLaps}
            onChange={(event) => setCustomLaps(Number(event.target.value))}
          />
        </label>
      )}
      <label className={styles.wide}>
        Variability
        <select aria-label="Variability" name="variability" defaultValue={frame.settings.variability.preset}>
          <option value="baseline">Deterministic baseline</option>
          <option value="mild">Mild variability</option>
          <option value="training">Broad training variation</option>
          <option value="stress">Stress testing</option>
        </select>
        <span>Driver traits, car setup, surface and wind. Synthetic scenario ranges.</span>
      </label>
      <label>
        Seed
        <input name="seed" type="number" min="0" max="4294967295" required defaultValue={frame.settings.seed} />
      </label>
      <label>
        Cars
        <input name="cars" type="number" min="1" max="20" required defaultValue={frame.settings.cars} />
      </label>
      <label>
        Time limit (s)
        <input name="duration" type="number" min="1" max="14400" required defaultValue={frame.settings.time_limit_s} />
      </label>
      <label>
        Weather
        <select aria-label="Weather" name="weather" defaultValue={frame.settings.weather}>
          <option value="sunny">Sunny</option>
          <option value="rainy">Rainy</option>
        </select>
        <span>Visual race-day conditions.</span>
      </label>
      <label>
        Wetness (0 dry, 1 wet)
        <input name="wetness" type="number" min="0" max="1" step="0.1" defaultValue={frame.settings.wetness} required />
      </label>
      <label>
        Ambient (°C)
        <input name="temperature" type="number" min="0" max="50" step="0.1"
          defaultValue={Number((frame.settings.temperature_k - 273.15).toFixed(1))} required />
      </label>
      <label>
        Wind (m/s)
        <input name="wind" type="number" min="-20" max="20" step="0.1" defaultValue={frame.settings.wind_mps} required />
      </label>
      <label className={styles.checkbox}>
        <input name="wake" type="checkbox" defaultChecked={frame.settings.wake} />{' '}
        Wake interactions
      </label>
      <label>
        Contact handling
        <select name="contact_mode" defaultValue={frame.settings.contact_mode}>
          <option value="ignore">Ignore overlaps</option>
          <option value="terminate">End race on contact</option>
        </select>
      </label>
      <label className={styles.checkbox}>
        <input name="storylines" type="checkbox" defaultChecked={frame.settings.storyline.enabled} />{' '}
        Random storylines
      </label>
      <label className={styles.checkbox}>
        <input name="pit-stops" type="checkbox" defaultChecked={frame.settings.storyline.pit_stops} />{' '}
        Automatic pit stops
      </label>
      <label>
        Tire wear scale
        <input name="tyre-wear" type="number" min="0" max="10" step="0.1"
          defaultValue={frame.settings.storyline.tyre_wear_scale} required />
      </label>
      <details className={styles.wide}>
        <summary>Racing lines</summary>
        <div className={styles.form}>
          <label className={styles.checkbox}>
            <input name="racing_line" type="checkbox" defaultChecked={frame.settings.racing_line.enabled} />{' '}
            Dynamic corner lines
          </label>
          <label className={styles.checkbox}>
            <input name="corner_overtakes" type="checkbox"
              defaultChecked={frame.settings.racing_line.overtake_in_corners} />{' '}
            Allow corner overtakes
          </label>
          {([
            ['corner_strength', 'Corner width use', 0, 1, frame.settings.racing_line.corner_strength],
            ['line_randomness', 'Line randomness', 0, 1, frame.settings.racing_line.randomness],
            ['line_wander_m', 'Random wander (m)', 0, 2, frame.settings.racing_line.wander_m],
            ['line_lookahead_m', 'Corner lookahead (m)', 10, 200, frame.settings.racing_line.lookahead_m],
            ['line_smoothing_m', 'Transition smoothing (m)', 5, 100, frame.settings.racing_line.smoothing_m],
          ] as const).map(([name, label, min, max, value]) => <label key={name}>{label}
            <input name={name} type="number" min={min} max={max} step="any" required defaultValue={value} />
          </label>)}
        </div>
      </details>
      <button type="submit" className={styles.primary} disabled={!connected}>
        Reset race
      </button>
    </form>
  );
}

export function Control() {
  const { frame, circuits, send, connected, selected, select, history } = useRace();
  const [profile, setProfile] = useState('neutral');
  const [manual, setManual] = useState(false);
  if (!frame) {
    return (
      <div className={styles.controlContent}>
        <p role="status" className={styles.caption}>Loading race settings…</p>
      </div>
    );
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
    <div className={styles.controlContent}>
      <div className={styles.controlGrid}>
        <section className={styles.panel}>
          <h2>Configure a race</h2>
          <p className={styles.caption}>
            Reset applies these settings and creates a new paused race.
          </p>
          <RaceSetupForm key={`${frame.generation}-${circuits.length}`} {...{
            frame, circuits, connected, send,
          }} />
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
                  <option key={item} value={item}>{item === 'push' ? 'Boost (80%)' : item === 'overtake' ? 'Maximum boost (100%)' : item}</option>
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
        <Telemetry />
        <details className={styles.panel}><summary>About the circuit scene</summary>
          <p>Circuit artwork: ROY Jules, CC BY 4.0, via Crowdflow.
            Scenery is an interpretation of reference material, not surveyed geometry.</p>
          <p>Landscape models and textures: Poly Haven, CC0. Spectator geometry: MakeHuman Community, CC0.</p>
          <p>Physics and vehicle parameters are experimental.
            Research notes and asset sources are included in the repository.</p>
        </details>
      </div>
    </div>
  );
}
