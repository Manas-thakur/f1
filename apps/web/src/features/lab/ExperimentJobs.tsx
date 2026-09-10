import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import type { ApiError, ExperimentStatusResponse } from '@contracts';
import Link from 'next/link';

import { newIdempotencyKey } from '@/api/client';
import { guidanceFor, toApiError } from '@/api/errors';
import {
  Button,
  DataTable,
  Notice,
  Panel,
  StatusBadge,
  type Column,
  type DataTableState,
} from '@/components';
import { UNAVAILABLE_TEXT } from '@/contracts/units';
import { labClient, type LabClient } from '@/api/controlPlane';
import styles from '@/styles/workspace.module.css';


export interface SubmittedExperiment {
  readonly seeds: readonly number[];
  readonly evaluatorVersion: string;
  readonly treatmentIds: readonly string[];
  readonly snapshotId: string;
}

export interface ExperimentJobsProps {
  readonly client?: LabClient;
  readonly submitted: Readonly<Record<string, SubmittedExperiment>>;
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

function statusTone(status: string) {
  if (status === 'completed') {return 'verified' as const;}
  if (status === 'failed') {return 'failure' as const;}
  if (status === 'cancelled') {return 'attention' as const;}
  if (status === 'running') {return 'selection' as const;}
  return 'neutral' as const;
}


export function ExperimentJobs({ client = labClient, submitted }: ExperimentJobsProps) {
  const queryClient = useQueryClient();
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const query = useQuery({
    queryKey: ['experiments', 'list'],
    queryFn: ({ signal }) => client.listExperiments({ limit: 25 }, { signal }),
    refetchInterval: 5_000,
  });

  const cancel = useCallback(
    async (jobId: string) => {
      setCancelling(jobId);
      setError(null);
      try {
        await client.cancelExperiment(
          jobId,
          { reason: 'cancelled from the simulation lab' },
          { idempotencyKey: newIdempotencyKey() },
        );
        await queryClient.invalidateQueries({ queryKey: ['experiments', 'list'] });
      } catch (caught: unknown) {
        setError(toApiError(caught, 'the job could not be cancelled'));
      } finally {
        setCancelling(null);
      }
    },
    [client, queryClient],
  );

  const columns: readonly Column<ExperimentStatusResponse>[] = [
    {
      id: 'id',
      header: 'Job',
      cell: (row) => (
        <>
          <Link href={`/experiments/${row.job.id}/report`}>{row.job.id}</Link>
          <br />
          <span className={styles.hashText}>manifest {row.job.manifest_hash}</span>
        </>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (row) => (
        <>
          <StatusBadge label="Job status" tone={statusTone(row.status)}>
            {row.status}
          </StatusBadge>
          {row.job.partial_results === true ? (
            <>
              {' '}
              <StatusBadge label="Result completeness" tone="attention">
                incomplete
              </StatusBadge>
            </>
          ) : null}
        </>
      ),
    },
    {
      id: 'progress',
      header: 'Progress',
      numeric: true,
      cell: (row) =>
        row.job.progress === undefined || row.job.progress === null
          ? UNAVAILABLE_TEXT
          : `${(row.job.progress * 100).toFixed(0)} %`,
    },
    {
      id: 'seeds',
      header: 'Seeds',
      cell: (row) => {
        const record = submitted[row.job.id];
        if (record === undefined) {
          return (
            <>
              {UNAVAILABLE_TEXT}
              <br />
              <span className="afterlap-small afterlap-muted">
                the status response carries a manifest hash, not the manifest
              </span>
            </>
          );
        }
        return (
          <>
            {record.seeds.length} paired
            <br />
            <span className="afterlap-mono afterlap-small">{record.seeds.join(', ')}</span>
          </>
        );
      },
    },
    {
      id: 'family',
      header: 'Scenario family',
      cell: (row) => {
        const record = submitted[row.job.id];
        return record === undefined ? (
          UNAVAILABLE_TEXT
        ) : (
          <span className="afterlap-mono afterlap-small">from snapshot {record.snapshotId}</span>
        );
      },
    },
    {
      id: 'evaluator',
      header: 'Evaluator revision',
      cell: (row) => submitted[row.job.id]?.evaluatorVersion ?? UNAVAILABLE_TEXT,
    },
    {
      id: 'report',
      header: 'Report',
      cell: (row) =>
        row.job.report_hash === null || row.job.report_hash === undefined ? (
          <span className="afterlap-small afterlap-muted">no report produced</span>
        ) : (
          <span className={styles.hashText}>{row.job.report_hash}</span>
        ),
    },
    {
      id: 'failure',
      header: 'Outcome detail',
      cell: (row) => row.job.failure ?? 'none recorded',
    },
    {
      id: 'cancel',
      header: 'Cancel',
      cell: (row) => (
        <Button
          variant="quiet"
          state={
            cancelling === row.job.id
              ? 'pending'
              : TERMINAL.has(row.status)
                ? 'disabled'
                : 'default'
          }
          pendingLabel="Cancelling…"
          {...(TERMINAL.has(row.status)
            ? { disabledReason: `Job is ${row.status}; a terminal job cannot be cancelled.` }
            : {})}
          onClick={() => void cancel(row.job.id)}
        >
          Cancel
        </Button>
      ),
    },
  ];

  const rows = query.data ?? [];
  const state: DataTableState = query.isPending
    ? 'pending'
    : query.isError
      ? 'error'
      : rows.length === 0
        ? 'empty'
        : 'ready';

  return (
    <Panel id="experiments" title="Experiment jobs">
      <DataTable
        caption="Experiment job queue"
        description="Batch runs queued against a snapshot. Cancellation keeps whatever finished and marks it incomplete."
        columns={columns}
        rows={[...rows]}
        rowKey={(row) => row.job.id}
        state={state}
        errorMessage="The experiment queue could not be read from the control plane."
        emptyArtefact="experiment job"
        emptyAction={
          <p className="afterlap-small afterlap-muted">
            Queue one with “Compare from here”. Nothing is listed until the control plane has a
            job.
          </p>
        }
      />

      {error === null ? null : (
        <Notice tone="failure" live testId="cancel-error">
          {error.message} {guidanceFor(error) ?? ''}
        </Notice>
      )}

      <Notice tone="attention">
        A cancelled job with progress is stored with partial results and is excluded from headline
        benchmark aggregates. Partial output is labelled incomplete rather than dropped.
      </Notice>
    </Panel>
  );
}
