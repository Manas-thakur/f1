'use client';

import type { ReactNode } from 'react';

import { MarketingLayout } from '@/shell/MarketingLayout';

export default function Layout({ children }: { readonly children: ReactNode }) {
  return <MarketingLayout>{children}</MarketingLayout>;
}
