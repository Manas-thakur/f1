'use client';

import { useState } from 'react';

import { CarState } from './CarState';
import { Dial } from './Dial';
import { lapClock, signedSeconds } from './lapTiming';
import { RECHARGE_ALLOWANCE_MJ, clamp01, fixed, ratioPercent } from './readouts';
import type { GapReadout } from './readouts';
import { useTelemetry } from './useTelemetry';
import { useRaceToggleShortcut } from '../race/Connection';
import styles from './telemetry.module.css';

const SEGMENTS = 20;
const GAP_SCALE_S = 3;

function deltaNote(connected: boolean, present: boolean, carId: string, delta: number | undefined) {
  if (!connected) {
    return 'SIMULATOR OFFLINE';
  }
  if (!present) {
    return `${carId.toUpperCase()} NOT IN SESSION`;
  }
  if (delta === undefined) {
    return 'NO REFERENCE LAP';
  }
  return delta < 0 ? '▾ FASTER' : '▴ SLOWER';
}

function Gap({ gap, side }: { readonly gap: GapReadout | undefined; readonly side: string }) {
  return (
    <div className={styles.gapCell} data-side={side}>
      <strong>{gap ? signedSeconds(gap.gap_s) : '--.---'}</strong>
      <i style={{ width: `${clamp01((gap?.gap_s ?? 0) / GAP_SCALE_S) * 100}%` }} />
    </div>
  );
}

export function Dashboard({ carId, controls = true, carIds, onCarChange }: {
  readonly carId: string;
  readonly controls?: boolean;
  readonly carIds?: readonly string[];
  readonly onCarChange?: (carId: string) => void;
}) {
  const { frame, connected, car, timing, flag, send, boost, stopBoost } = useTelemetry(carId);
  const [boosting, setBoosting] = useState(false);
  useRaceToggleShortcut(controls);
  const running = frame?.status === 'running';
  const startable = connected && frame !== null && !['finished', 'failed', 'truncated'].includes(frame.status);
  const boostActive = frame?.manual_boost_car_id === carId;
  const recommendation = frame?.recommendations?.[carId];
  const boostable = connected && running && car.present && !boosting
    && (boostActive || Boolean(recommendation?.manual_available));
  const lit = Math.round(clamp01(car.lapFraction) * SEGMENTS);
  const delta = timing.delta_s;
  async function applyBoost() {
    setBoosting(true);
    await (boostActive ? stopBoost() : boost());
    setBoosting(false);
  }
  return (
    <div className={styles.dashboard} data-connected={connected} data-status={frame?.status ?? 'offline'}>
      <div className={styles.strip} role="img"
        aria-label={`Lap progress ${ratioPercent(car.lapFraction)}`}>
        {Array.from({ length: SEGMENTS }, (_, index) => (
          <i key={index} data-lit={car.lapFraction !== undefined && index < lit} />
        ))}
      </div>
      <div className={styles.flagPill} data-tone={flag.tone}>
        <b>{'◆'}</b>{flag.label}
      </div>

      <section className={styles.posPanel} aria-label="Position and lap">
        <div>
          <small>POS</small>
          <strong>{car.position ?? '--'}</strong>
          <span>/{car.field || '--'}</span>
        </div>
        <div>
          <small>LAP</small>
          <strong>{car.lap ?? '--'}</strong>
          <span>/{car.laps || '--'}</span>
        </div>
      </section>

      <section className={styles.delta} aria-label="Delta to best lap"
        data-sign={delta === undefined ? 'none' : delta < 0 ? 'faster' : 'slower'}>
        <strong>{signedSeconds(delta)}</strong>
        <span>{deltaNote(connected, car.present, carId, delta)}</span>
      </section>

      <section className={styles.timesPanel} aria-label="Lap times">
        <div>
          <small>BEST</small>
          <strong className={styles.best}>{lapClock(timing.best_s)}</strong>
        </div>
        <div>
          <small>LAP TIME</small>
          <strong>{lapClock(timing.elapsed_s)}</strong>
        </div>
      </section>

      <section className={styles.energy} aria-label="Energy store">
        <header>
          <span>ENERGY</span>
          <b><em>MJ</em> {fixed(car.energy_mj, 2)}</b>
        </header>
        <div className={styles.energyTrack}>
          <i style={{ width: `${clamp01(car.energy_percent) * 100}%` }} data-energy-mode={car.mode} />
        </div>
        <footer>
          <span>{ratioPercent(car.energy_percent)} STORE</span>
          <span>DEP {fixed(car.deployed_lap_mj, 2)}</span>
          <span>REC {fixed(car.recharged_lap_mj, 2)}/{RECHARGE_ALLOWANCE_MJ.toFixed(2)}</span>
        </footer>
      </section>

      <CarState car={car} />

      <div className={styles.modeRow}>
        <span className={styles.modePill} data-energy-mode={car.mode}>{car.mode}</span>
      </div>

      <Dial speed_kph={car.speed_kph} power_kw={car.power_kw} profile={car.profile} />

      <section className={styles.pedals} aria-label="Throttle and brake">
        <header>
          <span className={styles.throttleLabel}>THROTTLE</span>
          <span className={styles.brakeLabel}>BRAKE</span>
        </header>
        <div className={styles.pedalBars}>
          <div className={styles.pedalTrack} data-pedal="throttle">
            <i style={{ height: `${clamp01(car.throttle) * 100}%` }} />
          </div>
          <div className={styles.pedalTrack} data-pedal="brake">
            <i style={{ height: `${clamp01(car.brake) * 100}%` }} />
          </div>
        </div>
        <footer>
          <span className={styles.throttleLabel}>{ratioPercent(car.throttle)}</span>
          <span className={styles.brakeLabel}>{ratioPercent(car.brake)}</span>
        </footer>
      </section>

      <div className={styles.carTag} data-selectable={Boolean(onCarChange)}>
        {onCarChange ? (
          <label>
            <small>CAR</small>
            <select aria-label="Telemetry car" value={carId}
              onChange={(event) => onCarChange(event.target.value)}>
              {carIds?.map((id) => <option key={id}>{id}</option>)}
            </select>
          </label>
        ) : (
          <><small>CAR</small><strong>{carId.replace(/^car-/, '').toUpperCase()}</strong></>
        )}
      </div>

      <section className={styles.gaps} aria-label="Gap to the cars ahead and behind">
        <span className={styles.gapPos}>{car.ahead ? `P${car.ahead.position}` : '--'}</span>
        <Gap gap={car.ahead} side="ahead" />
        <div className={styles.gapCentre}>
          <strong>{car.position ?? '--'}</strong>
          <small>of {car.field || '--'}</small>
        </div>
        <Gap gap={car.behind} side="behind" />
        <span className={styles.gapPos}>{car.behind ? `P${car.behind.position}` : '--'}</span>
      </section>

      <div className={styles.dashboardActions}>
        <button type="button" className={styles.boost} disabled={!boostable}
          data-active={boostActive}
          aria-label={`${boostActive ? 'Stop boost for' : 'Apply boost to'} ${carId}`}
          onClick={() => void applyBoost()}>
          {boosting ? 'WAIT' : boostActive ? 'BOOST ON' : 'BOOST'}
        </button>
        {controls && (
          <button type="button" className={styles.start} disabled={!startable}
            aria-label={running ? 'Pause race' : 'Start race'}
            aria-keyshortcuts="Space"
            onClick={() => send(running ? 'pause' : 'start')}>
            {running ? '❚❚' : '▶'}
          </button>
        )}
      </div>
    </div>
  );
}
