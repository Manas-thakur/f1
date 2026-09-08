
import { useEffect, useState } from 'react';

export const CONSOLE_OPERATOR_ID = 'console-operator';

export const OPERATOR_IDENTITY_NOTE =
  `No authenticated identity exists in this build. Commands are sent as "${CONSOLE_OPERATOR_ID}" ` +
  'and the control lease is held under that name.';


export const NARROW_QUERY = '(max-width: 768px)';


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
