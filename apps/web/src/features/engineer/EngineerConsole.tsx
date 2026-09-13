'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { SiteNav } from '../nav/SiteNav';
import { useRace } from '../race/Connection';
import type { RaceWorld } from '../race/RaceWorld';
import type { CircuitMap, RaceCar, RaceFrame } from '../race/types';
import styles from './engineer.module.css';

const CAMERAS: { label: string; location: string; progress: number; side: -1 | 1 }[] = [
  { label: 'Start approach', location: 'Trackside 01', progress: 0.02, side: -1 },
  { label: 'Sector one', location: 'Trackside 02', progress: 0.18, side: 1 },
  { label: 'High-speed entry', location: 'Trackside 03', progress: 0.35, side: -1 },
  { label: 'Midfield exit', location: 'Trackside 04', progress: 0.52, side: 1 },
  { label: 'Sector three', location: 'Trackside 05', progress: 0.69, side: -1 },
  { label: 'Final approach', location: 'Trackside 06', progress: 0.86, side: 1 },
];

const MOCK_PREDICTIONS = [
  { time: '+03s', title: 'Overtake window', detail: 'Close to <0.7 s before the braking zone', tone: 'attack' },
  { time: '+12s', title: 'Harvest window', detail: 'Lift 18 m earlier; protect the next deployment', tone: 'recover' },
  { time: '+34s', title: 'Traffic exposure', detail: 'Rejoin risk increases if the stop is extended', tone: 'watch' },
];

const MOCK_DECISIONS = [
  { time: '+03s', action: 'Overtake deployment', response: 'ACKNOWLEDGED', status: 'acted' },
  { time: '+12s', action: 'Harvest window', response: 'NOT ACTED', status: 'missed' },
  { time: '+34s', action: 'Hold pit window', response: 'AWAITING', status: 'pending' },
];

function available(value: number | undefined, digits = 1) {
  return value === undefined || !Number.isFinite(value) ? 'Unavailable' : value.toFixed(digits);
}

function currentLap(car: RaceCar | undefined, total: number | undefined) {
  if (!car || total === undefined) {
    return '—';
  }
  if (car.finish_time_s !== null) {
    return String(total);
  }
  const completed = car.channels['lap'];
  return completed === undefined ? '—' : String(Math.min(total, Math.floor(completed) + 1));
}

function CameraWall({ frame, selected }: { frame: RaceFrame | null; selected: string }) {
  const hosts = useRef<(HTMLDivElement | null)[]>([]);
  const worlds = useRef<RaceWorld[]>([]);
  const latest = useRef({ frame, selected });
  const [failed, setFailed] = useState<boolean[]>([]);
  latest.current = { frame, selected };
  const mapId = frame?.circuit_map.id;

  useEffect(() => {
    const map = latest.current.frame?.circuit_map;
    if (!map) {
      return;
    }
    let cancelled = false;
    setFailed([]);
    void import('../race/RaceWorld').then(({ RaceWorld }) => {
      if (cancelled) {
        return;
      }
      CAMERAS.forEach((camera, index) => {
        const host = hosts.current[index];
        if (!host) {
          return;
        }
        try {
          const world = new RaceWorld(host, map, () => undefined, () => undefined,
            () => setFailed((old) => CAMERAS.map((_, item) => item === index || Boolean(old[item]))),
            () => undefined);
          worlds.current.push(world);
          world.setQuality('performance');
          if (latest.current.frame) {
            world.update(latest.current.frame, latest.current.selected);
          }
          world.setTrackside(camera.progress, camera.side);
        } catch {
          setFailed((old) => CAMERAS.map((_, item) => item === index || Boolean(old[item])));
        }
      });
    }).catch(() => setFailed(CAMERAS.map(() => true)));
    return () => {
      cancelled = true;
      worlds.current.forEach((world) => world.dispose());
      worlds.current = [];
    };
  }, [mapId]);

  useEffect(() => {
    if (!frame) {
      return;
    }
    worlds.current.forEach((world) => {
      world.update(frame, selected);
    });
  }, [frame, selected]);

  return <section className={styles.cameraWall} aria-label="Live camera wall">
    {CAMERAS.map((camera, index) => <figure className={styles.camera} key={camera.location}>
      <div className={styles.cameraViewport} ref={(node) => { hosts.current[index] = node; }}
        role="img" aria-label={`${camera.location} ${camera.label} camera`} />
      {failed[index] && <div className={styles.cameraFallback}>FEED UNAVAILABLE</div>}
      <figcaption>
        <span><i /> LIVE · {camera.location}</span>
        <strong>{camera.label}</strong>
        <small>CAM {String(index + 1).padStart(2, '0')}</small>
      </figcaption>
    </figure>)}
  </section>;
}

