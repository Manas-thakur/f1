import * as RadixDialog from '@radix-ui/react-dialog';
import { useCallback, useEffect, useRef, type ReactNode } from 'react';

import { Button } from './Button';
import styles from './primitives.module.css';

export interface DialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly title: string;
  readonly description?: string;
  /**
   * DOM id of the control that opened the dialog. Focus returns there on
   * close, including when the dialog was opened from a table row that has
   * since re-rendered.
   */
  readonly returnFocusTo?: string | null;
  /**
   * When true, clicking the backdrop does not close the dialog. Set this
   * whenever the dialog holds unsaved state.
   */
  readonly blockOutsideClose?: boolean;
  readonly footer?: ReactNode;
  readonly children: ReactNode;
}

/**
 * Accessible dialog built on Radix.
 *
 * Guarantees required by SCREEN_INVENTORY's inspector pattern:
 *   - a title and a close control
 *   - Escape closes
 *   - focus is restored to the invoking control
 *   - focus never moves behind the modal
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  returnFocusTo = null,
  blockOutsideClose = false,
  footer,
  children,
}: DialogProps) {
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
    }
  }, [open]);

  // Radix restores focus to the element that had it before the dialog opened.
  // When the caller names an invoking control explicitly (a row action that
  // may have re-rendered), we restore to that element instead.
  const handleCloseAutoFocus = useCallback(
    (event: Event) => {
      if (returnFocusTo === null) {
        return;
      }
      const target = document.getElementById(returnFocusTo);
      if (target !== null) {
        event.preventDefault();
        target.focus();
      }
    },
    [returnFocusTo],
  );

  const handleInteractOutside = useCallback(
    (event: { preventDefault: () => void }) => {
      if (blockOutsideClose) {
        event.preventDefault();
      }
    },
    [blockOutsideClose],
  );

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.dialogOverlay} />
        <RadixDialog.Content
          className={styles.dialogContent}
          onCloseAutoFocus={handleCloseAutoFocus}
          onInteractOutside={handleInteractOutside}
        >
          <div className={styles.dialogHead}>
            <RadixDialog.Title asChild>
              <h2>{title}</h2>
            </RadixDialog.Title>
            <RadixDialog.Close asChild>
              <Button variant="quiet" aria-label="Close dialog">
                Close
              </Button>
            </RadixDialog.Close>
          </div>
          {description !== undefined ? (
            <RadixDialog.Description className={styles.dialogDescription}>
              {description}
            </RadixDialog.Description>
          ) : (
            // Radix warns when a dialog has no description; an explicit empty
            // one is honest and keeps the console clean.
            <RadixDialog.Description className="afterlap-visually-hidden">
              {title}
            </RadixDialog.Description>
          )}
          {children}
          {footer !== undefined ? <div className={styles.dialogFooter}>{footer}</div> : null}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
