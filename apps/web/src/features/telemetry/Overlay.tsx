'use client';

import { Dashboard } from './Dashboard';
import { TelemetryStage } from './Stage';
import styles from './telemetry.module.css';

export function TelemetryOverlay({ carId, visible, scale = 0.45 }: {
  readonly carId: string;
  readonly visible: boolean;
  readonly scale?: number;
}) {
  return (
    <div className={styles.overlay} hidden={!visible}>
      <TelemetryStage scale={scale} label={`Live telemetry for ${carId}`}>
        <Dashboard carId={carId} controls={false} />
      </TelemetryStage>
    </div>
  );
}
