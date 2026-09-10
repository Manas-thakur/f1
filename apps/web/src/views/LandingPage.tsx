import { useState } from 'react';
import Link from 'next/link';

import { ChartFrame } from '../components/charts/ChartFrame';
import { Notice } from '../components/Panel';
import { ValueReadout } from '../components/ValueReadout';
import { EVIDENCE_BOUNDARY, SPECIMEN_NOTICE } from '../fixtures/notices';
import { SPECIMEN_READOUTS, specimenSeries } from '../fixtures/specimen';
import styles from '../shell/shell.module.css';

const SERIES = specimenSeries();

export function LandingPage() {
  const [cursor, setCursor] = useState<number | null>(3100);

  return (
    <>
      <section className={`${styles.webSection} ${styles.heroSection}`}>
        <div className={`${styles.webContainer} ${styles.heroGrid}`}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>Energy and overtake intelligence</p>
            <h1>Decide where electrical energy changes the race.</h1>
            <p className={styles.leadText}>
              AFTERLAP turns a simulated race state into one energy instruction, then keeps the
              observations, limits, rule checks and expected consequences attached to it.
            </p>
            <div className={styles.heroActions}>
              <Link className={styles.primaryLink} href="/sessions">Open race workspace</Link>
              <Link className={styles.secondaryLink} href="/simulation-lab">Enter simulation lab</Link>
            </div>
            <p className={styles.heroFootnote}>
              Simulation and decision support. Selecting an instruction records a human decision;
              it does not actuate a car.
            </p>
          </div>

          <aside className={styles.decisionBoard} aria-label="Illustrative decision workflow">
            <div className={styles.boardHeader}>
              <span>Illustrative decision</span><span>Lap horizon</span>
            </div>
            <p className={styles.boardKicker}>Current question</p>
            <p className={styles.boardInstruction}>Attack now, retain at the next checkpoint.</p>
            <dl className={styles.boardDefinition}>
              <div>
                <dt>Trigger</dt>
                <dd>Exit phase is stable and the rival remains in range</dd>
              </div>
              <div>
                <dt>End condition</dt>
                <dd>Target checkpoint reached or energy floor approached</dd>
              </div>
              <div>
                <dt>Invalidated by</dt>
                <dd>Flag change, stale data, rule conflict or lost overlap</dd>
              </div>
            </dl>
            <ol className={styles.boardFlow}>
              {['Observe', 'Branch', 'Check', 'Decide', 'Verify'].map((step, index) => (
                <li key={step}><span>{index + 1}</span>{step}</li>
              ))}
            </ol>
          </aside>
        </div>
      </section>

      <section className={`${styles.webSection} ${styles.specimenSection}`} aria-labelledby="instrument-view">
        <div className={styles.webContainer}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.eyebrow}>Instrument view</p>
              <h2 id="instrument-view">Read the decision and its evidence together.</h2>
            </div>
            <p>
              Every quantity states its unit, source and age. Unobserved quantities remain
              unavailable instead of becoming false zeroes.
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
              subtitle="Authored specimen; selected lap solid, reference lap dashed."
              series={SERIES}
              cursor={cursor}
              onCursorChange={setCursor}
              height={260}
            />
          </div>
        </div>
      </section>

      <section className={`${styles.webSection} ${styles.argumentSection}`} aria-labelledby="why-energy">
        <div className={styles.webContainer}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.eyebrow}>The strategy problem</p>
              <h2 id="why-energy">A completed pass can still be the wrong decision.</h2>
            </div>
            <p className={styles.pullLine}>
              The useful outcome is retained position with enough energy left to defend.
            </p>
          </div>
          <div className={styles.explainGrid}>
            <p>
              A hybrid car can only deploy stored energy within the current thermal, electrical and
              regulatory limits. Spending early can create a pass that is immediately reversed.
              Waiting can remove the passing window entirely.
            </p>
            <p>
              AFTERLAP compares tactics from the same race state, evaluates rival responses and tail
              cases, and removes any candidate the loaded ruleset cannot clear. The surviving
              recommendation carries its trigger, end condition and invalidators.
            </p>
          </div>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="roles">
        <div className={styles.webContainer}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.eyebrow}>One system, three working views</p>
              <h2 id="roles">Each person sees only the decision detail they can use.</h2>
            </div>
          </div>
          <ul className={styles.roleList}>
            <li className={styles.roleItem}>
              <span className={styles.roleLabel}>01 · Race engineer</span>
              <h3>
                <Link href="/sessions">Operate the live decision workspace</Link>
              </h3>
              <p>
                Review the instruction, inspect evidence, select it, communicate it and compare
                execution with intent.
              </p>
            </li>
            <li className={styles.roleItem}>
              <span className={styles.roleLabel}>02 · Strategy analyst</span>
              <h3>
                <Link href="/simulation-lab">Build and compare simulation branches</Link>
              </h3>
              <p>
                Configure a scenario, freeze its starting state and compare treatments across
                recorded seeds.
              </p>
            </li>
            <li className={styles.roleItem}>
              <span className={styles.roleLabel}>03 · Simulator driver</span>
              <h3>
                <Link href="/sessions">Receive a glanceable command</Link>
              </h3>
              <p>
                See the instruction, trigger, end checkpoint and withdrawal state in a dedicated
                high-contrast display.
              </p>
            </li>
          </ul>
        </div>
      </section>

      <section className={`${styles.webSection} ${styles.boundarySection}`} aria-labelledby="boundary">
        <div className={styles.webContainer}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.eyebrow}>Evidence boundary</p>
              <h2 id="boundary">What the product does not establish</h2>
            </div>
          </div>
          <ul className={styles.boundaryList}>
            {EVIDENCE_BOUNDARY.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className={styles.webSection} aria-labelledby="open">
        <div className={`${styles.webContainer} ${styles.ctaRow}`}>
          <div>
            <p className={styles.eyebrow}>Decision workspace</p>
            <h2 id="open">Start from a session state.</h2>
          </div>
          <Link className={styles.primaryLink} href="/sessions">Open sessions</Link>
        </div>
      </section>
    </>
  );
}
