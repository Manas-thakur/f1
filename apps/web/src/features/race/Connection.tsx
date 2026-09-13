'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import type { CircuitSummary, Message, RaceFrame } from './types';
import styles from './race.module.css';

interface RaceConnection {
  frame: RaceFrame | null;
  circuits: CircuitSummary[];
  connected: boolean;
  socketUrl: string;
  error: string | null;
  selected: string;
  select: (id: string) => void;
  send: (operation: string, payload?: Record<string, unknown>) => void;
  boost: () => Promise<boolean>;
  history: RaceFrame[];
}

const Context = createContext<RaceConnection | null>(null);

export function useRace() {
  const context = useContext(Context);
  if (!context) {
    throw new Error('Race provider is missing');
  }
  return context;
}

export function useRaceToggleShortcut(enabled = true) {
  const { frame, connected, send } = useRace();
  const status = frame?.status;
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (!enabled || event.code !== 'Space' || event.repeat || event.altKey
        || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }
      if (event.target instanceof HTMLElement
        && event.target.closest('input, select, textarea, button, a, [contenteditable="true"]')) {
        return;
      }
      if (!connected || !status || ['finished', 'failed', 'truncated'].includes(status)) {
        return;
      }
      event.preventDefault();
      send(status === 'running' ? 'pause' : 'start');
    };
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  }, [connected, enabled, send, status]);
}

export function RaceConnectionProvider({ children }: { readonly children: ReactNode }) {
  const [frame, setFrame] = useState<RaceFrame | null>(null);
  const [circuits, setCircuits] = useState<CircuitSummary[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState('car-01');
  const desiredSelection = useRef<string | null>(null);
  const selectionRequest = useRef<Promise<boolean>>(Promise.resolve(true));
  const [history, setHistory] = useState<RaceFrame[]>([]);
  const worker = useRef<Worker | null>(null);
  const [socketUrl, setSocketUrl] = useState('');
  useEffect(() => {
    const connection = new Worker(new URL('./race.worker.ts', import.meta.url));
    worker.current = connection;
    let timer: ReturnType<typeof setTimeout>;
    connection.onmessage = (event: MessageEvent<
      Message | { type: 'snapshot'; frame: RaceFrame | null }
      | { type: 'connection'; connected: boolean; url: string }
    >) => {
      const message = event.data;
      if (message.type === 'connection') {
        setConnected(message.connected);
        setSocketUrl(message.url);
        if (message.connected) {
          setError(null);
        }
      } else if (message.type === 'catalogue') {
        setCircuits(message.circuits);
      } else if (message.type === 'snapshot') {
        const snapshot = message.frame;
        if (snapshot) {
          setFrame(snapshot);
          setSelected(() => {
            const desired = desiredSelection.current;
            if (desired && snapshot.cars.some((car) => car.id === desired)) {
              if (snapshot.selected_car_id === desired) {
                desiredSelection.current = null;
              }
              return desired;
            }
            desiredSelection.current = null;
            return snapshot.cars.some((car) => car.id === snapshot.selected_car_id)
              ? snapshot.selected_car_id : snapshot.cars[0]?.id ?? 'car-01';
          });
          setHistory((old) => {
            const kept = old.at(-1)?.generation === snapshot.generation ? old : [];
            return [...kept.slice(-199), snapshot];
          });
        }
        timer = setTimeout(() => connection.postMessage({ type: 'poll' }), 50);
      } else if (message.type === 'error') {
        setError(message.message);
      }
    };
    connection.onerror = () => {
      setConnected(false);
      setError('The simulator connection could not load. Reload the page to reconnect.');
    };
    connection.postMessage({ type: 'poll' });
    return () => {
      clearTimeout(timer);
      connection.postMessage({ type: 'stop' });
      connection.terminate();
      worker.current = null;
    };
  }, []);
  const send = useCallback((operation: string, payload: Record<string, unknown> = {}) => {
    setError(null);
    worker.current?.postMessage({
      type: 'command', payload: { id: crypto.randomUUID(), operation, ...payload },
    });
  }, []);
  const select = useCallback((carId: string) => {
    setError(null);
    setSelected(carId);
    desiredSelection.current = carId;
    const request = selectionRequest.current.then(async () => {
      try {
        const response = await fetch(`/race/selection/${encodeURIComponent(carId)}`, {
          method: 'POST',
        });
        const payload = await response.json() as { error?: string };
        if (!response.ok) {
          setError(payload.error ?? 'The car selection was rejected.');
          return false;
        }
        return true;
      } catch {
        setError('The car selection could not reach the race runtime.');
        return false;
      }
    });
    selectionRequest.current = request;
    void request.then((accepted) => {
      if (!accepted && desiredSelection.current === carId) {
        desiredSelection.current = null;
      }
    });
  }, []);
  const boost = useCallback(async () => {
    setError(null);
    if (!await selectionRequest.current) {
      return false;
    }
    try {
      const response = await fetch('/race/boost', { method: 'POST' });
      const payload = await response.json() as { error?: string };
      if (!response.ok) {
        setError(payload.error ?? 'The boost request was rejected.');
        return false;
      }
      return true;
    } catch {
      setError('The boost request could not reach the race runtime.');
      return false;
    }
  }, []);
  return (
    <Context.Provider value={{
      frame, circuits, connected, socketUrl, error, selected, select, send, boost, history,
    }}>
      <div className={styles.root}>
        {children}
      </div>
    </Context.Provider>
  );
}
