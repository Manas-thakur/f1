import type { Quality } from '@contracts';

import { QUALITY_TEXT } from '../contracts/units';
import styles from './primitives.module.css';

export interface QualityIndicatorProps {
  /** Null means the quality is genuinely unknown. It is shown as text. */
  readonly quality: Quality | null | undefined;
  readonly label?: string;
  readonly detail?: string | null;
}

/**
 * Freshness/validity of a value.
 *
 * Unknown quality renders the word "unknown", never an empty green check: an
 * absent assessment is not a passing assessment. The mark is decorative; the
 * text carries the meaning, so the state survives without colour.
 */
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
