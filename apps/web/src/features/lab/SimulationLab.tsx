import { useCallback, useState } from 'react';
import { useParams } from 'react-router';
import type { SnapshotReference } from '@contracts';

import { Notice, StatusBadge } from '@/components';
import { apiClient, type ApiClient } from '@/api/client';
import { useSessionStore } from '@/state/sessionStore';
import { useSessionRuntime, type SessionRuntimeOptions } from '../engineer/sessionRuntime';
import styles from '../engineer/workspace.module.css';
import { BranchCompare } from './BranchCompare';
import { ExperimentJobs, type SubmittedExperiment } from './ExperimentJobs';
import { RunControl } from './RunControl';
import { ScenarioPanel } from './ScenarioPanel';
import { labClient, type LabClient } from './controlPlane';

export interface SimulationLabProps {
  readonly runtimeOptions?: SessionRuntimeOptions;
  
  readonly client?: ApiClient;
  readonly labClientOverride?: LabClient;
}


export function SimulationLab({
  runtimeOptions,
  client = apiClient,
  labClientOverride = labClient,
}: SimulationLabProps) {
  const { sessionId } = useParams();
  const runtime = useSessionRuntime(sessionId, runtimeOptions ?? {});
  const manifest = useSessionStore((s) => s.server.manifest);

  const [snapshots, setSnapshots] = useState<readonly SnapshotReference[]>([]);
  const [submitted, setSubmitted] = useState<Readonly<Record<string, SubmittedExperiment>>>({});

  const onSnapshotCreated = useCallback((snapshot: SnapshotReference) => {
    setSnapshots((current) => [...current, snapshot]);
  }, []);

  const onExperimentCreated = useCallback(
    (experimentId: string, submission: SubmittedExperiment) => {
      setSubmitted((current) => ({ ...current, [experimentId]: submission }));
    },
    [],
  );

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Simulation lab</h1>
          <p>
            Configure a scenario, snapshot it, branch treatments from that snapshot and compare
            them. Every run started here is synthetic and is not evidence about a real car.
          </p>
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Data class" tone="attention">
            synthetic
          </StatusBadge>
          <StatusBadge label="Session mode">{manifest?.mode ?? 'no session'}</StatusBadge>
        </div>
      </div>

      <Notice tone="attention" testId="lab-synthetic-label">
        Synthetic laboratory. Physics, opponents and rule packs here are illustrative fixtures;
        nothing produced in this view is a measurement of a real car or evidence of compliance.
      </Notice>

      {runtime.snapshotError === null ? null : (
        <Notice tone="failure" testId="lab-snapshot-error">
          {runtime.snapshotError.message} (request {runtime.snapshotError.request_id})
        </Notice>
      )}

      <div className={styles.columns}>
        <div className={styles.stack}>
          {sessionId === undefined ? null : (
            <RunControl
              sessionId={sessionId}
              mode={manifest?.mode ?? null}
              client={client}
              refresh={runtime.refresh}
            />
          )}

          {sessionId === undefined ? null : (
            <BranchCompare
              sessionId={sessionId}
              client={labClientOverride}
              snapshots={snapshots}
              onSnapshotCreated={onSnapshotCreated}
              onExperimentCreated={onExperimentCreated}
            />
          )}

          <ExperimentJobs client={labClientOverride} submitted={submitted} />
        </div>

        <div className={styles.stack}>
          <ScenarioPanel client={labClientOverride} />
        </div>
      </div>
    </div>
  );
}