function normalizedMap(map: CircuitMap | undefined) {
  if (!map?.points.length) {
    return { path: '', positions: [] as [number, number][] };
  }
  const xs = map.points.map(([x]) => x);
  const ys = map.points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const scale = Math.min(270 / spanX, 178 / spanY);
  const width = spanX * scale;
  const height = spanY * scale;
  const offsetX = (320 - width) / 2;
  const offsetY = (220 - height) / 2;
  const positions = map.points.map(([x, y]) => [
    offsetX + (x - minX) * scale,
    offsetY + (y - minY) * scale,
  ] as [number, number]);
  const path = positions
    .map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ');
  return { path: `${path} Z`, positions };
}

function carPosition(
  map: CircuitMap | undefined,
  positions: [number, number][],
  progress: number | undefined,
) {
  if (!map || !positions.length || progress === undefined) {
    return undefined;
  }
  const lapProgress = ((progress % map.length_m) + map.length_m) % map.length_m;
  const segments = map.points.map(([x, y], index) => {
    const nextPoint = map.points[(index + 1) % map.points.length];
    return nextPoint ? Math.hypot(nextPoint[0] - x, nextPoint[1] - y) : 0;
  });
  const geometryLength = segments.reduce((total, segment) => total + segment, 0);
  const target = lapProgress / map.length_m * geometryLength;
  let covered = 0;
  let index = 0;
  while (index < segments.length - 1 && covered + (segments[index] ?? 0) < target) {
    covered += segments[index] ?? 0;
    index++;
  }
  const point = positions[index];
  const nextPoint = positions[(index + 1) % positions.length];
  const segment = segments[index] ?? 0;
  if (!point || !nextPoint || segment <= 0) {
    return undefined;
  }
  const mix = Math.min(1, Math.max(0, (target - covered) / segment));
  return [
    point[0] + (nextPoint[0] - point[0]) * mix,
    point[1] + (nextPoint[1] - point[1]) * mix,
  ];
}

function CircuitTracker({ frame, selected }: { frame: RaceFrame | null; selected: string }) {
  const geometry = useMemo(() => normalizedMap(frame?.circuit_map), [frame?.circuit_map]);
  return <section className={`${styles.module} ${styles.trackModule}`} aria-label="Circuit tracker">
    <div className={styles.moduleHead}>
      <div><span>07 / CIRCUIT</span><h2>{frame?.circuit_map.name ?? 'Waiting for circuit'}</h2></div>
      <strong>{frame?.settings.laps ?? '—'} LAPS</strong>
    </div>
    <div className={styles.trackStage}>
      {geometry.path ? <svg viewBox="0 0 320 220" role="img" aria-label="Live circuit position map">
        <path className={styles.trackShadow} d={geometry.path} />
        <path className={styles.trackLine} d={geometry.path} />
        {frame?.cars.map((car, index) => {
          const position = carPosition(frame.circuit_map, geometry.positions, car.channels['s_m']);
          return position && <g key={car.id} transform={`translate(${position[0]} ${position[1]})`}>
            <circle className={selected === car.id ? styles.selectedCar : styles.rivalCar}
              r={selected === car.id ? 6 : 3.5} />
            {selected === car.id && <text x="9" y="4">{car.id.toUpperCase()}</text>}
            {index === 0 && <circle className={styles.leaderHalo} r="10" />}
          </g>;
        })}
      </svg> : <div className={styles.empty}>Awaiting live geometry</div>}
    </div>
    <div className={styles.trackFooter}>
      <span><i className={styles.youDot} /> Selected</span>
      <span><i className={styles.fieldDot} /> Field</span>
      <span>{frame?.circuit_map.length_m
        ? `${(frame.circuit_map.length_m / 1000).toFixed(3)} KM`
        : 'Length unavailable'}</span>
    </div>
  </section>;
}

