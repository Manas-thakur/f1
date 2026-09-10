'use client';

import { AppShell } from '@/shell/AppShell';
import { NotFoundPage } from '@/views/NotFoundPage';

export default function NotFound() {
  return (
    <AppShell>
      <NotFoundPage />
    </AppShell>
  );
}
