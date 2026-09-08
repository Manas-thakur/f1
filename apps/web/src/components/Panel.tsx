import type { ReactNode } from 'react';

import styles from './primitives.module.css';

export interface PanelProps {
  readonly title?: string;
  readonly headingLevel?: 2 | 3;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly id?: string;
}


export function Panel({ title, headingLevel = 2, actions, children, id }: PanelProps) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  return (
    <section className={styles.panel} id={id} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {title === undefined && actions === undefined ? null : (
        <div className={styles.panelHead}>
          {title === undefined ? <span /> : <Heading id={id ? `${id}-title` : undefined}>{title}</Heading>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export interface NoticeProps {
  readonly tone?: 'info' | 'attention' | 'failure';
  readonly children: ReactNode;
  
  readonly live?: boolean;
  readonly testId?: string;
}

export function Notice({ tone = 'info', children, live = false, testId }: NoticeProps) {
  return (
    <p
      className={styles.notice}
      data-tone={tone}
      data-testid={testId}
      role={live ? 'status' : undefined}
      aria-live={live ? 'polite' : undefined}
    >
      {children}
    </p>
  );
}
