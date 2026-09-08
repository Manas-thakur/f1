import type { ModelManifest } from '@contracts';

import { guidanceFor, toApiError } from '@/api/errors';
import { useModels } from '@/api/queries';
import {
  DataTable,
  Notice,
  Panel,
  StatusBadge,
  type Column,
  type DataTableState,
} from '@/components';
import { UNAVAILABLE_TEXT } from '@/contracts/units';
import styles from '../engineer/workspace.module.css';

function approvalTone(status: ModelManifest['approval_status']) {
  if (status === 'approved') {return 'verified' as const;}
  if (status === 'rejected') {return 'failure' as const;}
  if (status === 'candidate') {return 'attention' as const;}
  return 'neutral' as const;
}


export function approvalIsSupported(model: ModelManifest): boolean {
  if (model.approval_status !== 'approved') {
    return true;
  }
  return typeof model.benchmark_report_hash === 'string' && model.benchmark_report_hash !== '';
}

const COLUMNS: readonly Column<ModelManifest>[] = [
  {
    id: 'id',
    header: 'Bundle',
    cell: (row) => (
      <>
        <span className="afterlap-mono">{row.id}</span>
        <br />
        <span className="afterlap-small afterlap-muted">{row.algorithm}</span>
      </>
    ),
  },
  {
    id: 'approval',
    header: 'Approval state',
    cell: (row) => (
      <>
        <StatusBadge label="Approval state" tone={approvalTone(row.approval_status)}>
          {row.approval_status ?? 'unevaluated'}
        </StatusBadge>
        {approvalIsSupported(row) ? null : (
          <>
            <br />
            <span className="afterlap-small afterlap-muted">
              approved with no benchmark report referenced — the record does not support the state
            </span>
          </>
        )}
      </>
    ),
  },
  {
    id: 'evidence',
    header: 'Benchmark evidence',
    cell: (row) =>
      row.benchmark_report_hash === null || row.benchmark_report_hash === undefined ? (
        <>
          {UNAVAILABLE_TEXT}
          <br />
          <span className="afterlap-small afterlap-muted">no report hash recorded</span>
        </>
      ) : (
        <span className={styles.hashText}>{row.benchmark_report_hash}</span>
      ),
  },
  { id: 'family', header: 'Rule family', cell: (row) => row.rule_family },
  { id: 'reward', header: 'Reward revision', cell: (row) => row.reward_revision },
  {
    id: 'support',
    header: 'Support thresholds',
    cell: (row) => {
      const thresholds = row.support_thresholds ?? null;
      if (thresholds === null) {
        return `${UNAVAILABLE_TEXT} — no support envelope declared`;
      }
      return (
        <span className="afterlap-mono afterlap-small">
          disagreement ≤ {thresholds.max_ensemble_disagreement} · clip ≤{' '}
          {thresholds.max_clip_fraction} · known mask ≥ {thresholds.min_known_mask_fraction}
        </span>
      );
    },
  },
  {
    id: 'promotion',
    header: 'Promotion policy',
    cell: (row) => {
      const policy = row.promotion_policy ?? null;
      if (policy === null) {
        return 'none declared';
      }
      return (
        <span className="afterlap-small">
          {policy.enabled === true ? 'enabled' : 'disabled'}
          {policy.benefit_metric === null || policy.benefit_metric === undefined
            ? ''
            : ` · ${policy.benefit_metric}`}
          {policy.minimum_benefit === null || policy.minimum_benefit === undefined
            ? ''
            : ` ≥ ${policy.minimum_benefit}`}
          {policy.frozen_at === null || policy.frozen_at === undefined
            ? ' · not frozen'
            : ` · frozen ${policy.frozen_at}`}
        </span>
      );
    },
  },
  {
    id: 'hashes',
    header: 'Weights / features',
    cell: (row) => (
      <span className={styles.hashText}>
        {row.weights_hash}
        <br />
        {row.feature_schema_hash}
      </span>
    ),
  },
  { id: 'created', header: 'Created', cell: (row) => row.created_at },
];


export function ModelsView() {
  const query = useModels();
  const models = query.data?.models ?? [];
  const error =
    query.error === null || query.error === undefined
      ? null
      : toApiError(query.error, 'models unavailable');

  const state: DataTableState = query.isPending
    ? 'pending'
    : query.isError
      ? 'error'
      : models.length === 0
        ? 'empty'
        : 'ready';

  const approved = models.filter((model) => model.approval_status === 'approved');
  const unsupported = approved.filter((model) => !approvalIsSupported(model));

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Models</h1>
          <p>
            Candidate and approved model bundles, distinguished by measured benchmark results. A
            bundle is a candidate until a report says otherwise.
          </p>
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Approved count" tone={approved.length > 0 ? 'verified' : 'neutral'}>
            {approved.length} approved
          </StatusBadge>
          <StatusBadge label="Listed count">{models.length} listed</StatusBadge>
        </div>
      </div>

      {error === null ? null : (
        <Notice tone="failure" testId="models-error">
          {error.message} {guidanceFor(error) ?? ''} (request {error.request_id})
        </Notice>
      )}

      <Panel id="models" title="Model bundles">
        <DataTable
          caption="Registered model bundles"
          description="Immutable manifests as the control plane records them."
          columns={COLUMNS}
          rows={[...models]}
          rowKey={(row) => row.id}
          state={state}
          errorMessage="The model list could not be read from the control plane."
          emptyArtefact="model manifest"
          emptyAction={
            <p className="afterlap-small afterlap-muted">
              No model bundle has been registered. No trained bundle exists in this build, which is
              why the learned rows of the comparison matrix read as unmeasured.
            </p>
          }
        />

        {unsupported.length === 0 ? null : (
          <Notice tone="failure" testId="unsupported-approval">
            {unsupported.length} bundle(s) are marked approved with no benchmark report referenced.
            That state is not supported by evidence in the record.
          </Notice>
        )}

        <Notice tone="attention" testId="no-promotion">
          Promotion is not performed from this screen. There is no promotion route in the control
          plane, no automatic promotion exists anywhere in the product, and a bundle never becomes
          approved because a label changed.
        </Notice>
      </Panel>
    </div>
  );
}
