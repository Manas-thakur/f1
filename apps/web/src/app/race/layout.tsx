import type { ReactNode } from 'react';

import { RaceConnectionProvider } from '@/features/race/Connection';

export default function Layout({ children }: { readonly children: ReactNode }) {
  return <RaceConnectionProvider>{children}</RaceConnectionProvider>;
}
