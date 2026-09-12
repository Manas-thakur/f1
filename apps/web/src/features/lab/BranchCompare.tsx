import { useCallback, useState } from 'react';
import type { ApiError, SnapshotReference, TreatmentSpec } from '@contracts';

import { newIdempotencyKey } from '@/api/client';
import { guidanceFor, toApiError } from '@/api/errors';
import {
  Button,
  DataTable,
  EmptyState,
  Field,
  Notice,
  Panel,
  StatusBadge,
  type Column,
} from '@/components';
import { labClient, type LabClient } from '@/api/controlPlane';
import { useSessionStore } from '@/state/sessionStore';
import { ALIGNMENT_LABEL } from '@/state/types';
import type { SubmittedExperiment } from './ExperimentJobs';
import styles from '@/styles/workspace.module.css';

export interface BranchCompareProps {
  readonly sessionId: string;
  readonly client?: LabClient;
  
  readonly snapshots: readonly SnapshotReference[];
  readonly onSnapshotCreated: (snapshot: SnapshotReference) => void;
  
  readonly onExperimentCreated: (
    experimentId: string,
    submission: SubmittedExperiment,
  ) => void;
}

interface BranchRow {
  readonly treatmentId: string;
  readonly controller: string;
  readonly bundle: string;
  readonly outcome: string;
  readonly reason: string;
}

const BRANCH_COLUMNS: readonly Column<BranchRow>[] = [
  { id: 'treatment', header: 'Treatment', cell: (row) => row.treatmentId },
  { id: 'controller', header: 'Controller', cell: (row) => row.controller },
  { id: 'bundle', header: 'Model bundle', cell: (row) => row.bundle },
  {
    id: 'outcome',
    header: 'Checkpoint outcome',
    cell: (row) => (
      <>
        <StatusBadge label="Outcome">{row.outcome}</StatusBadge>
        <br />
        <span className="afterlap-small afterlap-muted">{row.reason}</span>
      </>
    ),
  },
];

function parseSeeds(text: string): { seeds: readonly number[]; error: string | null } {
  const parts = text
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter((part) => part !== '');
  if (parts.length === 0) {
    return { seeds: [], error: 'At least one disturbance seed is required.' };
  }
  const seeds: number[] = [];
  for (const part of parts) {
    const value = Number(part);
    if (!Number.isInteger(value) || value < 0) {
      return { seeds: [], error: `"${part}" is not a non-negative integer seed.` };
    }
    seeds.push(value);
  }
  if (new Set(seeds).size !== seeds.length) {
    return { seeds: [], error: 'Seeds must be distinct; a repeated seed is not a second sample.' };
  }
  return { seeds, error: null };
}


