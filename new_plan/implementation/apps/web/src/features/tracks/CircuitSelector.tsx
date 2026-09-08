/**
 * The circuit selector.
 *
 * Every row is live data from `GET /api/v1/tracks`: readiness rung, geometry
 * provenance, short package hash and corridor quality. Nothing is hardcoded
 * and no circuit list is shipped in the bundle.
 *
 * A radio group, not a `<select>`: a circuit below `geometry_validated` must
 * be *visibly* unselectable with its reason on screen, and a disabled
 * `<option>` inside a closed listbox can show neither. Each disabled radio is
 * described by the paragraph carrying that reason, so the reason is announced
 * too, not only drawn.
 */
import type { ReactNode } from 'react';

import { StatusBadge } from '@/components';
import type { TrackCatalogueEntry } from '@/api/trackCatalogue';
import {
  MIN_SELECTABLE_RUNG,
  OPENF1_ATTRIBUTION,
  SIMULATION_ELIGIBLE_UNREACHABLE,
  corridorText,
  needsOpenF1Attribution,
  provenanceText,
  readinessTone,
  selectability,
  shortHash,
} from './readiness';
import styles from './circuits.module.css';

export interface CircuitSelectorProps {
  readonly tracks: readonly TrackCatalogueEntry[];
  readonly selectedTrackId: string | null;
  readonly onSelect: (trackId: string) => void;
  /** Radio group name, so two selectors on one page do not collide. */
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
  const anyOpenF1 = tracks.some((track) => needsOpenF1Attribution(track.geometry_provenance));

  return (
    <div>
      <ul className={styles.optionList} aria-label="Registered circuits">
        {tracks.map((track) => {
          const state = selectability(track);
          const reasonId = `circuit-${track.track_id}-reason`;
          const hash = shortHash(track.package_hash);
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
                  <span>{track.display_name ?? track.track_id}</span>
                  <span className={styles.optionId}>{track.track_id}</span>
                  <StatusBadge label="Readiness rung" tone={readinessTone(track.readiness)}>
                    {track.readiness ?? track.readiness_reported ?? 'no rung reported'}
                  </StatusBadge>
                </label>

                <dl className={styles.factList}>
                  <Fact term="Geometry provenance">{provenanceText(track.geometry_provenance)}</Fact>
                  <Fact term="Package hash">
                    {hash === null ? (
                      <Unavailable>no compiled package</Unavailable>
                    ) : (
                      <span className={styles.hash}>{hash}</span>
                    )}
                  </Fact>
                  <Fact term="Corridor quality">{corridorText(track.corridor_quality)}</Fact>
                  <Fact term="Closure error">
                    {track.closure_error_m === null ? (
                      <Unavailable>not measured</Unavailable>
                    ) : (
                      `${track.closure_error_m.toExponential(1)} m`
                    )}
                  </Fact>
                  <Fact term="Length vs official">
                    {track.length_error_fraction === null ? (
                      <Unavailable>not measured</Unavailable>
                    ) : (
                      `${(track.length_error_fraction * 100).toFixed(3)} %`
                    )}
                  </Fact>
                  <Fact term="Official length">
                    {track.official_length_m === null ? (
                      <Unavailable>not retrieved</Unavailable>
                    ) : (
                      `${track.official_length_m.toFixed(0)} m${
                        track.official_length_verified ? '' : ' (unverified source)'
                      }`
                    )}
                  </Fact>
                </dl>

                {track.licence_labels.length === 0 ? null : (
                  <p className={styles.attribution}>
                    Source permissions: {track.licence_labels.join(' · ')}
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