function EnergyGraph({ frame, selected }: { frame: RaceFrame | null; selected: string }) {
  const car = frame?.cars.find((item) => item.id === selected);
  const recorded = car?.energy_laps ?? [];
  const currentLapIndex = Number(currentLap(car, frame?.settings.laps));
  const deployed = car?.channels['deployed_this_lap_j'];
  const recharged = car?.channels['recharge_this_lap_j'];
  const current = Number.isFinite(currentLapIndex)
    && deployed !== undefined && recharged !== undefined ? [{
    lap: currentLapIndex,
    deployed_j: deployed,
    recharged_j: recharged,
    boost_s: car?.channels['boost_this_lap_s'] ?? 0,
  }] : [];
  const data = [...recorded.slice(-8), ...current].slice(-9);
  const max = Math.max(1, ...data.flatMap((lap) => [lap.deployed_j, lap.recharged_j]));
  return <section className={`${styles.module} ${styles.energyModule}`} aria-label="Energy deployment by lap">
    <div className={styles.moduleHead}>
      <div><span>03 / ENERGY TRACE</span><h2>Deployment by lap</h2></div>
      <div className={styles.energyLegend}><span>Deploy</span><span>Recover</span></div>
    </div>
    {data.length ? <div className={styles.chart} role="img"
      aria-label="Observed deployed and recovered energy by lap">
      <div className={styles.axisLabel}>MJ</div>
      <div className={styles.yTicks}>
        <span>{(max / 1e6).toFixed(1)}</span><span>{(max / 2e6).toFixed(1)}</span><span>0</span>
      </div>
      <div className={styles.bars}>
        {data.map((lap, index) => <div className={styles.barGroup} key={`${lap.lap}-${index}`}>
          <div className={styles.barPair}>
            <i className={styles.deployBar}
              style={{ height: `${Math.max(2, lap.deployed_j / max * 100)}%` }} />
            <i className={styles.recoverBar}
              style={{ height: `${Math.max(2, lap.recharged_j / max * 100)}%` }} />
          </div>
          <span>L{lap.lap}</span>
        </div>)}
      </div>
    </div> : <div className={styles.empty}>
      Energy measurements unavailable until the first observed frame
    </div>}
    <div className={styles.energyReadouts}>
      <div><span>DEPLOY THIS LAP</span><strong>
        {available(deployed === undefined ? undefined : deployed / 1e6, 2)} <small>MJ</small>
      </strong></div>
      <div><span>RECOVERED</span><strong>
        {available(recharged === undefined ? undefined : recharged / 1e6, 2)} <small>MJ</small>
      </strong></div>
      <div><span>ACTIVE PROFILE</span>
        <strong>{car?.active_profile?.toUpperCase() ?? 'UNAVAILABLE'}</strong></div>
    </div>
  </section>;
}

function Predictions() {
  return <section className={`${styles.module} ${styles.predictionModule}`} aria-label="Model predictions">
    <div className={styles.moduleHead}>
      <div><span>06 / FORESIGHT</span><h2>Prediction queue</h2></div>
      <b className={styles.mockBadge}>SCENARIO MOCK</b>
    </div>
    <div className={styles.nextCall}>
      <span>NEXT CALL</span><strong>PREPARE OVERTAKE</strong>
      <p>Deployment at corner exit, subject to driver confirmation.</p>
    </div>
    <ol className={styles.predictionList}>
      {MOCK_PREDICTIONS.map((prediction) => <li key={prediction.time} data-tone={prediction.tone}>
        <time>{prediction.time}</time><div><strong>{prediction.title}</strong><p>{prediction.detail}</p></div>
      </li>)}
    </ol>
    <div className={styles.mockNotice}>Placeholder recommendations only · no trained model connected</div>
  </section>;
}

