import { NavLink, Outlet, useParams } from 'react-router';

import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';
import { useSessionStore } from '../state/sessionStore';
import {
  selectConnection,
  selectDataAgeS,
  selectQualitySummary,
  selectRejectedEnvelopeCount,
} from '../state/selectors';
import { QualityIndicator } from '../components/QualityIndicator';
import { StatusBadge } from '../components/StatusBadge';
import { formatAge } from '../contracts/units';
import { moduleGroups } from './modules';
import styles from './shell.module.css';

function SessionStrip() {
  const { sessionId: routeSessionId } = useParams();
  const manifest = useSessionStore((s) => s.server.manifest);
  const estimate = useSessionStore((s) => s.server.estimate);
  const status = useSessionStore((s) => s.server.status);
  const connection = useSessionStore(selectConnection);
  // selectQualitySummary is memoised on the server slice, so it returns a
  // stable reference and is safe to hand straight to the hook.
  const quality = useSessionStore(selectQualitySummary);
  const dataAge = useSessionStore(selectDataAgeS);

  const mode = manifest?.mode ?? null;
  const car = estimate?.own_car.car_id ?? null;
  const lap = estimate?.race_context.lap ?? null;
  const flagKnown = estimate?.race_context.flag_known ?? false;
  const flag = flagKnown ? (estimate?.race_context.flag_state ?? 'unknown') : 'unknown';

  return (
    <section className={styles.sessionStrip} aria-label="Session context">
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Mode</span>
        <span className={styles.stripValue}>{mode ?? 'no session'}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Session</span>
        <span className={styles.stripValue}>{routeSessionId ?? 'none selected'}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Car</span>
        <span className={styles.stripValue}>{car ?? 'unknown'}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Lap</span>
        <span className={styles.stripValue}>{lap === null ? 'unknown' : lap}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Flag</span>
        <span className={styles.stripValue}>{flag}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Data age</span>
        <span className={styles.stripValue}>{formatAge(dataAge)}</span>
      </span>
      <span className={styles.stripItem}>
        <span className={styles.stripLabel}>Source quality</span>
        <QualityIndicator quality={quality.overall} />
      </span>
      <span className={`${styles.stripItem} ${styles.stripPush}`}>
        <StatusBadge
          label="Session status"
          tone={status === 'running' ? 'selection' : 'neutral'}
        >
          {status}
        </StatusBadge>
        <StatusBadge label="Stream connection" tone="neutral">
          {connection}
        </StatusBadge>
      </span>
    </section>
  );
}

function ModuleRail() {
  const { sessionId } = useParams();
  const groups = moduleGroups(sessionId ?? null);
  return (
    <header className={styles.rail}>
      <NavLink to="/" className={styles.brand ?? ''}>
        <span className={styles.brandMark} aria-hidden="true" />
        AFTERLAP
      </NavLink>
      <nav className={styles.railNav} aria-label="Modules">
        {groups.map((group) => (
          <div key={group.label}>
            <span className={styles.railGroupLabel}>{group.label}</span>
            <ul>
              {group.links.map((link) => (
                <li key={link.to}>
                  <NavLink to={link.to} className={styles.railLink ?? ''} end={false}>
                    {link.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className={styles.railBottom}>
        <span>Working name. No affiliation implied.</span>
      </div>
    </header>
  );
}

function FooterStatus() {
  const rejected = useSessionStore(selectRejectedEnvelopeCount);
  const resync = useSessionStore((s) => s.stream.resyncCount);
  const lastSequence = useSessionStore((s) => s.server.lastSequence);
  return (
    <footer className={styles.footer}>
      <span data-testid="synthetic-data-notice">{SYNTHETIC_DATA_NOTICE}</span>
      <span>last sequence {lastSequence}</span>
      <span>rejected envelopes {rejected}</span>
      <span>resyncs {resync}</span>
    </footer>
  );
}

/**
 * The application shell.
 *
 * Left module rail, top session strip, work area, quiet footer status. One
 * `<main>` per route; the route supplies the single `<h1>`.
 */
export function AppShell() {
  return (
    <div className={styles.shell}>
      <a className="afterlap-skip-link" href="#main-content">
        Skip to main content
      </a>
      <ModuleRail />
      <div className={styles.workspace}>
        <SessionStrip />
        <main id="main-content" className={styles.main}>
          <Outlet />
        </main>
        <FooterStatus />
      </div>
    </div>
  );
}
