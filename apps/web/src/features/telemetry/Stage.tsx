'use client';

import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { STAGE_HEIGHT, STAGE_WIDTH } from './readouts';
import styles from './telemetry.module.css';

export function TelemetryStage({ scale, label, children }: {
  readonly scale: 'fit' | number;
  readonly label: string;
  readonly children: ReactNode;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [fitted, setFitted] = useState(1);
  useEffect(() => {
    const element = host.current;
    if (!element || scale !== 'fit') {
      return;
    }
    const measure = () => {
      const box = element.getBoundingClientRect();
      setFitted(Math.max(0.05, Math.min(box.width / STAGE_WIDTH, box.height / STAGE_HEIGHT)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [scale]);
  const factor = scale === 'fit' ? fitted : scale;
  return (
    <div ref={host} className={styles.stageHost} data-fit={scale === 'fit'} aria-label={label}>
      <div className={styles.stageBox}
        style={{ width: STAGE_WIDTH * factor, height: STAGE_HEIGHT * factor }}>
        <div className={styles.stage} style={{ transform: `scale(${factor})` }}>{children}</div>
      </div>
    </div>
  );
}
