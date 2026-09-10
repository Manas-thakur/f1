import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import type { ApiError } from '@contracts';

import { guidanceFor, toApiError } from '@/api/errors';
import { useExperiment } from '@/api/queries';
import {
  DataTable,
  EmptyState,
  Notice,
  Panel,
  StatusBadge,
  type Column,
} from '@/components';
import { UNAVAILABLE_TEXT } from '@/contracts/units';
import { labClient, type LabClient } from '@/api/controlPlane';
import styles from '@/styles/workspace.module.css';
import {
  isUnmeasured,
  parseReportBundle,
  type ComparisonMatrixRow,
  type MatrixCoverageRow,
} from './reportTypes';

export interface ExperimentReportProps {
  readonly client?: LabClient;
}

const REPORT_ROUTE = 'GET /api/v1/experiments/{experiment_id}/report';

const REPORT_ROUTE_ABSENT =
  'The status route returns a server-side file path, and no route serves the report JSON.';

function reportUnavailableReason(error: ApiError | null, requested: boolean): string {
  if (!requested) {
    return `No experiment id is in the address, so ${REPORT_ROUTE} was never called and no report body was asked for.`;
  }
  if (error === null) {
    return `${REPORT_ROUTE} answered, but the body is not a benchmark report bundle this view can read. Nothing is substituted for it.`;
  }
  if (error.code === 'not_found') {
    return `${REPORT_ROUTE} is not implemented by this control plane: it answered ${error.code} — ${error.message} (request ${error.request_id}). ${REPORT_ROUTE_ABSENT}`;
  }
  return `${REPORT_ROUTE} failed: ${error.message} (${error.code}, request ${error.request_id}). ${REPORT_ROUTE_ABSENT}`;
}

const MATRIX_COLUMNS: readonly Column<ComparisonMatrixRow>[] = [
  { id: 'controller', header: 'Controller', cell: (row) => row.controller },
  { id: 'reference', header: 'Compared against', cell: (row) => row.reference ?? 'is the reference' },
  { id: 'purpose', header: 'Purpose', cell: (row) => row.purpose },
  {
    id: 'status',
    header: 'Evidence',
    cell: (row) =>
      isUnmeasured(row.status) ? (
        <>
          <StatusBadge label="Evidence state" tone="attention">
            unavailable
          </StatusBadge>
          <br />
          <span className="afterlap-small afterlap-muted">
            {row.reason ?? 'no reason recorded'}
          </span>
        </>
      ) : (
        <StatusBadge label="Evidence state" tone="verified">
          {row.status}
        </StatusBadge>
      ),
  },
  {
    id: 'difference',
    header: 'Paired difference',
    numeric: true,
    cell: (row) => {
      const comparison = row.comparison;
      if (comparison === null) {
        return `${UNAVAILABLE_TEXT} — no paired estimate was computed for this row`;
      }
      return `${comparison.difference_mean.toFixed(4)} ${comparison.unit}`;
    },
  },
  {
    id: 'interval',
    header: 'Interval',
    cell: (row) => {
      const comparison = row.comparison;
      if (comparison === null) {
        return UNAVAILABLE_TEXT;
      }
      return `${comparison.ci_low.toFixed(4)} to ${comparison.ci_high.toFixed(4)} ${comparison.unit} at ${(comparison.coverage * 100).toFixed(0)}% nominal coverage, ${comparison.scenario_count} scenarios × ${comparison.seed_count} seeds`;
    },
  },
];

const COVERAGE_COLUMNS: readonly Column<MatrixCoverageRow>[] = [
  { id: 'controller', header: 'Row', cell: (row) => row.controller },
  { id: 'actor', header: 'Uses actor', cell: (row) => (row.uses_actor ? 'yes' : 'no') },
  {
    id: 'return',
    header: 'Uses learned return',
    cell: (row) => (row.uses_learned_return ? 'yes' : 'no'),
  },
  {
    id: 'status',
    header: 'Status',
    cell: (row) => (
      <StatusBadge
        label="Row status"
        tone={isUnmeasured(row.status) ? 'attention' : 'verified'}
      >
        {isUnmeasured(row.status) ? 'unmeasured' : row.status}
      </StatusBadge>
    ),
  },
  { id: 'reason', header: 'Reason', cell: (row) => row.reason ?? 'measured in this run' },
  { id: 'owner', header: 'Owner', cell: (row) => row.owner },
];


