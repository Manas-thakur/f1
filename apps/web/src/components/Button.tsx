import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import styles from './primitives.module.css';

export type ButtonVariant = 'default' | 'primary' | 'quiet' | 'danger';


export type ButtonState = 'default' | 'pending' | 'error' | 'success' | 'disabled';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  readonly variant?: ButtonVariant;
  readonly state?: ButtonState;
  
  readonly pendingLabel?: string;
  
  readonly disabledReason?: string;
  
  readonly errorMessage?: string;
  
  readonly successMessage?: string;
  readonly children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'default',
    state = 'default',
    pendingLabel = 'Working…',
    disabledReason,
    errorMessage,
    successMessage,
    children,
    className,
    type = 'button',
    ...rest
  },
  ref,
) {
  const pending = state === 'pending';
  const disabled = state === 'disabled' || pending || rest.disabled === true;

  const note =
    state === 'error' && errorMessage
      ? { tone: 'error' as const, text: errorMessage }
      : state === 'success' && successMessage
        ? { tone: 'success' as const, text: successMessage }
        : disabled && disabledReason
          ? { tone: 'neutral' as const, text: disabledReason }
          : null;

  const classes = [styles.button, variant !== 'default' ? styles[variant] : null, className]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={styles.buttonWrap}>
      <button
        {...rest}
        ref={ref}
        type={type}
        className={classes}
        data-state={state}
        data-variant={variant}
        disabled={disabled}
        aria-busy={pending || undefined}
        aria-describedby={note ? `${rest.id ?? 'button'}-note` : rest['aria-describedby']}
      >
        {pending ? (
          <>
            <span className={styles.spinner} aria-hidden="true" />
            {pendingLabel}
          </>
        ) : (
          children
        )}
      </button>
      {note ? (
        <span
          id={`${rest.id ?? 'button'}-note`}
          className={styles.buttonNote}
          data-tone={note.tone}
        >
          {note.text}
        </span>
      ) : null}
    </span>
  );
});
