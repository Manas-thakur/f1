'use client';

import { Dashboard } from './Dashboard';
import { TelemetryStage } from './Stage';
import styles from './telemetry.module.css';

export function TelemetryScreen({ carId }: { readonly carId: string }) {
  return (
    <div className={styles.screen}>
      <TelemetryStage scale="fit" label={`Live telemetry for ${carId}`}>
        <Dashboard carId={carId} />
      </TelemetryStage>
    </div>
  );
}
