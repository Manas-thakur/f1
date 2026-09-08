import { EmptyState, Notice, Panel, StatusBadge } from '@/components';
import {
  catalogueFailureText,
  trackCatalogueClient,
  type TrackCatalogueClient,
} from '@/api/trackCatalogue';
import {
  useConditionsCatalogue,
  useTrackCatalogue,
  useTrackCentreline,
} from '@/api/trackQueries';
import { CircuitMap } from '../tracks/CircuitMap';
import { CircuitSelector } from '../tracks/CircuitSelector';
import { ConditionsSelector } from '../tracks/ConditionsSelector';
import {
  REAL_CIRCUIT_SYNTHETIC_ENERGY,
  SYNTHETIC_ENERGY_EXPLANATION,
  selectability,
  validatorNotes,
} from '../tracks/readiness';
import { useCircuitSelection } from './circuitSelection';
import styles from '../tracks/circuits.module.css';

export interface CircuitConfigurationProps {
  readonly client?: TrackCatalogueClient;
}

export function CircuitConfiguration({
  client = trackCatalogueClient,
}: CircuitConfigurationProps) {
  const trackId = useCircuitSelection((s) => s.trackId);
  const conditionsId = useCircuitSelection((s) => s.conditionsId);
  const selectTrack = useCircuitSelection((s) => s.selectTrack);
  const selectConditions = useCircuitSelection((s) => s.selectConditions);

  const tracksQuery = useTrackCatalogue(client);
  const centrelineQuery = useTrackCentreline(trackId, client);
  const conditionsQuery = useConditionsCatalogue(trackId, client);

  const catalogue = tracksQuery.data ?? null;
  const tracks = catalogue?.tracks ?? [];
  const conditions = conditionsQuery.data?.conditions ?? [];
  const selected = tracks.find((track) => track.track_id === trackId) ?? null;
  const selectedIsOffered = selected !== null && selectability(selected).selectable;

  return (
    <Panel
      id="circuit-configuration"
      title="Circuit and conditions"
      actions={
        <StatusBadge label="Energy fidelity" tone="attention">
          {REAL_CIRCUIT_SYNTHETIC_ENERGY}
        </StatusBadge>
      }
    >
      <Notice tone="attention" testId="circuit-config-label">
        {SYNTHETIC_ENERGY_EXPLANATION}
      </Notice>

      <h3>Circuit</h3>
      {tracksQuery.isPending ? (
        <p className="afterlap-small afterlap-muted">
          Reading the circuit catalogue from <span className="afterlap-mono">GET /api/v1/tracks</span>
          …
        </p>
      ) : tracksQuery.isError ? (
        <EmptyState
          artefact="circuit catalogue (GET /api/v1/tracks)"
          heading="The circuit catalogue is unavailable"
          reason={catalogueFailureText('GET /api/v1/tracks', tracksQuery.error)}
        >
          <p className="afterlap-small afterlap-muted">
            No circuit list is shipped in this bundle, so nothing is shown in its place. A run
            cannot be configured against a real circuit until this route answers.
          </p>
        </EmptyState>
      ) : tracks.length === 0 ? (
        <EmptyState
          artefact="registered circuits"
          heading="The catalogue is empty"
          reason="GET /api/v1/tracks answered with an empty list, so no circuit exists to configure."
        />
      ) : (
        <>
          <CircuitSelector tracks={tracks} selectedTrackId={trackId} onSelect={selectTrack} />
          <p className={styles.attribution}>
            {catalogue?.season === null || catalogue?.season === undefined
              ? 'The catalogue reported no season.'
              : `Season ${catalogue.season}${
                  catalogue.snapshot_date === null
                    ? ''
                    : `, registry snapshot ${catalogue.snapshot_date}`
                }.`}{' '}
            {catalogue?.minimum_readiness_to_drive === null ||
            catalogue?.minimum_readiness_to_drive === undefined
              ? 'The catalogue did not state the minimum readiness needed to drive the simulator, so this view applies its own floor of geometry_validated.'
              : `The control plane requires ${catalogue.minimum_readiness_to_drive} before a circuit may drive the simulator.`}
          </p>
          {catalogue?.notice === null || catalogue?.notice === undefined ? null : (
            <p className={styles.attribution}>{catalogue.notice}</p>
          )}
        </>
      )}

      {selected === null || validatorNotes(selected).length === 0 ? null : (
        <details data-testid="circuit-validator-evidence">
          <summary>
            Validator evidence for {selected.display_name ?? selected.track_id} (
            {validatorNotes(selected).length} recorded checks)
          </summary>
          <ul className={styles.withdrawnList}>
            {validatorNotes(selected).map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      )}

      <h3>Circuit map</h3>
      {trackId === null ? (
        <p className="afterlap-small afterlap-muted">
          Select a circuit to draw its compiled centreline. No outline is drawn before one is
          chosen, and none is drawn from artwork.
        </p>
      ) : !selectedIsOffered ? (
        <p className="afterlap-small afterlap-muted">
          The selected circuit is not offered, so no map is drawn for it.
        </p>
      ) : centrelineQuery.isPending ? (
        <p className="afterlap-small afterlap-muted">
          Reading{' '}
          <span className="afterlap-mono">GET /api/v1/tracks/{trackId}/centreline</span>…
        </p>
      ) : centrelineQuery.isError ? (
        <EmptyState
          artefact={`compiled centreline for ${trackId}`}
          heading="The circuit map is unavailable"
          reason={catalogueFailureText(
            `GET /api/v1/tracks/${trackId}/centreline`,
            centrelineQuery.error,
          )}
        >
          <p className="afterlap-small afterlap-muted">
            The map is drawn only from compiled package coordinates. There is no traced outline
            and no image asset to fall back to.
          </p>
        </EmptyState>
      ) : centrelineQuery.data === undefined ? null : (
        <CircuitMap
          centreline={centrelineQuery.data}
          displayName={selected?.display_name ?? null}
          readiness={selected?.readiness ?? null}
        />
      )}

      <h3>Conditions</h3>
      {trackId === null ? (
        <p className="afterlap-small afterlap-muted">
          Select a circuit first. A condition tape carries the venue's altitude and an absolute
          wind heading, so it is only meaningful bound to one circuit.
        </p>
      ) : conditionsQuery.isPending ? (
        <p className="afterlap-small afterlap-muted">
          Reading{' '}
          <span className="afterlap-mono">GET /api/v1/conditions</span>…
        </p>
      ) : conditionsQuery.isError ? (
        <EmptyState
          artefact={`condition tapes for ${trackId}`}
          heading="The conditions catalogue is unavailable"
          reason={catalogueFailureText('GET /api/v1/conditions', conditionsQuery.error)}
        >
          <p className="afterlap-small afterlap-muted">
            No tape is assumed. The session will be created without a conditions id, which the
            engine reads as the static reference environment.
          </p>
        </EmptyState>
      ) : conditions.length === 0 ? (
        <EmptyState
          artefact="condition tapes"
          heading="The conditions catalogue is empty"
          reason="GET /api/v1/conditions returned no tape at all. Nothing is substituted; a run would use the static reference environment."
        />
      ) : (
        <ConditionsSelector
          conditions={conditions}
          selectedConditionsId={conditionsId}
          onSelect={selectConditions}
          notice={conditionsQuery.data?.notice ?? null}
        />
      )}

      <p className={styles.attribution}>
        The circuit and tape chosen here travel to the control plane as{' '}
        <span className="afterlap-mono">track_id</span> and{' '}
        <span className="afterlap-mono">conditions_id</span> on{' '}
        <span className="afterlap-mono">POST /sessions</span>. The control plane resolves them; if
        it cannot, it rejects the request and the scenario panel shows the typed error rather than
        starting a run on something else.
      </p>
    </Panel>
  );
}
