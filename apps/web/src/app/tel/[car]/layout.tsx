import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { RaceConnectionProvider } from '@/features/race/Connection';

export const metadata: Metadata = {
  title: 'Car telemetry',
  description: 'Delayed simulated telemetry for one race car on an 800 by 480 display.',
};

export default function Layout({ children }: { readonly children: ReactNode }) {
  return <RaceConnectionProvider>{children}</RaceConnectionProvider>;
}
