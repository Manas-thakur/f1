import {
  Close as DialogClose,
  Content as DialogContent,
  Description as DialogDescription,
  Overlay as DialogOverlay,
  Portal as DialogPortal,
  Root as DialogRoot,
  Title as DialogTitle,
} from '@radix-ui/react-dialog';
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
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className={styles.dialogOverlay} />
        <DialogContent
          className={styles.dialogContent}
          onCloseAutoFocus={handleCloseAutoFocus}
          onInteractOutside={handleInteractOutside}
        >
          <div className={styles.dialogHead}>
            <DialogTitle asChild>
              <h2>{title}</h2>
            </DialogTitle>
            <DialogClose asChild>
              <Button variant="quiet" aria-label="Close dialog">
                Close
              </Button>
            </DialogClose>
          </div>
          {description !== undefined ? (
            <DialogDescription className={styles.dialogDescription}>
              {description}
            </DialogDescription>
          ) : (


            <DialogDescription className="afterlap-visually-hidden">
              {title}
            </DialogDescription>
          )}
          {children}
          {footer !== undefined ? <div className={styles.dialogFooter}>{footer}</div> : null}
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
}
