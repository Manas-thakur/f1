import { useState } from 'react';
import { Link } from 'react-router';

import { ChartFrame } from '../components/charts/ChartFrame';
import { Notice } from '../components/Panel';
import { ValueReadout } from '../components/ValueReadout';
import { EVIDENCE_BOUNDARY, SPECIMEN_NOTICE } from '../fixtures/notices';
import { SPECIMEN_READOUTS, specimenSeries } from '../fixtures/specimen';
import styles from '../app/shell.module.css';

const SERIES = specimenSeries();


export function LandingPage() {
  const [cursor, setCursor] = useState<number | null>(3100);

  return (
    <>
      <section className={styles.webSection}>
        <div className={styles.webContainer}>
          <div className={styles.webIntro}>
            <h1>Energy deployment decisions, with the evidence attached</h1>
            <p className={styles.leadText}>
              AFTERLAP is a simulation workspace for hybrid energy strategy. It estimates the
              state of a car and its rivals, plans a deployment profile over the next
              checkpoints, checks that profile against a loaded ruleset, and hands a race
              engineer one instruction with the observations, limits and rule results that
              produced it. Selecting an instruction records a decision. It never actuates a car.
            </p>
            <p>
              Every number on screen states its unit, where it came from and how old it is. A
              quantity the product cannot observe is shown as unavailable, not as zero.
            </p>
          </div>

          <div className={styles.specimen}>
            <Notice tone="attention">{SPECIMEN_NOTICE}</Notice>
            <div className={styles.specimenRow}>
              {SPECIMEN_READOUTS.map((readout) => (
                <ValueReadout
                  key={readout.label}
                  label={readout.label}
                  channel={readout.channel}
                  value={readout.value}
                  provenance={readout.provenance}
                  quality={readout.quality}
                  ageS={readout.ageS}
                  {...(readout.unavailableReason === undefined
                    ? {}
                    : { unavailableReason: readout.unavailableReason })}
                />
              ))}
            </div>
            <ChartFrame
              title="Deployment and stored energy over one lap"
              subtitle="Authored specimen; the selected lap is solid, the reference lap dashed."
              series={SERIES}
              cursor={cursor}
              onCursorChange={setCursor}
              height={260}
            />
          </div>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="why-energy">
        <div className={styles.webContainer}>
          <h2 id="why-energy">Why energy decides retained position</h2>
          <div className={styles.explainGrid}>
            <div>
              <p>
                A hybrid power unit can only deploy the energy it has already stored, under a
                ceiling that changes with speed, temperature and the current rules. Spending it
                early buys a pass that the car behind can immediately reverse; spending it late
                may mean never getting close enough to try. The question is not top speed. It is
                which distribution of a fixed budget over the remaining checkpoints leaves the
                car ahead at the end of the stint and still able to defend.
              </p>
            </div>
            <div>
              <p>
                That makes it an optimisation over an uncertain rival, not a lookup. AFTERLAP
                enumerates discrete tactics, solves a continuous deployment profile for each,
                scores them against sampled rival behaviour including the tail cases, and
                rejects anything the rule checker cannot clear. What reaches the engineer is the
                surviving candidate, its end condition, and what would invalidate it.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="roles">
        <div className={styles.webContainer}>
          <h2 id="roles">Three ways in</h2>
          <ul className={styles.roleList}>
            <li className={styles.roleItem}>
              <h3>
                <Link to="/sessions">Race engineer — open a session workspace</Link>
              </h3>
              <p>
                One instruction with its trigger and end condition, the channels behind it, the
                rule results, and the decision history. Select, mark communicated, and see what
                the driver actually did.
              </p>
            </li>
            <li className={styles.roleItem}>
              <h3>
                <Link to="/simulation-lab">Strategy analyst — open the simulation lab</Link>
              </h3>
              <p>
                Configure a scenario, take an immutable snapshot, branch treatments from that
                same snapshot, and compare outcomes across recorded seeds.
              </p>
            </li>
            <li className={styles.roleItem}>
              <h3>
                <Link to="/sessions">Simulator driver — pick a session, then open its display</Link>
              </h3>
              <p>
                A dedicated dark, high-contrast screen showing the current instruction and its
                withdrawal. It exists only in simulator sessions; the session list is the way in.
              </p>
            </li>
          </ul>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="boundary">
        <div className={styles.webContainer}>
          <h2 id="boundary">What this product does not establish</h2>
          <ul className={styles.boundaryList}>
            {EVIDENCE_BOUNDARY.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="open">
        <div className={`${styles.webContainer} ${styles.ctaRow}`}>
          <h2 id="open">Open the workspace</h2>
          <Link to="/sessions">Go to sessions</Link>
        </div>
      </section>
    </>
  );
}
