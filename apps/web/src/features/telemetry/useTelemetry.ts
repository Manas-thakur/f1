'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { useRace } from '../race/Connection';
import { LapTimer, emptyLapReading } from './lapTiming';
import type { LapReading } from './lapTiming';
import { flagState, readout } from './readouts';
import type { CarReadout, FlagReadout } from './readouts';
import type { RaceFrame } from '../race/types';

export interface TelemetrySnapshot {
  frame: RaceFrame | null;
  connected: boolean;
  car: CarReadout;
  timing: LapReading;
  flag: FlagReadout;
  send: (operation: string, payload?: Record<string, unknown>) => void;
  boost: (carId: string) => Promise<boolean>;
}

export function useTelemetry(carId: string): TelemetrySnapshot {
  const { frame, connected, send, boost } = useRace();
  const timer = useRef<LapTimer | null>(null);
  timer.current ??= new LapTimer();
  const [timing, setTiming] = useState<LapReading>(emptyLapReading);
  useEffect(() => {
    const current = timer.current;
    if (frame && current) {
      setTiming(current.push(frame, carId));
    }
  }, [frame, carId]);
  const car = useMemo(() => readout(frame, carId), [frame, carId]);
  const flag = useMemo(() => flagState(frame, car, connected), [frame, car, connected]);
  return { frame, connected, car, timing, flag, send, boost };
}
