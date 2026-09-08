import type { RuntimeCapabilities, SessionManifest } from '@contracts';

import { Notice, Panel, StatusBadge } from '@/components';
import { isReadinessRung, type ReadinessRung } from '@/api/trackCatalogue';
import {
  CORRIDOR_DERIVED_FIELDS,
  CORRIDOR_UNKNOWN_REASON,
  OPENF1_ATTRIBUTION,
  REAL_CIRCUIT_SYNTHETIC_ENERGY,
  SIMULATION_ELIGIBLE_UNREACHABLE,
  SYNTHETIC_ENERGY_EXPLANATION,
  needsOpenF1Attribution,
  provenanceText,
  readinessTone,
  shortHash,
} from './readiness';
import styles from './circuits.module.css';

export interface SessionCircuitIdentityProps {
  readonly manifest: SessionManifest | null | undefined;
  readonly capabilities?: RuntimeCapabilities | null;
}

type CorridorVerdict = 'available' | 'degraded' | 'unavailable' | 'undeclared';

function corridorVerdict(capabilities: RuntimeCapabilities | null | undefined): CorridorVerdict {
  const state = capabilities?.lateral_geometry;
  return state ?? 'undeclared';
}

function corridorSummary(verdict: CorridorVerdict): string {
  switch (verdict) {
    case 'available':
      return 'corridor surveyed';
    case 'degraded':
      return 'corridor synthetic';
    case 'unavailable':
      return 'corridor unavailable';
    default:
      return 'corridor undeclared';
  }
}

export function isRealCircuitSession(manifest: SessionManifest | null | undefined): boolean {
  return (
    manifest !== null &&
    manifest !== undefined &&
    typeof manifest.track_id === 'string' &&
    manifest.track_id !== ''
  );
}

function reportedRung(reported: string | null | undefined): ReadinessRung | null {
  return typeof reported === 'string' && isReadinessRung(reported) ? reported : null;
}

function Item({ term, value }: { readonly term: string; readonly value: string | null }) {
  return (
    <span>
      <span className={styles.identityKey}>{term}</span>
      <span className={styles.identityValue}>
        {value ?? <span className={styles.unavailable}>unavailable</span>}
      </span>
    </span>
  );
}

export function SessionCircuitStrip({ manifest }: SessionCircuitIdentityProps) {
  if (!isRealCircuitSession(manifest)) {
    return (
      <p className={styles.identityStrip} data-testid="session-circuit-strip">
        <Item term="circuit" value="synthetic track document" />
        <Item term="geometry" value={provenanceText(manifest?.geometry_provenance ?? null)} />
        <StatusBadge label="Data class" tone="attention">
          synthetic
        </StatusBadge>
      </p>
    );
  }

  const track = manifest as SessionManifest;
  return (
    <p className={styles.identityStrip} data-testid="session-circuit-strip">
      <Item term="circuit" value={track.track_id ?? null} />
      <span>
        <span className={styles.identityKey}>readiness</span>
        <StatusBadge
          label="Readiness rung"
          tone={readinessTone(reportedRung(track.track_readiness))}
        >
          {track.track_readiness ?? 'unavailable'}
        </StatusBadge>
      </span>
      <Item term="package" value={shortHash(track.track_package_hash)} />
      <Item term="conditions" value={track.conditions_id ?? null} />
      <Item term="tape" value={shortHash(track.conditions_hash)} />
      <StatusBadge label="Run label" tone="attention" title={SYNTHETIC_ENERGY_EXPLANATION}>
        {REAL_CIRCUIT_SYNTHETIC_ENERGY}
      </StatusBadge>
    </p>
  );
}

export function DriverCircuitContext({ manifest, capabilities }: SessionCircuitIdentityProps) {
  const corridor = corridorSummary(corridorVerdict(capabilities));
  if (!isRealCircuitSession(manifest)) {
    return (
      <>
        <span>circuit synthetic</span>
        <span>{corridor}</span>
      </>
    );
  }
  return (
    <>
      <span>circuit {manifest?.track_id}</span>
      <span>{manifest?.track_readiness ?? 'readiness unavailable'}</span>
      <span data-testid="driver-synthetic-energy">{REAL_CIRCUIT_SYNTHETIC_ENERGY}</span>
      <span>{corridor}</span>
    </>
  );
}

