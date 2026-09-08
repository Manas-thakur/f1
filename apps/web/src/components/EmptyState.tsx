import type { ReactNode } from 'react';

import styles from './primitives.module.css';

export interface EmptyStateProps {
  
  readonly artefact: string;
  readonly heading?: string;
  
  readonly reason?: string;
  
  readonly action?: ReactNode;
  readonly children?: ReactNode;
}


export function EmptyState({ artefact, heading, reason, action, children }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <h3>{heading ?? `No ${artefact}`}</h3>
      <p className={styles.emptyArtefact}>missing artefact: {artefact}</p>
      {reason !== undefined ? <p className="afterlap-muted">{reason}</p> : null}
      {children}
      {action}
    </div>
  );
}
