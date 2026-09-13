'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode, Ref } from 'react';

import styles from './nav.module.css';

const PAGES = [
  { href: '/race', label: 'Race', match: (path: string) => path === '/race' },
  { href: '/race/engineer', label: 'Engineer', match: (path: string) => path === '/race/engineer' },
] as const;

export function SiteNav({
  children,
  className,
  menu,
  ref,
}: {
  readonly children?: ReactNode;
  readonly className?: string | undefined;
  readonly menu?: ReactNode;
  readonly ref?: Ref<HTMLElement | null>;
}) {
  const pathname = usePathname() ?? '';
  return (
    <header
      ref={ref}
      className={className ? `${styles.bar} ${className}` : styles.bar}
      data-menu={menu ? 'true' : 'false'}
    >
      <Link className={styles.brand} href="/race" aria-label="Afterlap race">
        <b>AL</b>
        <span>AFTERLAP</span>
      </Link>
      <nav className={styles.links} aria-label="Pages">
        {PAGES.map((page) => (
          <Link
            key={page.href}
            href={page.href}
            {...(page.match(pathname) ? { 'aria-current': 'page' as const } : {})}
          >
            {page.label}
          </Link>
        ))}
      </nav>
      {children}
      {menu ? <div className={styles.menu}>{menu}</div> : null}
    </header>
  );
}
