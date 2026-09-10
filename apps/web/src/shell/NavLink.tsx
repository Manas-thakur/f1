'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

export interface NavLinkProps {
  readonly href: string;
  readonly children: ReactNode;
  readonly className?: string;
  readonly end?: boolean;
}

export function NavLink({ href, children, className, end = false }: NavLinkProps) {
  const pathname = usePathname();
  const current = end ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link href={href} className={className} aria-current={current ? 'page' : undefined}>
      {children}
    </Link>
  );
}
