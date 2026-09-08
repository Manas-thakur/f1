import type { ReactNode } from 'react';

import styles from './primitives.module.css';


export type BadgeTone =
  | 'neutral'
  | 'selection'
  | 'verified'
  | 'failure'
  | 'attention'
  | 'reference';

export interface StatusBadgeProps {
  readonly tone?: BadgeTone;
  
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


export function checkTone(status: 'pass' | 'fail' | 'unknown'): BadgeTone {
  if (status === 'pass') {return 'verified';}
  if (status === 'fail') {return 'failure';}
  return 'neutral';
}
