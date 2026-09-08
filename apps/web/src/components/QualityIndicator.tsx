import type { Quality } from '@contracts';

import { QUALITY_TEXT } from '../contracts/units';
import styles from './primitives.module.css';

export interface QualityIndicatorProps {
  
  readonly quality: Quality | null | undefined;
  readonly label?: string;
  readonly detail?: string | null;
}


export function QualityIndicator({ quality, label, detail }: QualityIndicatorProps) {
  const key = quality ?? 'unknown';
  const text = quality === null || quality === undefined ? 'unknown' : QUALITY_TEXT[quality];
  return (
    <span className={styles.quality} data-quality={key}>
      <span className={styles.qualityMark} aria-hidden="true" />
      <span className={styles.qualityText}>
        {label === undefined ? null : <span className="afterlap-muted">{label} </span>}
        {text}
        {detail ? <span className="afterlap-muted"> — {detail}</span> : null}
      </span>
    </span>
  );
}
