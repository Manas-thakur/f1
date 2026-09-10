'use client';

import type { ReactNode } from 'react';

import { AppShell } from '@/shell/AppShell';

export default function Layout({ children }: { readonly children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
