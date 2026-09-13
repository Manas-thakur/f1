'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useRouter } from 'next/navigation';

import { useRace } from '../race/Connection';
import { Dashboard } from './Dashboard';
import { TelemetryStage } from './Stage';
import styles from './telemetry.module.css';

export function TelemetryScreen({ carId }: { readonly carId: string }) {
  const router = useRouter();
  const { frame, selected, select } = useRace();
  const initialized = useRef(false);
  const carIds = useMemo(() => frame?.cars.map((car) => car.id) ?? [], [frame?.cars]);
  useEffect(() => {
    if (carIds.length === 0) {
      return;
    }
    if (!initialized.current) {
      initialized.current = true;
      const initial = carIds.includes(carId) ? carId
        : carIds.includes(selected) ? selected : carIds[0] ?? 'car-01';
      if (initial !== selected) {
        select(initial);
      }
      if (initial !== carId) {
        router.replace(`/tel/${encodeURIComponent(initial)}`);
      }
      return;
    }
    const next = carIds.includes(selected) ? selected : carIds[0] ?? 'car-01';
    if (next !== selected) {
      select(next);
    }
    if (next !== carId) {
      router.replace(`/tel/${encodeURIComponent(next)}`);
    }
  }, [carId, carIds, router, select, selected]);
  function choose(next: string) {
    select(next);
    router.replace(`/tel/${encodeURIComponent(next)}`);
  }
  return (
    <div className={styles.screen}>
      <TelemetryStage scale="fit" label={`Live telemetry for ${selected}`}>
        <Dashboard carId={selected} carIds={carIds} onCarChange={choose} />
      </TelemetryStage>
    </div>
  );
}
