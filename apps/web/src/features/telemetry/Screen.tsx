'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { useRace } from '../race/Connection';
import { Dashboard } from './Dashboard';
import { TelemetryStage } from './Stage';
import styles from './telemetry.module.css';

export function TelemetryScreen({ carId }: { readonly carId: string }) {
  const router = useRouter();
  const { frame } = useRace();
  const [selected, setSelected] = useState(carId);
  const carIds = useMemo(() => frame?.cars.map((car) => car.id) ?? [], [frame?.cars]);
  useEffect(() => {
    setSelected(carId);
  }, [carId]);
  useEffect(() => {
    if (carIds.length > 0 && !carIds.includes(selected)) {
      const next = carIds[0] ?? carId;
      setSelected(next);
      router.replace(`/tel/${encodeURIComponent(next)}`);
    }
  }, [carId, carIds, router, selected]);
  function select(next: string) {
    setSelected(next);
    router.replace(`/tel/${encodeURIComponent(next)}`);
  }
  return (
    <div className={styles.screen}>
      <TelemetryStage scale="fit" label={`Live telemetry for ${selected}`}>
        <Dashboard carId={selected} carIds={carIds} onCarChange={select} />
      </TelemetryStage>
    </div>
  );
}
