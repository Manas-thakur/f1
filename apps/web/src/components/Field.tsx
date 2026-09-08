import { useId, type ReactElement, cloneElement } from 'react';

import styles from './primitives.module.css';

export type FieldState = 'default' | 'pending' | 'error' | 'success' | 'disabled';

export interface FieldProps {
  readonly label: string;
  readonly hint?: string;
  readonly state?: FieldState;
  readonly errorMessage?: string;
  readonly successMessage?: string;
  readonly required?: boolean;
  
  readonly children: ReactElement<{
    id?: string;
    'aria-describedby'?: string;
    'aria-invalid'?: boolean;
    disabled?: boolean;
  }>;
}


export function Field({
  label,
  hint,
  state = 'default',
  errorMessage,
  successMessage,
  required = false,
  children,
}: FieldProps) {
  const id = useId();
  const controlId = `${id}-control`;
  const hintId = `${id}-hint`;
  const messageId = `${id}-message`;

  const message =
    state === 'error' && errorMessage
      ? { tone: 'error' as const, text: errorMessage }
      : state === 'success' && successMessage
        ? { tone: 'success' as const, text: successMessage }
        : null;

  const describedBy = [hint ? hintId : null, message ? messageId : null]
    .filter(Boolean)
    .join(' ');

  const control = cloneElement(children, {
    id: controlId,
    ...(describedBy === '' ? {} : { 'aria-describedby': describedBy }),
    ...(state === 'error' ? { 'aria-invalid': true } : {}),
    ...(state === 'disabled' ? { disabled: true } : {}),
  });

  return (
    <div className={styles.field} data-state={state}>
      <label className={styles.fieldLabel} htmlFor={controlId}>
        {label}
        {required ? (
          <span className={styles.fieldRequired} aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {hint !== undefined ? (
        <span className={styles.fieldHint} id={hintId}>
          {hint}
        </span>
      ) : null}
      <div className={styles.fieldControl}>{control}</div>
      {message ? (
        <span
          className={styles.fieldMessage}
          id={messageId}
          data-tone={message.tone}
          role={message.tone === 'error' ? 'alert' : undefined}
        >
          {message.text}
        </span>
      ) : null}
    </div>
  );
}
