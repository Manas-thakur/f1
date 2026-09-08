import * as RadixDialog from '@radix-ui/react-dialog';
import { useCallback, useEffect, useRef, type ReactNode } from 'react';

import { Button } from './Button';
import styles from './primitives.module.css';

export interface DialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly title: string;
  readonly description?: string;
  
  readonly returnFocusTo?: string | null;
  
  readonly blockOutsideClose?: boolean;
  readonly footer?: ReactNode;
  readonly children: ReactNode;
}


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
