import { useState } from 'react';
import { Link } from 'react-router';

import { ChartFrame } from '../components/charts/ChartFrame';
import { DataTable, type Column } from '../components/DataTable';
import { Notice } from '../components/Panel';
import { StatusBadge } from '../components/StatusBadge';
import { SPECIMEN_NOTICE } from '../fixtures/notices';
import { specimenSeries } from '../fixtures/specimen';
import styles from '../app/shell.module.css';

const SERIES = specimenSeries();

interface CapabilityRow {
  readonly id: string;
  readonly capability: string;
  readonly what: string;
  readonly established: 'in the product' | 'not established';
}

const CAPABILITIES: readonly CapabilityRow[] = [
  {
    id: 'snapshot',
    capability: 'Immutable snapshot',
    what: 'A complete, content-hashed simulation state that every branch starts from.',
    established: 'in the product',
  },
  {
    id: 'seeds',
    capability: 'Recorded seeds',
    what: 'Disturbance and opponent seeds are stored with the experiment manifest.',
    established: 'in the product',
  },
  {
    id: 'checker',
    capability: 'Independent rule checker',
    what: 'Candidate profiles are checked against the loaded ruleset manifest, not the planner.',
    established: 'in the product',
  },
  {
    id: 'calibration',
    capability: 'Calibration status',
    what: 'Every probability reports whether it has been calibrated against held-out outcomes.',
    established: 'in the product',
  },
  {
    id: 'track',
    capability: 'On-track performance',
    what: 'No measurement against a real car or a real race exists.',
    established: 'not established',
  },
];

const COLUMNS: readonly Column<CapabilityRow>[] = [
  { id: 'capability', header: 'Capability', cell: (r) => r.capability },
  { id: 'what', header: 'What it means', cell: (r) => r.what },
  {
    id: 'established',
    header: 'Status',
    cell: (r) => (
      <StatusBadge
        label="Status"
        tone={r.established === 'in the product' ? 'verified' : 'neutral'}
      >
        {r.established}
      </StatusBadge>
    ),
  },
];

/**
 * `/simulation-lab` — the lab product page.
 *
 * Explains the snapshot / branch / inspect workflow, shows the specimen it
 * produces, states the validation capabilities and their boundary, and links
 * into the workspace. No forms, no submissions.
 */
export function SimulationLabLandingPage() {
  const [cursor, setCursor] = useState<number | null>(2600);

  return (
    <>
      <section className={styles.webSection}>
        <div className={styles.webContainer}>
          <div className={styles.webIntro}>
            <h1>Reproducible experiments over a frozen simulation state</h1>
            <p className={styles.leadText}>
              The simulation lab exists so that a comparison means something. Every branch starts
              from the same immutable snapshot, runs against the same recorded seeds, and is
              scored by the same evaluator version. A result that cannot be regenerated from its
              manifest is not a result.
            </p>
          </div>

          <div className={styles.specimen}>
            <Notice tone="attention">{SPECIMEN_NOTICE}</Notice>
            <ChartFrame
              title="Branch comparison specimen"
              subtitle="Two treatments from one snapshot. Reference branch dashed."
              series={SERIES.slice(0, 2)}
              cursor={cursor}
              onCursorChange={setCursor}
              height={240}
            />
          </div>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="workflow">
        <div className={styles.webContainer}>
          <h2 id="workflow">Snapshot, branch, inspect</h2>
          <ul className={styles.roleList}>
            <li className={styles.roleItem}>
              <h3>Configure the scenario</h3>
              <p>
                Track, cars, ruleset, opponent policies and the starting state. The configuration
                is hashed into the session manifest, so the run is identified by what it actually
                contained rather than by a label.
              </p>
            </li>
            <li className={styles.roleItem}>
              <h3>Snapshot</h3>
              <p>
                Freeze the complete simulation state. The snapshot hash is the shared origin of
                every treatment. Nothing about it changes once taken.
              </p>
            </li>
            <li className={styles.roleItem}>
              <h3>Branch treatments</h3>
              <p>
                Run candidate controllers from that one snapshot across the recorded seed set. A
                cancelled or partial run is reported as partial, never quietly averaged in.
              </p>
            </li>
            <li className={styles.roleItem}>
              <h3>Inspect</h3>
              <p>
                Compare aligned traces on a shared cursor, read the checkpoint outcomes, and open
                the audit record for any single decision including the rule checks behind it.
              </p>
            </li>
          </ul>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="validation">
        <div className={styles.webContainer}>
          <h2 id="validation">Validation capabilities and their boundary</h2>
          <p className="afterlap-muted" style={{ marginBottom: 'var(--s4)' }}>
            The last row is the one that matters most: nothing in this product has been measured
            against a real car.
          </p>
          <DataTable
            caption="Validation capabilities"
            columns={COLUMNS}
            rows={CAPABILITIES}
            rowKey={(r) => r.id}
          />
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="open-lab">
        <div className={`${styles.webContainer} ${styles.ctaRow}`}>
          <h2 id="open-lab">Open the lab</h2>
          <Link to="/sessions">Choose a session to branch from</Link>
        </div>
      </section>
    </>
  );
}
