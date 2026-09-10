'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';

import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';
import { NavLink } from './NavLink';
import styles from './shell.module.css';


export function MarketingLayout({ children }: { readonly children: ReactNode }) {
  return (
    <div className={styles.webShell}>
      <a className="afterlap-skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className={styles.webNav}>
        <div className={styles.webContainer}>
          <div className={styles.webNavInner}>
            <Link href="/" className={styles.brand}>
              <span className={styles.brandMark} aria-hidden="true" />
              AFTERLAP
            </Link>
            <div className={styles.webNavMeta}>
              <span>Simulation decision system</span>
              <span>Energy · Overtake · Evidence</span>
            </div>
            <nav aria-label="Product pages">
              <ul className={styles.webNavLinks}>
                <li>
                  <NavLink href="/" end>
                    Overview
                  </NavLink>
                </li>
                <li>
                  <NavLink href="/simulation-lab" end>
                    Simulation lab
                  </NavLink>
                </li>
                <li>
                  <NavLink href="/sessions" end>
                    Open workspace
                  </NavLink>
                </li>
              </ul>
            </nav>
          </div>
        </div>
      </header>

      <main id="main-content">
        {children}
      </main>

      <footer className={styles.webFooter}>
        <div className={`${styles.webContainer} ${styles.webFooterInner}`}>
          <span data-testid="synthetic-data-notice">{SYNTHETIC_DATA_NOTICE}</span>
          <span>AFTERLAP is a working name. No affiliation with any championship or team.</span>
        </div>
      </footer>
    </div>
  );
}
