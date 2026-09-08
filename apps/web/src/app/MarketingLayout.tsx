import { Link, NavLink, Outlet } from 'react-router';

import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';
import styles from './shell.module.css';


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
