import type { ReactNode } from 'react';
import type { TrackSummary } from '@contracts';

import { StatusBadge } from '../StatusBadge';
import {
  MIN_SELECTABLE_RUNG,
  OPENF1_ATTRIBUTION,
  SIMULATION_ELIGIBLE_UNREACHABLE,
  corridorText,
  needsOpenF1Attribution,
  provenanceText,
  readinessTone,
  readinessView,
  selectability,
  shortHash,
} from '@/contracts/readiness';
import styles from '@/styles/circuits.module.css';

export interface CircuitSelectorProps {
  readonly tracks: readonly TrackSummary[];
  readonly selectedTrackId: string | null;
  readonly onSelect: (trackId: string) => void;
  readonly name?: string;
}

function Fact({ term, children }: { readonly term: string; readonly children: ReactNode }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </>
  );
}

function Unavailable({ children }: { readonly children: ReactNode }) {
  return <span className={styles.unavailable}>{children}</span>;
}

export function CircuitSelector({
  tracks,
  selectedTrackId,
  onSelect,
  name = 'lab-circuit',
}: CircuitSelectorProps) {
  const anyOpenF1 = tracks.some((track) =>
    needsOpenF1Attribution(track.geometry_provenance ?? null),
  );

  return (
    <div>
      <ul className={styles.optionList} aria-label="Registered circuits">
        {tracks.map((track) => {
          const state = selectability(track);
          const reasonId = `circuit-${track.track_id}-reason`;
          const hash = shortHash(track.package_hash);
          const licences = track.licence_labels ?? [];
          const closureErrorM = track.closure_error_m ?? null;
          const lengthErrorFraction = track.length_error_fraction ?? null;
          const officialLengthM = track.official_length_m ?? null;
          const reported = readinessView(track).reported;
          return (
            <li
              key={track.track_id}
              className={styles.option}
              data-selectable={state.selectable ? 'true' : 'false'}
              data-selected={selectedTrackId === track.track_id ? 'true' : 'false'}
              data-testid={`circuit-option-${track.track_id}`}
            >
              <input
                type="radio"
                name={name}
                id={`circuit-${track.track_id}`}
                value={track.track_id}
                checked={selectedTrackId === track.track_id}
                disabled={!state.selectable}
                {...(state.selectable ? {} : { 'aria-describedby': reasonId })}
                onChange={() => onSelect(track.track_id)}
              />
              <div className={styles.optionBody}>
                <label className={styles.optionTitle} htmlFor={`circuit-${track.track_id}`}>
                  <span>{track.display_name}</span>
                  <span className={styles.optionId}>{track.track_id}</span>
                  <StatusBadge label="Readiness rung" tone={readinessTone(reported)}>
                    {reported ?? 'no rung reported'}
                  </StatusBadge>
                </label>

                <dl className={styles.factList}>
                  <Fact term="Geometry provenance">
                    {provenanceText(track.geometry_provenance ?? null)}
                  </Fact>
                  <Fact term="Package hash">
                    {hash === null ? (
                      <Unavailable>no compiled package</Unavailable>
                    ) : (
                      <span className={styles.hash}>{hash}</span>
                    )}
                  </Fact>
                  <Fact term="Corridor quality">
                    {corridorText(track.corridor_quality ?? null)}
                  </Fact>
                  <Fact term="Closure error">
                    {closureErrorM === null ? (
                      <Unavailable>not measured</Unavailable>
                    ) : (
                      `${closureErrorM.toExponential(1)} m`
                    )}
                  </Fact>
                  <Fact term="Length vs official">
                    {lengthErrorFraction === null ? (
                      <Unavailable>not measured</Unavailable>
                    ) : (
                      `${(lengthErrorFraction * 100).toFixed(3)} %`
                    )}
                  </Fact>
                  <Fact term="Official length">
                    {officialLengthM === null ? (
                      <Unavailable>not retrieved</Unavailable>
                    ) : (
                      `${officialLengthM.toFixed(0)} m${
                        (track.official_length_verified ?? false) ? '' : ' (unverified source)'
                      }`
                    )}
                  </Fact>
                </dl>

                {licences.length === 0 ? null : (
                  <p className={styles.attribution}>
                    Source permissions: {licences.join(' · ')}
                  </p>
                )}

                {state.selectable ? null : (
                  <p className={styles.blocked} id={reasonId}>
                    Not selectable. {state.reason}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <p className={styles.attribution} data-testid="circuit-ladder-note">
        A circuit is offered only at {MIN_SELECTABLE_RUNG} or above. {SIMULATION_ELIGIBLE_UNREACHABLE}
      </p>
      {anyOpenF1 ? (
        <p className={styles.attribution} data-testid="circuit-openf1-attribution">
          {OPENF1_ATTRIBUTION}
        </p>
      ) : null}
    </div>
  );
}