export function ExperimentReport({ client = labClient }: ExperimentReportProps) {
  const { experimentId } = useParams();
  const jobQuery = useExperiment(experimentId);

  const reportQuery = useQuery({
    queryKey: ['experiments', experimentId ?? 'none', 'report'],
    queryFn: ({ signal }) => client.getExperimentReport(experimentId as string, { signal }),
    enabled: experimentId !== undefined,
    retry: false,
  });

  const bundle = reportQuery.data === undefined ? null : parseReportBundle(reportQuery.data);

  const job =
    jobQuery.data !== undefined && typeof jobQuery.data.job === 'object' && jobQuery.data.job !== null
      ? jobQuery.data
      : null;
  const jobError =
    jobQuery.error === null || jobQuery.error === undefined
      ? null
      : toApiError(jobQuery.error, 'experiment status unavailable');
  const reportError =
    reportQuery.error === null || reportQuery.error === undefined
      ? null
      : toApiError(reportQuery.error, 'report body unavailable');
  const reportPending = experimentId !== undefined && reportQuery.isPending;

  const matrix = bundle?.detail.comparison_matrix ?? [];
  const coverage = bundle?.detail.matrix_coverage ?? [];
  const population = bundle?.detail.population ?? null;

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Experiment report</h1>
          <p>
            The benchmark schema, what was measured, what was not, and the audit trail. Rows
            without evidence read as unavailable with their reason.
          </p>
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Job status" tone={job?.status === 'completed' ? 'verified' : 'neutral'}>
            {job?.status ?? 'unknown'}
          </StatusBadge>
          {job?.job.partial_results === true ? (
            <StatusBadge label="Result completeness" tone="attention">
              incomplete
            </StatusBadge>
          ) : null}
        </div>
      </div>

      {jobError === null ? null : (
        <Notice tone="failure" testId="job-error">
          {jobError.message} {guidanceFor(jobError) ?? ''} (request {jobError.request_id})
        </Notice>
      )}

      <Panel id="job" title="Job">
        {job === null ? (
          <p aria-busy={jobQuery.isPending || undefined}>
            {jobQuery.isPending ? 'Reading the job record…' : 'No job record is available.'}
          </p>
        ) : (
          <dl className={styles.definitionList}>
            <dt>Job id</dt>
            <dd>{job.job.id}</dd>
            <dt>Manifest hash</dt>
            <dd>{job.job.manifest_hash}</dd>
            <dt>Status</dt>
            <dd>{job.status}</dd>
            <dt>Progress</dt>
            <dd>
              {job.job.progress === undefined || job.job.progress === null
                ? UNAVAILABLE_TEXT
                : `${(job.job.progress * 100).toFixed(0)} %`}
            </dd>
            <dt>Partial results</dt>
            <dd>
              {job.job.partial_results === true
                ? 'yes — this run is incomplete and is excluded from headline aggregates'
                : 'no'}
            </dd>
            <dt>Report hash</dt>
            <dd>{job.job.report_hash ?? 'no report produced'}</dd>
            <dt>Report path</dt>
            <dd>{job.report_path ?? 'not recorded'}</dd>
            <dt>Failure</dt>
            <dd>{job.job.failure ?? 'none recorded'}</dd>
          </dl>
        )}
      </Panel>

      {reportPending ? (
        <Panel id="report" title="Benchmark report">
          <p aria-busy="true" className="afterlap-small afterlap-muted" data-testid="report-pending">
            Reading <span className="afterlap-mono">{REPORT_ROUTE}</span>… nothing is drawn until
            it answers.
          </p>
        </Panel>
      ) : bundle === null ? (
        <Panel id="report" title="Benchmark report">
          <EmptyState
            artefact="benchmark report body"
            heading="The report body is not available to this browser"
            reason={reportUnavailableReason(reportError, experimentId !== undefined)}
            action={
              <p className="afterlap-small afterlap-muted">
                This is an integration action, not a missing measurement: add a read route that
                serves the bundle A13 already writes under artifacts/reports. Nothing is
                substituted for it here.
              </p>
            }
          />
        </Panel>
      ) : (
        <>
          <Panel id="report" title="Benchmark report">
            <dl className={styles.definitionList}>
              <dt>Report id</dt>
              <dd>{bundle.report.id}</dd>
              <dt>Report hash</dt>
              <dd className={styles.hashText}>{bundle.report_hash}</dd>
              <dt>Evaluator / metrics</dt>
              <dd>
                {bundle.report.evaluator_version} · {bundle.report.metrics_version}
              </dd>
              <dt>Scenario family</dt>
              <dd>{bundle.report.scenario_family}</dd>
              <dt>Population</dt>
              <dd>
                {bundle.report.scenario_count} scenarios × {bundle.report.seed_count} seeds
                {population === null
                  ? ''
                  : ` · ${population.completed_runs ?? 0} completed, ${population.unavailable_runs ?? 0} unavailable, ${population.failed_runs ?? 0} failed of ${population.planned_units ?? 0} planned`}
              </dd>
              <dt>Withdrawn decisions</dt>
              <dd>{bundle.report.withdrawn_decisions ?? UNAVAILABLE_TEXT}</dd>
              <dt>Modelled violations</dt>
              <dd>{bundle.report.modelled_violations ?? UNAVAILABLE_TEXT}</dd>
              <dt>Decision latency p50 / p95 / p99</dt>
              <dd>
                {[
                  bundle.report.latency_p50_ms,
                  bundle.report.latency_p95_ms,
                  bundle.report.latency_p99_ms,
                ]
                  .map((value) =>
                    value === null || value === undefined ? UNAVAILABLE_TEXT : `${value.toFixed(1)} ms`,
                  )
                  .join(' / ')}
              </dd>
              <dt>Hardware</dt>
              <dd>{bundle.report.hardware ?? UNAVAILABLE_TEXT}</dd>
              <dt>Rerun command</dt>
              <dd className={styles.hashText}>{bundle.report.rerun_command ?? 'not recorded'}</dd>
              <dt>Certification</dt>
              <dd>{bundle.detail.certification ?? 'not claimed'}</dd>
            </dl>
          </Panel>

          <Panel id="matrix" title="Comparison matrix">
            <DataTable
              caption="Comparison matrix rows"
              description="Every required row, measured or not. A row with no number is unavailable, with the reason the report gives."
              columns={MATRIX_COLUMNS}
              rows={[...matrix]}
              rowKey={(row) => row.controller}
              emptyArtefact="comparison matrix row"
            />
            <Notice tone="attention" testId="no-win-rate">
              No win rate, success percentage or aggregate score is computed on this screen. The
              report does not contain one, and deriving one from rows that are unmeasured would
              manufacture the claim the report declines to make.
            </Notice>
          </Panel>

          <Panel id="coverage" title="Matrix coverage">
            <DataTable
              caption="Required matrix rows"
              description="Which of the required rows this benchmark could measure, and why the others could not."
              columns={COVERAGE_COLUMNS}
              rows={[...coverage]}
              rowKey={(row) => row.controller}
              emptyArtefact="matrix coverage row"
            />
          </Panel>

          <Panel id="notes" title="Report notes">
            {(bundle.report.notes ?? []).length === 0 ? (
              <p className="afterlap-small afterlap-muted">The report records no notes.</p>
            ) : (
              <ul className={styles.inlineList}>
                {(bundle.report.notes ?? []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
            <h3>Calibration</h3>
            {(bundle.report.calibration ?? []).length === 0 ? (
              <p className="afterlap-small afterlap-muted">
                No probability calibration was assessed. Unmeasured, not perfect.
              </p>
            ) : (
              <ul className={styles.inlineList}>
                {(bundle.report.calibration ?? []).map((entry) => (
                  <li key={entry.event_definition}>
                    {entry.event_definition}: {entry.status}
                    {entry.brier_score === null || entry.brier_score === undefined
                      ? ''
                      : ` · Brier ${entry.brier_score.toFixed(4)}`}
                  </li>
                ))}
              </ul>
            )}
            <h3>Failures by category</h3>
            {Object.keys(bundle.report.failures_by_category ?? {}).length === 0 ? (
              <p className="afterlap-small afterlap-muted">No failure was categorised.</p>
            ) : (
              <ul className={styles.inlineList}>
                {Object.entries(bundle.report.failures_by_category ?? {}).map(([name, count]) => (
                  <li key={name}>
                    {name}: {count}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
