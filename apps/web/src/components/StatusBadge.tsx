import type { ReactNode } from 'react';

import styles from './primitives.module.css';

/**
 * Badge tones are a closed set. There are no arbitrary status colours: every
 * tone below answers selection, verification or a failure. `neutral` is used
 * for fixture and proposed states, which assert nothing.
 */
export type BadgeTone =
  | 'neutral'
  | 'selection'
  | 'verified'
  | 'failure'
  | 'attention'
  | 'reference';

export interface StatusBadgeProps {
  readonly tone?: BadgeTone;
  /** Screen-reader prefix, e.g. "Recommendation status". */
  readonly label?: string;
  readonly title?: string;
  readonly children: ReactNode;
}

export function StatusBadge({ tone = 'neutral', label, title, children }: StatusBadgeProps) {
  return (
    <span className={styles.badge} data-tone={tone} title={title}>
      {label ? <span className="afterlap-visually-hidden">{label}: </span> : null}
      {children}
    </span>
  );
}

/**
 * Recommendation lifecycle -> badge tone.
 *
 * `proposed` is deliberately neutral: a proposal is not an achievement, and a
 * healthy fixture feed is not compliance.
 */
export function recommendationTone(status: string): BadgeTone {
  switch (status) {
    case 'selected':
    case 'communicated':
    case 'executing':
      return 'selection';
    case 'completed':
      return 'verified';
    case 'rejected':
    case 'expired':
    case 'invalidated':
      return 'failure';
    default:
      return 'neutral';
  }
}

/** Rule/constraint check status -> badge tone. `unknown` stays text. */
export function checkTone(status: 'pass' | 'fail' | 'unknown'): BadgeTone {
  if (status === 'pass') return 'verified';
  if (status === 'fail') return 'failure';
  return 'neutral';
}
