'use client';

import { useRace } from './Connection';
import styles from './race.module.css';
import { energyMode } from './energyStatus';


function value(n: number | undefined, scale = 1, digits = 1) {
  return n === undefined || !Number.isFinite(n) ? 'Unavailable' : (n / scale).toFixed(digits);
}

export function BatteryHud() {
  const { frame, selected, connected, boost, stopBoost } = useRace();
  const car = frame?.cars.find((item) => item.id === selected);
  const ch = car?.channels ?? {};
  const window = car?.battery_window_j;
  const energy = ch['battery_energy_j'];
  const percent = energy === undefined || !window || window[1] <= window[0]
    ? undefined : Math.max(0, Math.min(100, (energy - window[0]) / (window[1] - window[0]) * 100));
  const mode = connected ? energyMode(car) : 'UNAVAILABLE';
  const recommendation = frame?.recommendations?.[selected];
  const boostActive = frame?.manual_boost_car_id === selected;
  return <div className={styles.batteryHud} data-energy-mode={mode} aria-label="Battery and boost">
    <small>ENERGY STORE · {value(percent, 1, 0)}%</small>
    <strong>{value(energy, 1e6, 2)} <small>MJ</small></strong>
    <progress max={100} value={percent} aria-label="Usable battery charge" />
    <span className={styles.energyMode}>{mode} · {value(ch['electrical_power_w'], 1000, 0)} kW</span>
    <span>{mode === 'BOOST' ? 'Burst' : 'Last burst'} {value(ch[mode === 'BOOST' ? 'boost_elapsed_s' : 'last_boost_s'])} s</span>
    <span className={styles.hudRecommendation}>
      {recommendation?.mode.toUpperCase() ?? 'WAITING'} · {recommendation?.boost_available ? 'READY' : 'HELD'}
    </span>
    <button type="button"
      disabled={!connected || (!boostActive && !recommendation?.manual_available)}
      data-active={boostActive}
      aria-label={`${boostActive ? 'Stop boost for' : 'Apply boost to'} ${selected}`}
      onClick={() => void (boostActive ? stopBoost() : boost())}>
      {boostActive ? 'Stop boost' : 'Apply boost'}
    </button>
  </div>;
}

export function EnergyTelemetry() {
  const { frame, selected, history } = useRace();
  const car = frame?.cars.find((item) => item.id === selected);
  const ch = car?.channels ?? {};
  const samples = history.map((tick) => tick.cars.find((item) => item.id === selected)?.channels['battery_energy_j']);
  const paths: string[] = [];
  let segment = '';
  samples.forEach((sample, index) => {
    if (sample === undefined) {
      if (segment) {paths.push(segment); segment = '';}
    } else {
      segment += `${segment ? ' L' : 'M'}${index / Math.max(1, samples.length - 1) * 300} ${65 - sample / 4e6 * 60}`;
    }
  });
  if (segment) {paths.push(segment);}
  return <section className={styles.energyTelemetry} aria-label="Lap energy telemetry">
    <h3>Hybrid energy</h3>
    <p>Blue trail: electrical boost · Green: recharge. The trail is an illustrative overlay.</p>
    <svg viewBox="0 0 300 70" role="img" aria-label="Recent observed battery energy from zero to four megajoules">
      {paths.map((path, index) => <path key={index} d={path} fill="none" stroke="#76dff4" strokeWidth="2" />)}
    </svg>
    <dl className={styles.telemetryGrid}>
      <dt>Delivered profile</dt><dd>{car?.active_profile ?? 'Unavailable'}</dd>
      <dt>Deployed this lap</dt><dd>{value(ch['deployed_this_lap_j'], 1e6, 2)} MJ</dd>
      <dt>Recharged this lap</dt><dd>{value(ch['recharge_this_lap_j'], 1e6, 2)} / 8.50 MJ</dd>
      <dt>Boost this lap</dt><dd>{value(ch['boost_this_lap_s'])} s</dd>
      <dt>Total deployed</dt><dd>{value(ch['deployed_cumulative_j'], 1e6, 2)} MJ</dd>
      <dt>Total recharged</dt><dd>{value(ch['recharge_cumulative_j'], 1e6, 2)} MJ</dd>
      <dt>Total boost</dt><dd>{value(ch['boost_total_s'])} s</dd>
    </dl>
    <details><summary>Completed laps ({car?.energy_laps?.length ?? 0})</summary>
      {car?.energy_laps?.map((lap) => <p key={lap.lap}>
        Lap {lap.lap}: {value(lap.deployed_j, 1e6, 2)} MJ deployed ·{' '}
        {value(lap.recharged_j, 1e6, 2)} MJ recovered · {value(lap.boost_s)} s boost
      </p>)}
    </details>
    <p>2026 base dry limits · 4 MJ usable window · 350 kW maximum.
      Event-specific Overtake authorization is unavailable; all profiles use the standard power curve.
      Synthetic strategy and vehicle efficiencies.</p>
  </section>;
}
