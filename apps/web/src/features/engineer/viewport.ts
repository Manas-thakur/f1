
import { useEffect, useState } from 'react';

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
