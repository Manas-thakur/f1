import { Link, NavLink, Outlet } from 'react-router';

import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';
import styles from './shell.module.css';

/**
 * Layout for the two product pages (`/` and `/simulation-lab`).
 *
 * These are documents, not the operator workspace, so they use a plain top nav
 * rather than the module rail. They carry no forms, no payment, no tracking
 * and no external submission of any kind.
 */
export function MarketingLayout() {
  return (
    <div className={styles.webShell}>
      <a className="afterlap-skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className={styles.webNav}>
        <div className={styles.webContainer}>
          <div className={styles.webNavInner}>
            <Link to="/" className={styles.brand}>
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
                  <NavLink to="/">Overview</NavLink>
                </li>
                <li>
                  <NavLink to="/simulation-lab">Simulation lab</NavLink>
                </li>
                <li>
                  <NavLink to="/sessions">Open workspace</NavLink>
                </li>
              </ul>
            </nav>
          </div>
        </div>
      </header>

      <main id="main-content">
        <Outlet />
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
