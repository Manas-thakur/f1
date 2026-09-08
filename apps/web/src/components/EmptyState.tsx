import type { ReactNode } from 'react';

import styles from './primitives.module.css';

export interface EmptyStateProps {
  /** The specific artefact that is missing, named, not described vaguely. */
  readonly artefact: string;
  readonly heading?: string;
  /** Why it is missing, when that is known. */
  readonly reason?: string;
  /** The action that would create the artefact. A link or a real control. */
  readonly action?: ReactNode;
  readonly children?: ReactNode;
}

/**
 * A useful empty state names the missing artefact and the action that would
 * create it. It never shows a placeholder chart or an encouraging slogan.
 */
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