function DecisionLedger({ car }: { car: RaceCar | undefined }) {
  const delivered = car?.active_profile?.toUpperCase();
  return <section className={`${styles.module} ${styles.decisionModule}`} aria-label="Decision execution">
    <div className={styles.moduleHead}>
      <div><span>08 / EXECUTION</span><h2>Decision response</h2></div>
      <b className={styles.mockBadge}>MOCK</b>
    </div>
    <div className={styles.decisionState}><span>LIVE PROFILE</span>
      <strong>{delivered ?? 'UNAVAILABLE'}</strong></div>
    <ol className={styles.decisionList}>
      {MOCK_DECISIONS.map((decision) => <li key={decision.time} data-status={decision.status}>
        <time>{decision.time}</time>
        <div><strong>{decision.action}</strong><small>Engineer recommendation</small></div>
        <em>{decision.response}</em>
      </li>)}
    </ol>
  </section>;
}

function Validation({ frame }: { frame: RaceFrame | null }) {
  const counts = frame?.boost_evaluation;
  const latestPass = [...(frame?.events ?? [])]
    .reverse().find((event) => event.kind === 'completed_pass');
  const outcomes = [
    { label: 'TRUE', detail: 'Opportunity present · boost used', value: counts?.true_positive },
    { label: 'FALSE', detail: 'No opportunity · boost used', value: counts?.false_positive },
    { label: 'MISSED', detail: 'Opportunity present · no boost', value: counts?.false_negative },
    { label: 'CLEAR', detail: 'No opportunity · no boost', value: counts?.true_negative },
  ];
  return <section className={`${styles.module} ${styles.validationModule}`} aria-label="Prediction validation">
    <div className={styles.moduleHead}>
      <div><span>09 / VALIDATION</span><h2>Energy attribution</h2></div>
    </div>
    <div className={styles.outcomeList}>
      {outcomes.map((outcome) => <article key={outcome.label}
        data-outcome={outcome.label.toLowerCase()}>
        <strong>{outcome.label}</strong>
        <span>{outcome.detail}</span>
        <b>{outcome.value ?? '—'}</b>
      </article>)}
    </div>
    <div className={styles.lastEvent}>{latestPass
      ? `${latestPass.overtaking_car_id?.toUpperCase()} passed ${latestPass.overtaken_car_id?.toUpperCase()}`
        + ` · ${latestPass.session_time_s.toFixed(1)}s`
      : 'No completed pass observed'}</div>
  </section>;
}

export function EngineerConsole() {
  const { frame, connected, socketUrl, selected, select, send, error } = useRace();
  const car = frame?.cars.find((item) => item.id === selected);
  const speed = car?.channels['speed_mps'];
  return <main className={styles.console}>
    <SiteNav>
      <div className={styles.sessionMeta}>
        <span>{frame?.circuit_map.name?.toUpperCase() ?? 'SESSION INITIALISING'}</span>
        <strong>LAP {currentLap(car, frame?.settings.laps)} <i>/</i>{' '}
          {frame?.settings.laps ?? '—'}</strong>
      </div>
      <label className={styles.carSelect}>FOCUS CAR
        <select value={selected} onChange={(event) => select(event.target.value)} aria-label="Focus car">
          {frame?.cars.map((item) => <option key={item.id} value={item.id}>
            {item.id.toUpperCase()}
          </option>)}
        </select>
      </label>
      <div className={styles.quickReadout}><span>SPEED</span><strong>
        {available(speed === undefined ? undefined : speed * 3.6, 0)} <small>KM/H</small>
      </strong></div>
      <div className={styles.quickReadout}><span>SESSION</span><strong>
        {available(frame?.time_s, 1)} <small>S</small>
      </strong></div>
      <div className={styles.connectionState} data-connected={connected} data-socket-url={socketUrl}>
        <i /> <div><span>DATA LINK</span><strong>{connected ? 'LIVE' : 'OFFLINE'}</strong></div>
      </div>
      <button className={styles.transportButton} type="button" disabled={!connected}
        onClick={() => send(frame?.status === 'running' ? 'pause' : 'start')}>
        {frame?.status === 'running' ? 'PAUSE' : 'START'}
      </button>
    </SiteNav>
    {(error ?? frame?.failure) && <div className={styles.alert} role="status">
      {error ?? frame?.failure}
    </div>}
    <div className={styles.workspace}>
      <CameraWall frame={frame} selected={selected} />
      <Predictions />
      <CircuitTracker frame={frame} selected={selected} />
      <EnergyGraph frame={frame} selected={selected} />
      <DecisionLedger car={car} />
      <Validation frame={frame} />
    </div>
  </main>;
}
