/**
 * The conditions selector.
 *
 * Rows come from `GET /api/v1/conditions`: the tape's source kind, its
 * content hash and its rainfall minutes, all as the control plane reported
 * them. A tape whose rainfall flag was never carried by the source reports
 * `rainfall_minutes: null`, and that renders as unavailable — never as
 * "0 minutes", which would read as a dry session.
 *
 * The permission text travels with the row. The real 2025 tapes are OpenF1
 * weather under CC BY-NC-SA 4.0 (D-11): a trackside station reading, not a
 * certified condition.
 */
import { StatusBadge } from '@/components';
import type { ConditionsCatalogueEntry } from '@/api/trackCatalogue';
import { shortHash } from './readiness';
import styles from './circuits.module.css';

export interface ConditionsSelectorProps {
  readonly conditions: readonly ConditionsCatalogueEntry[];
  readonly selectedConditionsId: string | null;
  readonly onSelect: (conditionsId: string) => void;
  readonly name?: string;
  /** The catalogue's own notice, shown verbatim when it sent one. */
  readonly notice?: string | null;
}

function sourceTone(sourceKind: string | null) {
  if (sourceKind === 'openf1') return 'reference' as const;
  if (sourceKind === 'synthetic') return 'attention' as const;
  return 'neutral' as const;
}

function sourceText(sourceKind: string | null): string {
  if (sourceKind === 'openf1') return 'openf1 (recorded, unofficial)';
  if (sourceKind === 'synthetic') return 'synthetic';
  return sourceKind ?? 'source not reported';
}

export function ConditionsSelector({
  conditions,
  selectedConditionsId,
  onSelect,
  name = 'lab-conditions',
  notice = null,
}: ConditionsSelectorProps) {
  return (
    <div>
      <ul className={styles.optionList} aria-label="Condition tapes">
        {conditions.map((tape) => {
          const hash = shortHash(tape.content_hash);
          const reasonId = `conditions-${tape.conditions_id}-reason`;
          return (
            <li
              key={tape.conditions_id}
              className={styles.option}
              data-selectable={tape.available ? 'true' : 'false'}
              data-selected={selectedConditionsId === tape.conditions_id ? 'true' : 'false'}
              data-testid={`conditions-option-${tape.conditions_id}`}
            >
              <input
                type="radio"
                name={name}
                id={`conditions-${tape.conditions_id}`}
                value={tape.conditions_id}
                checked={selectedConditionsId === tape.conditions_id}
                disabled={!tape.available}
                {...(tape.available ? {} : { 'aria-describedby': reasonId })}
                onChange={() => onSelect(tape.conditions_id)}
              />
              <div className={styles.optionBody}>
                <label
                  className={styles.optionTitle}
                  htmlFor={`conditions-${tape.conditions_id}`}
                >
                  <span className={styles.optionId}>{tape.conditions_id}</span>
                  <StatusBadge label="Tape source" tone={sourceTone(tape.source)}>
                    {sourceText(tape.source)}
                  </StatusBadge>
                </label>

                <dl className={styles.factList}>
                  <dt>Tape hash</dt>
                  <dd>
                    {hash === null ? (
                      <span className={styles.unavailable}>
                        unavailable — the tape has not been resolved
                      </span>
                    ) : (
                      <span className={styles.hash}>{hash}</span>
                    )}
                  </dd>
                  <dt>Rainfall</dt>
                  <dd>
                    {tape.rainfall_minutes === null ? (
                      <span className={styles.unavailable}>
                        unavailable — the source carried no rainfall flag
                      </span>
                    ) : (
                      `${tape.rainfall_minutes.toFixed(1)} minutes with the rainfall flag set`
                    )}
                  </dd>
                  <dt>Samples</dt>
                  <dd>
                    {tape.sample_count === null ? (
                      <span className={styles.unavailable}>unavailable</span>
                    ) : (
                      `${tape.sample_count} over ${
                        tape.duration_s === null
                          ? 'an unreported duration'
                          : `${(tape.duration_s / 60).toFixed(0)} minutes`
                      }`
                    )}
                  </dd>
                  <dt>Altitude</dt>
                  <dd>
                    {tape.altitude_m === null ? (
                      <span className={styles.unavailable}>unavailable</span>
                    ) : (
                      `${tape.altitude_m.toFixed(0)} m (${tape.altitude_source ?? 'source not reported'})`
                    )}
                  </dd>
                  <dt>Description</dt>
                  <dd>
                    {tape.description ?? <span className={styles.unavailable}>not reported</span>}
                  </dd>
                </dl>

                {tape.available ? null : (
                  <p className={styles.blocked} id={reasonId}>
                    Not selectable.{' '}
                    {tape.unavailable_reason ??
                      'The control plane reports this tape as unavailable and gave no reason.'}
                  </p>
                )}

                {tape.permission === null ? null : (
                  <p className={styles.attribution}>{tape.permission}</p>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {notice === null ? null : <p className={styles.attribution}>{notice}</p>}
      <p className={styles.attribution}>
        No conditions calibration evidence exists for any circuit, so no tape carries
        condition_calibrated. A tape reproduces one recorded session; it is not a distribution and
        not a forecast. The catalogue declares no circuit binding, so check the tape's altitude and
        session against the circuit you selected.
      </p>
    </div>
  );
}
