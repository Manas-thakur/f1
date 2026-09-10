import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { Providers } from '@/shell/Providers';
import '@/styles/base.css';

export const metadata: Metadata = {
  title: 'AFTERLAP: energy deployment workspace',
  description:
    'AFTERLAP: a simulation workspace for hybrid energy deployment strategy. All data shown is synthetic.',
};

export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div id="root">
          <Providers>{children}</Providers>
        </div>
      </body>
    </html>
  );
}
