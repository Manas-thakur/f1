/**
 * Operator identity and viewport class.
 *
 * There is no authentication in this build. The control plane requires an
 * `operator_id` on every mutable route and checks a single-operator control
 * lease against it, so the console sends a fixed console identity and says so
 * on screen. Replacing this with the authenticated identity is a named
 * integration action in `handoffs/A09-A11.md`; it is deliberately a constant
 * rather than a free-text field so nobody can impersonate another operator
 * from the browser.
 */
import { useEffect, useState } from 'react';

export const CONSOLE_OPERATOR_ID = 'console-operator';

export const OPERATOR_IDENTITY_NOTE =
  `No authenticated identity exists in this build. Commands are sent as "${CONSOLE_OPERATOR_ID}" ` +
  'and the control lease is held under that name.';

/** Breakpoint at which the operational view becomes a read-only summary. */
export const NARROW_QUERY = '(max-width: 768px)';

/**
 * True on a narrow viewport.
 *
 * The operational routes hide their command controls there: a phone-width
 * screen is a place to read the current decision, not to actuate one, and
 * laboratory controls stay on their own route entirely.
 */
export function useNarrowViewport(query: string = NARROW_QUERY): boolean {
  const [narrow, setNarrow] = useState<boolean>(() => {
    if (typeof globalThis.matchMedia !== 'function') {
      return false;
    }
    return globalThis.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof globalThis.matchMedia !== 'function') {
      return;
    }
    const list = globalThis.matchMedia(query);
    setNarrow(list.matches);
    const onChange = (event: MediaQueryListEvent): void => setNarrow(event.matches);
    if (typeof list.addEventListener === 'function') {
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    }
    return;
  }, [query]);

  return narrow;
}
