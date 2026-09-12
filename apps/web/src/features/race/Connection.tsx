'use client';

import Link from 'next/link';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import type { CircuitMap, Message, RaceFrame } from './types';
import styles from './race.module.css';

interface RaceConnection {
  frame: RaceFrame | null;
  circuits: Omit<CircuitMap, 'points'>[];
  connected: boolean;
  selected: string;
  select: (id: string) => void;
  send: (operation: string, payload?: Record<string, unknown>) => void;
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

export function RaceConnectionProvider({ children }: { readonly children: ReactNode }) {
  const [frame, setFrame] = useState<RaceFrame | null>(null);
  const [circuits, setCircuits] = useState<Omit<CircuitMap, 'points'>[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, select] = useState('car-01');
  const [history, setHistory] = useState<RaceFrame[]>([]);
  const socket = useRef<WebSocket | null>(null);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    function connect() {
      const url = new URL('/race/socket', window.location.href);
      url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url);
      socket.current = ws;
      ws.onopen = () => {
        setConnected(true);
        setError(null);
      };
      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const message = JSON.parse(event.data) as Message;
          if (message.type === 'catalogue') {
            setCircuits(message.circuits);
          }
          if (message.type === 'frame') {
            setFrame(message);
            setHistory((old) => {
              const previous = old.at(-1);
              const kept = previous?.generation === message.generation ? old : [];
              return [...kept.slice(-199), message];
            });
          }
          if (message.type === 'error') {
            setError(message.message);
          }
        } catch {
          setError('Invalid simulator message. Reconnect to the runtime.');
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!disposed) {
          timer = setTimeout(connect, 1500);
        }
      };
    }
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket.current?.close();
    };
  }, []);
  const send = useCallback((operation: string, payload: Record<string, unknown> = {}) => {
    if (socket.current?.readyState !== WebSocket.OPEN) {
      setError('Simulator disconnected. Start make race-server.');
      return;
    }
    setError(null);
    socket.current.send(JSON.stringify({ id: crypto.randomUUID(), operation, ...payload }));
  }, []);
  return (
    <Context.Provider value={{ frame, circuits, connected, selected, select, send, history }}>
      <div className={styles.root}>
        <header className={styles.header}>
          <Link className={styles.brand} href="/race">
            AFTERLAP<span>RACE LAB</span>
          </Link>
          <nav aria-label="Race navigation">
            <Link href="/race">Circuit view</Link>
            <Link href="/race/control">Race control</Link>
          </nav>
          <span className={styles.connection}>{connected ? '● CONNECTED' : '○ DISCONNECTED'}</span>
        </header>
        <div className={styles.notice}>
          SIMULATION ONLY · Scaled circuit artwork · Uncalibrated vehicle physics
        </div>
        {!connected && (
          <div role="status" className={styles.alert}>
            Waiting for the race runtime. Run make race.
          </div>
        )}
        {error && (
          <div role="alert" className={styles.alert}>
            {error}
          </div>
        )}
        {frame?.failure && (
          <div role="alert" className={styles.alert}>
            {frame.failure}
          </div>
        )}
        {children}
      </div>
    </Context.Provider>
  );
}