export function BranchCompare({
  sessionId,
  client = labClient,
  snapshots,
  onSnapshotCreated,
  onExperimentCreated,
}: BranchCompareProps) {
  const cursorAxis = useSessionStore((s) => s.view.cursorAxis);
  const setCursorAxis = useSessionStore((s) => s.setCursorAxis);

  const [snapshotLabel, setSnapshotLabel] = useState('');
  const [snapshotPending, setSnapshotPending] = useState(false);
  const [snapshotError, setSnapshotError] = useState<ApiError | null>(null);

  const [selectedSnapshot, setSelectedSnapshot] = useState('');
  const [referenceController, setReferenceController] = useState('legal_fixed_schedule');
  const [candidateController, setCandidateController] = useState('mpc_only');
  const [candidateBundle, setCandidateBundle] = useState('');
  const [seedText, setSeedText] = useState('1, 2, 3, 4');
  const [evaluatorVersion, setEvaluatorVersion] = useState('evaluator-v1');
  const [horizon, setHorizon] = useState('30');
  const [experimentPending, setExperimentPending] = useState(false);
  const [experimentError, setExperimentError] = useState<ApiError | null>(null);
  const [lastJobId, setLastJobId] = useState<string | null>(null);

  const seedParse = parseSeeds(seedText);
  const horizonSeconds = Number(horizon);
  const horizonValid = Number.isFinite(horizonSeconds) && horizonSeconds > 0;
  const snapshotChoice = selectedSnapshot === '' ? (snapshots[0]?.snapshot_id ?? '') : selectedSnapshot;
  const treatmentsDistinct = referenceController.trim() !== candidateController.trim();

  const createSnapshot = useCallback(async () => {
    setSnapshotPending(true);
    setSnapshotError(null);
    try {
      const response = await client.createSnapshot(
        sessionId,
        { label: snapshotLabel === '' ? null : snapshotLabel },
        { idempotencyKey: newIdempotencyKey() },
      );
      onSnapshotCreated(response.snapshot);
      setSelectedSnapshot(response.snapshot.snapshot_id);
    } catch (caught: unknown) {
      setSnapshotError(toApiError(caught, 'snapshot could not be created'));
    } finally {
      setSnapshotPending(false);
    }
  }, [client, onSnapshotCreated, sessionId, snapshotLabel]);

  const launch = useCallback(async () => {
    setExperimentPending(true);
    setExperimentError(null);
    const treatments: readonly TreatmentSpec[] = [
      {
        treatment_id: 'reference',
        controller: referenceController.trim(),
        description: 'Reference arm of the paired comparison.',
      },
      {
        treatment_id: 'candidate',
        controller: candidateController.trim(),
        ...(candidateBundle.trim() === '' ? {} : { model_bundle_id: candidateBundle.trim() }),
        description: 'Candidate arm, same scenario and same disturbance seeds.',
      },
    ];
    try {
      const response = await client.createExperiment(
        {
          snapshot_id: snapshotChoice,
          treatments: [...treatments],
          seeds: [...seedParse.seeds],
          evaluator_version: evaluatorVersion.trim(),
          evaluation_horizon_s: horizonSeconds,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      setLastJobId(response.job.id);
      onExperimentCreated(response.job.id, {
        seeds: [...seedParse.seeds],
        evaluatorVersion: evaluatorVersion.trim(),
        treatmentIds: treatments.map((treatment) => treatment.treatment_id),
        snapshotId: snapshotChoice,
      });
    } catch (caught: unknown) {
      setExperimentError(toApiError(caught, 'experiment could not be queued'));
    } finally {
      setExperimentPending(false);
    }
  }, [
    candidateBundle,
    candidateController,
    client,
    evaluatorVersion,
    horizonSeconds,
    onExperimentCreated,
    referenceController,
    seedParse.seeds,
    snapshotChoice,
  ]);

  const canLaunch =
    snapshotChoice !== '' &&
    seedParse.error === null &&
    horizonValid &&
    treatmentsDistinct &&
    evaluatorVersion.trim() !== '';

  const branchRows: readonly BranchRow[] = [
    {
      treatmentId: 'reference',
      controller: referenceController,
      bundle: 'none',
      outcome: 'unmeasured',
      reason: 'No branch outcome has been read back; see the note below.',
    },
    {
      treatmentId: 'candidate',
      controller: candidateController,
      bundle: candidateBundle === '' ? 'none' : candidateBundle,
      outcome: 'unmeasured',
      reason: 'No branch outcome has been read back; see the note below.',
    },
  ];

  return (
    <div className={styles.stack}>
      <Panel id="snapshot" title="Snapshot">
        <p className="afterlap-small afterlap-muted">
          A snapshot is the complete backend state at an event boundary. Every branch below starts
          from the same one, which is what makes the comparison a comparison.
        </p>
        <div className={styles.formGrid}>
          <Field label="Snapshot label" hint="Optional. Recorded with the snapshot reference.">
            <input
              type="text"
              maxLength={120}
              value={snapshotLabel}
              onChange={(event) => setSnapshotLabel(event.target.value)}
            />
          </Field>
        </div>
        <div className={styles.controlRow}>
          <Button
            variant="primary"
            state={snapshotPending ? 'pending' : 'default'}
            pendingLabel="Requesting…"
            onClick={() => void createSnapshot()}
          >
            Create snapshot
          </Button>
        </div>

        {snapshotError === null ? null : (
          <Notice tone="failure" live testId="snapshot-error">
            {snapshotError.message} {guidanceFor(snapshotError) ?? ''}
          </Notice>
        )}

        {snapshots.length === 0 ? (
          <EmptyState
            artefact="snapshot reference"
            heading="No snapshot has been taken in this view"
            reason="Snapshots created here are listed below with the hash the server returned. The control plane exposes no route that lists a session's existing snapshots, so earlier ones cannot be shown."
          />
        ) : (
          <ul className={styles.inlineList}>
            {snapshots.map((snapshot) => (
              <li key={snapshot.snapshot_id}>
                <span className="afterlap-mono">{snapshot.snapshot_id}</span> ·{' '}
                {snapshot.session_time_s.toFixed(2)} s · {snapshot.label ?? 'no label'}
                <br />
                <span className={styles.hashText}>hash {snapshot.snapshot_hash}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel id="compare" title="Compare scenario treatments">
        <fieldset className={styles.fieldset}>
          <legend>Paired treatments</legend>
          <div className={styles.formGrid}>
            <Field
              label="Snapshot id"
              hint="Records provenance. Trials restart from the scenario and seed; snapshot restoration is unavailable."
            >
              <input
                type="text"
                value={snapshotChoice}
                onChange={(event) => setSelectedSnapshot(event.target.value)}
              />
            </Field>
            <Field label="Reference controller">
              <input
                type="text"
                value={referenceController}
                onChange={(event) => setReferenceController(event.target.value)}
              />
            </Field>
            <Field
              label="Candidate controller"
              state={treatmentsDistinct ? 'default' : 'error'}
              errorMessage="The candidate must differ from the reference; comparing a controller with itself measures only seed noise."
            >
              <input
                type="text"
                value={candidateController}
                onChange={(event) => setCandidateController(event.target.value)}
              />
            </Field>
            <Field
              label="Candidate model bundle"
              hint="Learned bundles are unavailable in batch experiments. Leave this empty."
            >
              <input
                type="text"
                value={candidateBundle}
                onChange={(event) => setCandidateBundle(event.target.value)}
              />
            </Field>
            <Field
              label="Disturbance seeds"
              hint="Applied identically to both branches, which is what pairs them."
              state={seedParse.error === null ? 'default' : 'error'}
              {...(seedParse.error === null ? {} : { errorMessage: seedParse.error })}
            >
              <input
                type="text"
                value={seedText}
                onChange={(event) => setSeedText(event.target.value)}
              />
            </Field>
            <Field label="Evaluator version">
              <input
                type="text"
                value={evaluatorVersion}
                onChange={(event) => setEvaluatorVersion(event.target.value)}
              />
            </Field>
            <Field
              label="Evaluation horizon"
              hint="Seconds of simulated time each branch runs."
              state={horizonValid ? 'default' : 'error'}
              errorMessage="The horizon must be a positive number of seconds."
            >
              <input
                type="number"
                min="0.1"
                step="0.1"
                value={horizon}
                onChange={(event) => setHorizon(event.target.value)}
              />
            </Field>
          </div>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>Alignment</legend>
          <p className="afterlap-small afterlap-muted">
            Branches are compared at {ALIGNMENT_LABEL[cursorAxis]}. The choice is stated on every
            comparison, because a lead at common distance is not a lead at common time.
          </p>
          <div className={styles.controlRow}>
            {(['progress_m', 'session_time_s'] as const).map((axis) => (
              <label key={axis}>
                <input
                  type="radio"
                  name="alignment"
                  value={axis}
                  checked={cursorAxis === axis}
                  onChange={() => setCursorAxis(axis)}
                />{' '}
                {ALIGNMENT_LABEL[axis]}
              </label>
            ))}
          </div>
        </fieldset>

        <div className={styles.controlRow}>
          <Button
            variant="primary"
            state={experimentPending ? 'pending' : canLaunch ? 'default' : 'disabled'}
            pendingLabel="Queueing…"
            {...(canLaunch || experimentPending
              ? {}
              : {
                  disabledReason:
                    snapshotChoice === ''
                      ? 'Create or name a snapshot first; a branch has to start somewhere definite.'
                      : 'Fix the highlighted fields before queueing the paired run.',
                })}
            onClick={() => void launch()}
          >
            Queue paired experiment
          </Button>
        </div>

        {lastJobId === null ? null : (
          <Notice live testId="experiment-queued">
            Queued experiment <span className="afterlap-mono">{lastJobId}</span>. Queued is not
            finished: the job list below carries its real status.
          </Notice>
        )}

        {experimentError === null ? null : (
          <Notice tone="failure" live testId="experiment-error">
            {experimentError.message} {guidanceFor(experimentError) ?? ''}
          </Notice>
        )}

        <DataTable
          caption="Branch outcomes"
          description={`Aligned at ${ALIGNMENT_LABEL[cursorAxis]}.`}
          columns={BRANCH_COLUMNS}
          rows={branchRows}
          rowKey={(row) => row.treatmentId}
        />

        <Notice tone="attention" testId="branch-outcome-unavailable">
          Branch trajectories, checkpoint outcomes and constraint results are unmeasured here, not
          zero. `GET /experiments/{'{id}'}` returns a server-side file path for the report and no
          route serves the report body, so the browser cannot read what a finished run produced.
          This is a named integration action, not a missing number.
        </Notice>
      </Panel>
    </div>
  );
}