export function SessionCircuitPanel({ manifest, capabilities }: SessionCircuitIdentityProps) {
  const real = isRealCircuitSession(manifest);
  const provenance = manifest?.geometry_provenance ?? null;
  const verdict = corridorVerdict(capabilities);
  const notes = capabilities?.notes ?? [];

  return (
    <Panel id="circuit" title="Circuit">
      <SessionCircuitStrip manifest={manifest} />

      <dl className={styles.factList}>
        <dt>Track id</dt>
        <dd>
          {real ? (
            manifest?.track_id
          ) : (
            <span className={styles.unavailable}>
              none — this session runs a synthetic track document
            </span>
          )}
        </dd>
        <dt>Event id</dt>
        <dd>
          {manifest?.event_id ?? <span className={styles.unavailable}>unavailable</span>}
        </dd>
        <dt>Readiness rung</dt>
        <dd>
          {manifest?.track_readiness ?? <span className={styles.unavailable}>unavailable</span>}
        </dd>
        <dt>Geometry provenance</dt>
        <dd>{provenanceText(provenance)}</dd>
        <dt>Track package hash</dt>
        <dd>
          {shortHash(manifest?.track_package_hash) === null ? (
            <span className={styles.unavailable}>unavailable</span>
          ) : (
            <span className={styles.hash}>{shortHash(manifest?.track_package_hash)}</span>
          )}
        </dd>
        <dt>Event package hash</dt>
        <dd>
          {shortHash(manifest?.event_package_hash) === null ? (
            <span className={styles.unavailable}>
              unavailable — no reviewer-confirmed event overlay
            </span>
          ) : (
            <span className={styles.hash}>{shortHash(manifest?.event_package_hash)}</span>
          )}
        </dd>
        <dt>Conditions id</dt>
        <dd>
          {manifest?.conditions_id ?? <span className={styles.unavailable}>unavailable</span>}
        </dd>
        <dt>Conditions tape hash</dt>
        <dd>
          {shortHash(manifest?.conditions_hash) === null ? (
            <span className={styles.unavailable}>unavailable</span>
          ) : (
            <span className={styles.hash}>{shortHash(manifest?.conditions_hash)}</span>
          )}
        </dd>
      </dl>

      {real ? (
        <>
          <Notice tone="attention" testId="circuit-synthetic-energy">
            <strong>{REAL_CIRCUIT_SYNTHETIC_ENERGY}.</strong> {SYNTHETIC_ENERGY_EXPLANATION}{' '}
            {SIMULATION_ELIGIBLE_UNREACHABLE}
          </Notice>

          <h3>Corridor</h3>
          <p className="afterlap-small afterlap-muted">
            The control plane declares lateral geometry{' '}
            <span className="afterlap-mono">{verdict}</span> for this session, re-read from the
            package the hash on this session pins.{' '}
            {verdict === 'available' ? '' : CORRIDOR_UNKNOWN_REASON}
          </p>
          {verdict === 'available' ? null : (
            <ul className={styles.withdrawnList} data-testid="circuit-corridor-withdrawn">
              {CORRIDOR_DERIVED_FIELDS.map((field) => (
                <li key={field}>
                  {field}: <span className={styles.withdrawnValue}>unavailable</span>
                </li>
              ))}
            </ul>
          )}

          {notes.length === 0 ? null : (
            <>
              <h3>Notes from the control plane</h3>
              <ul className={styles.withdrawnList} data-testid="circuit-capability-notes">
                {notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}

          {needsOpenF1Attribution(provenance) ? (
            <p className={styles.attribution} data-testid="circuit-panel-attribution">
              {OPENF1_ATTRIBUTION}
            </p>
          ) : null}
        </>
      ) : (
        <p className="afterlap-small afterlap-muted">
          No compiled circuit is bound to this session, so there is no readiness rung, package
          hash or corridor to report. Selecting a circuit is done in the simulation laboratory
          when the session is created.
        </p>
      )}
    </Panel>
  );
}
