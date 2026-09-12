'use client';

import { useEffect, useRef, useState } from 'react';

import { BatteryHud } from './Energy';
import { rankedCar } from './motion';
import { Classification, Transport } from './RacePanels';
import { ControlDrawer } from './ControlDrawer';
import { TelemetryOverlay } from '../telemetry/Overlay';
import { useRace } from './Connection';
import type { CameraMode, RaceWorld } from './RaceWorld';
import styles from './race.module.css';

const CAMERAS: { id: CameraMode; label: string; key: string }[] = [
  { id: 'chase', label: 'Chase', key: '1' },
  { id: 'cockpit', label: 'First person', key: '2' },
  { id: 'orbit', label: 'Car orbit', key: '3' },
  { id: 'track', label: 'Full circuit', key: '4' },
];

export function Circuit() {
  const { frame, selected, select, connected, socketUrl, error: connectionError } = useRace();
  const [settings, setSettings] = useState(false);
  const [dockWidth, setDockWidth] = useState(0);
  const [classification, setClassification] = useState(true);
  const [fps, setFps] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const minimapCanvas = useRef<HTMLCanvasElement>(null);
  const [showMap, setShowMap] = useState(true);
  const [showTelemetry, setShowTelemetry] = useState(true);
  const panel = useRef<HTMLElement>(null);
  const world = useRef<RaceWorld | null>(null);
  const latest = useRef({ frame, selected, select });
  latest.current = { frame, selected, select };
  const [mode, setMode] = useState<CameraMode>('chase');
  const [highQuality, setHighQuality] = useState(true);
  const [help, setHelp] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const mapId = frame?.circuit_map.id;

  useEffect(() => {
    const element = toolbar.current;
    if (!element) {
      return;
    }
    const resize = new ResizeObserver(() => {
      element.parentElement?.style.setProperty('--toolbar-bottom', `${element.offsetTop + element.offsetHeight + 16}px`);
    });
    resize.observe(element);
    return () => resize.disconnect();
  }, []);

  useEffect(() => {
    const element = host.current;
    const map = latest.current.frame?.circuit_map;
    if (!element || !map) {
      return;
    }
    let cancelled = false;
    setReady(false);
    setError('');
    void import('./RaceWorld').then(({ RaceWorld }) => {
      if (cancelled) {
        return;
      }
      try {
        const scene = new RaceWorld(element, map, setMode,
          (id) => latest.current.select(id), setError, setFps);
        world.current = scene;
        scene.setMinimap(minimapCanvas.current);
        setHighQuality(scene.highQuality);
        if (latest.current.frame) {
          scene.update(latest.current.frame, latest.current.selected);
        }
        scene.setMode('chase');
        setReady(true);
      } catch {
        setError('3D rendering is unavailable. Enable hardware acceleration or try another browser.');
      }
    }).catch(() => {
      if (!cancelled) {
        setError('The 3D view could not load. Check your connection and try again.');
      }
    });
    return () => {
      cancelled = true;
      world.current?.dispose();
      world.current = null;
    };
  }, [mapId, attempt]);

  useEffect(() => {
    if (frame) {
      world.current?.update(frame, selected);
    }
  }, [frame, selected]);

  useEffect(() => {
    world.current?.setMinimap(showMap ? minimapCanvas.current : null);
  }, [showMap, ready]);

  const switchCar = (direction: -1 | 1) => {
    const current = latest.current;
    current.select(rankedCar(current.frame?.cars.map((item) => item.id) ?? [], current.selected, direction));
  };

  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement
        && event.target.closest('input, select, textarea, [contenteditable="true"]')) {
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        event.preventDefault();
        switchCar(event.key === 'ArrowUp' ? -1 : 1);
      } else if (event.key.toLowerCase() === 'm') {
        setShowMap((visible) => !visible);
      } else if (event.key.toLowerCase() === 't') {
        setShowTelemetry((visible) => !visible);
      }
    };
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  }, []);

  const fullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await panel.current?.requestFullscreen();
      }
    } catch {
      setError('Fullscreen is unavailable in this browser. The scene controls still work.');
    }
  };
  const car = frame?.cars.find((item) => item.id === selected);
  const speed = car?.channels['speed_mps'];
  return (
    <section ref={panel} className={styles.mapPanel} aria-label="Live circuit">
      <div className={styles.sceneWrap} style={{ width: `calc(100% - ${dockWidth}px)` }}>
      <div ref={toolbar} className={styles.mapTools}>
        <button type="button" aria-label="Race controls" aria-expanded={settings} onClick={() => setSettings(!settings)}>☰</button>
        <span className={styles.circuitName}>{frame?.circuit_map.name.toUpperCase() ?? 'CONNECTING'}</span>
        <span className={styles.connection} data-socket-url={socketUrl}>{connected ? '● CONNECTED' : '○ DISCONNECTED'}</span>
        <div className={styles.cameraTabs} role="group" aria-label="Camera view">
          {CAMERAS.map((camera) => (
            <button key={camera.id} type="button" aria-pressed={mode === camera.id}
              disabled={!ready} onClick={() => world.current?.setMode(camera.id)}>
              {camera.label}
            </button>
          ))}
        </div>
        <select aria-label="Graphics quality" value={highQuality ? 'high' : 'performance'}
          onChange={(event) => {
            const high = event.target.value === 'high';
            setHighQuality(high);
            world.current?.setQuality(high);
          }}>
          <option value="high">High graphics</option>
          <option value="performance">Performance</option>
        </select>
        <button type="button" onClick={() => void fullscreen()}>Fullscreen</button>
        <Transport />
      </div>
        {/* eslint-disable-next-line
          jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex
        */}
        <div ref={host} className={styles.scene} tabIndex={0} role="application"
          aria-label="3D camera controls" aria-describedby="camera-instructions"
          data-camera-mode={mode}
          onKeyDown={(event) => {
            const camera = CAMERAS.find((item) => item.key === event.key);
            if (camera) {
              event.preventDefault();
              world.current?.setMode(camera.id);
            } else if (['+', '=', '-', '_'].includes(event.key)) {
              event.preventDefault();
              world.current?.zoom(['-', '_'].includes(event.key) ? 1.2 : 1 / 1.2);
            } else if (event.key.toLowerCase() === 'f') {
              event.preventDefault();
              world.current?.setMode('track');
            } else if (event.key === 'Escape') {
              setHelp(false);
            }
          }} />
        {!ready && !error && (
          <div className={styles.sceneMessage}>Loading the circuit world…</div>
        )}
        {error && <div className={styles.sceneMessage} role="alert">
          <p>{error}</p><button type="button" onClick={() => setAttempt(attempt + 1)}>Reload 3D view</button>
        </div>}
        <div className={styles.sceneBadge}>
          <span>{frame?.status === 'running' ? `${fps} FPS` : 'RENDER ON DEMAND'}
            {' · '}{mode === 'cockpit' ? 'FIRST PERSON' : mode.toUpperCase()}</span>
          <span>PACE {frame?.playback_rate?.toFixed(2) ?? '…'}× · TARGET {frame?.requested_rate ?? 1}×</span>
          <span>{frame?.settings.weather === 'rainy' ? '☂ RAIN' : '☀ SUN'}</span>
        </div>
        {car && car.tyres.phase !== 'track' && <div className={styles.pitOverlay} role="status">
          <small>PIT LANE · {car?.tyres.phase.toUpperCase()}</small>
          <strong>{car?.tyres.phase === 'service'
            ? `${car.tyres.service_remaining_s.toFixed(1)}s`
            : car?.tyres.phase === 'entry' ? 'BOX THIS LAP' : 'REJOINING'}</strong>
          <span>{car?.tyres.compound.toUpperCase()} → {car?.tyres.phase === 'exit'
            ? car.tyres.compound.toUpperCase() : 'NEW SET'}</span>
        </div>}
        {classification && <Classification />}
        <TelemetryOverlay carId={selected} visible={showTelemetry} />
        {(connectionError ?? frame?.failure ?? !connected) && <div className={styles.connectionAlert} role="status">
          {connectionError ?? frame?.failure ?? 'Connecting to the race runtime…'}
        </div>}
        <div className={styles.sceneActions}>
          <button type="button" aria-label="Zoom in" onClick={() => world.current?.zoom(1 / 1.2)}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => world.current?.zoom(1.2)}>−</button>
          <button type="button" onClick={() => world.current?.setMode('chase')}>Reset view</button>
          <button type="button" aria-pressed={showMap} onClick={() => setShowMap(!showMap)}>Minimap</button>
          <button type="button" aria-pressed={showTelemetry}
            onClick={() => setShowTelemetry(!showTelemetry)}>Telemetry</button>
          <button type="button" aria-pressed={classification} onClick={() => setClassification(!classification)}>Classification</button>
          <button type="button" aria-expanded={help} onClick={() => setHelp(!help)}>Controls</button>
        </div>
        {help && <div className={styles.cameraHelp} id="camera-instructions">
          <strong>Explore the circuit</strong>
          <p>Drag to orbit · Right drag or Shift + drag to pan</p>
          <p>Scroll or pinch to zoom · Two fingers to pan</p>
          <p>Click a car to inspect · Double-click to orbit the selected car</p>
          <p>Focus the scene: 1–4 cameras · + / − zoom (also ⌘ / Ctrl) · F fit circuit</p>
          <p>↑ car ahead · ↓ car behind · Circular race order · M minimap · T telemetry</p>
          <p>Dragging releases chase. Reset view resumes it.</p>
        </div>}
        <div className={styles.minimap} hidden={!showMap}>
          <div><strong>CIRCUIT MAP</strong><span>YOU ▴</span></div>
          <canvas ref={minimapCanvas} width={480} height={300}
            aria-label={`Circuit minimap tracking ${selected}`} role="img" />
          <small>{selected.toUpperCase()} · P{car ? (frame?.cars.indexOf(car) ?? 0) + 1 : '?'}</small>
        </div>
        <div className={styles.followDock}>
          <small>FOLLOWING</small>
          <strong>{selected.toUpperCase()}</strong>
          <div className={styles.carSwitch}>
            <button type="button" aria-label="Watch car ahead" onClick={() => switchCar(-1)}>↑</button>
            <button type="button" aria-label="Watch car behind" onClick={() => switchCar(1)}>↓</button>
          </div>
        </div>
        <div className={styles.worldHud}>
          <div><small>FOLLOWING</small><strong>{selected.toUpperCase()}</strong>
            <span>{car ? `P${(frame?.cars.indexOf(car) ?? 0) + 1}` : 'WAITING'} ·{' '}
              {car?.tyres.phase === 'track' ? frame?.status.toUpperCase() : `PIT ${car?.tyres.phase.toUpperCase()}`}</span>
          </div>
          <div className={styles.hudSpeed}>
            <strong>{speed === undefined ? 'N/A' : (speed * 3.6).toFixed(0)}</strong>
            <small>KM/H</small></div>
          <BatteryHud />
        </div>
      </div>
      <ControlDrawer parent={panel} open={settings} close={() => setSettings(false)} reserve={setDockWidth} />
    </section>
  );
}
