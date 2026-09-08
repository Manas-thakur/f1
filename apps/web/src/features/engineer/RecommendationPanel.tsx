import { useState } from 'react';
import type { ExecutionEvent, OperatorAction, Recommendation } from '@contracts';

import {
  Button,
  EmptyState,
  Notice,
  Panel,
  StatusBadge,
  recommendationTone,
} from '@/components';
import { formatAge } from '@/contracts/units';
import type { ConsoleStatus } from './lifecycle';
import type { RecommendationActions } from './useRecommendationActions';
import styles from './workspace.module.css';

export interface RecommendationPanelProps {
  readonly recommendation: Recommendation | null;
  readonly status: ConsoleStatus;
  readonly sessionTimeS: number;
  readonly actions: RecommendationActions;
  
  readonly execution: ExecutionEvent | null;
  
  readonly readOnly: boolean;
  readonly onOpenEvidence: () => void;
  readonly evidenceButtonId: string;
  
  readonly timeSensitiveDisabledReason: string | null;
}

const ACTION_LABEL: Record<OperatorAction, string> = {
  select: 'Select',
  mark_communicated: 'Mark communicated',
  reject: 'Reject',
};

function expiryText(recommendation: Recommendation, sessionTimeS: number): string {
  const remaining = recommendation.expires_at_s - sessionTimeS;
  if (remaining <= 0) {
    return `expired ${Math.abs(remaining).toFixed(1)} s ago (at ${recommendation.expires_at_s.toFixed(1)} s)`;
  }
  return `${remaining.toFixed(1)} s remaining (at ${recommendation.expires_at_s.toFixed(1)} s)`;
}


export function RecommendationPanel({
  recommendation,
  status,
  sessionTimeS,
  actions,
  execution,
  readOnly,
  onOpenEvidence,
  evidenceButtonId,
  timeSensitiveDisabledReason,
}: RecommendationPanelProps) {
  const [reason, setReason] = useState('');

  if (recommendation === null || recommendation.action_code === 'withdraw_advice') {
    return (
      <Panel id="decision" title="Decision">
        <EmptyState
          artefact={status.missingArtefact ?? 'recommendation'}
          heading={status.heading}
          reason={status.detail}
          action={
            <p className="afterlap-small afterlap-muted">
              {recommendation === null
                ? 'Nothing is proposed for the current state revision. No instruction is shown because none exists.'
                : `The control plane published an explicit withdrawal (${(recommendation.reason_codes ?? []).join(', ') || 'no reason code'}). Advice is removed rather than relaxed.`}
            </p>
          }
        />
        <div className={styles.actions}>
          <Button id={evidenceButtonId} variant="quiet" onClick={onOpenEvidence}>
            Open evidence
          </Button>
        </div>
      </Panel>
    );
  }

  const pending = actions.pendingAction;
  const disabledReason = status.blockedReason ?? timeSensitiveDisabledReason;
  const canSelect = status.selectable && timeSensitiveDisabledReason === null && !readOnly;
  const canCommunicate =
    !readOnly &&
    timeSensitiveDisabledReason === null &&
    !status.expiredLocally &&
    recommendation.status === 'selected' &&
    pending === null;
  const canReject =
    !readOnly &&
    timeSensitiveDisabledReason === null &&
    (recommendation.status === 'proposed' || recommendation.status === 'selected') &&
    pending === null;

  return (
    <Panel id="decision" title="Decision">
      <div className={styles.badgeRow}>
        <StatusBadge label="Recommendation status" tone={recommendationTone(recommendation.status)}>
          {recommendation.status}
        </StatusBadge>
        <StatusBadge label="Action code">{recommendation.action_code}</StatusBadge>
        {status.expiredLocally ? (
          <StatusBadge label="Local expiry" tone="failure">
            past expiry
          </StatusBadge>
        ) : null}
        {recommendation.learned_contribution_enabled === true ? (
          <StatusBadge label="Learned contribution" tone="attention">
            learned contribution enabled
          </StatusBadge>
        ) : (
          <StatusBadge label="Learned contribution">
            baseline only ({recommendation.baseline_identity ?? 'unnamed baseline'})
          </StatusBadge>
        )}
      </div>

      <p className={styles.instruction}>{recommendation.display_text}</p>

      <dl className={styles.instructionMeta}>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Trigger</dt>
          <dd className={styles.metaValue}>
            {recommendation.trigger.description}
            {recommendation.trigger.progress_m === null ||
            recommendation.trigger.progress_m === undefined
              ? ''
              : ` · ${recommendation.trigger.progress_m.toFixed(0)} m`}
          </dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>End condition</dt>
          <dd className={styles.metaValue}>{recommendation.end_condition}</dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Validity</dt>
          <dd className={styles.metaValue}>{expiryText(recommendation, sessionTimeS)}</dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Observation cutoff</dt>
          <dd className={styles.metaValue}>
            {recommendation.observation_cutoff_s.toFixed(2)} s ·{' '}
            {formatAge(sessionTimeS - recommendation.observation_cutoff_s)}
          </dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Reason</dt>
          <dd className={styles.metaValue}>
            {(recommendation.reason_codes ?? []).length === 0
              ? 'no reason code published'
              : (recommendation.reason_codes ?? []).join(', ')}
          </dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Operator status</dt>
          <dd className={styles.metaValue}>
            {pending === null
              ? recommendation.status
              : `${ACTION_LABEL[pending]} in flight — awaiting server`}
          </dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Execution</dt>
          <dd className={styles.metaValue}>
            {execution === null
              ? 'not observed'
              : `${execution.observed_profile_id} · ${execution.match_status}`}
          </dd>
        </div>
        <div className={styles.metaItem}>
          <dt className={styles.metaLabel}>Ruleset / objective</dt>
          <dd className={styles.metaValue}>
            {recommendation.ruleset_hash} · {recommendation.objective_version}
          </dd>
        </div>
      </dl>

      {readOnly ? (
        <Notice tone="attention" testId="read-only-summary">
          Read-only summary. Operational commands are not offered at this width; open the console
          on a desktop-width screen to select, communicate or reject. Laboratory controls are on
          the lab route and are never mixed into this view.
        </Notice>
      ) : null}

      <div className={styles.actions}>
        <Button
          variant="primary"
          state={pending === 'select' ? 'pending' : canSelect ? 'default' : 'disabled'}
          pendingLabel="Sending select…"
          {...(canSelect || pending === 'select'
            ? {}
            : { disabledReason: disabledReason ?? 'Selection is not available.' })}
          onClick={() => void actions.submit('select')}
        >
          Select
        </Button>

        <Button
          state={pending === 'mark_communicated' ? 'pending' : canCommunicate ? 'default' : 'disabled'}
          pendingLabel="Sending…"
          {...(canCommunicate || pending === 'mark_communicated'
            ? {}
            : {
                disabledReason:
                  recommendation.status === 'proposed'
                    ? 'Communicated is a separate action taken after the server records the selection.'
                    : (disabledReason ??
                      `Status is "${recommendation.status}"; nothing to mark communicated.`),
              })}
          onClick={() => void actions.submit('mark_communicated')}
        >
          Mark communicated
        </Button>

        <Button
          variant="danger"
          state={pending === 'reject' ? 'pending' : canReject ? 'default' : 'disabled'}
          pendingLabel="Sending…"
          {...(canReject || pending === 'reject'
            ? {}
            : { disabledReason: disabledReason ?? 'There is nothing to reject.' })}
          onClick={() => void actions.submit('reject', reason)}
        >
          Reject
        </Button>

        <Button id={evidenceButtonId} variant="quiet" onClick={onOpenEvidence}>
          Open evidence
        </Button>
      </div>

      {readOnly ? null : (
        <p className={styles.metaItem}>
          <label className={styles.metaLabel} htmlFor="reject-reason">
            Rejection reason (brief, optional)
          </label>
          <input
            id="reject-reason"
            type="text"
            maxLength={140}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </p>
      )}

      {actions.outcome === null ? null : (
        <Notice
          live
          tone={actions.outcome.status === 'ok' ? 'info' : 'failure'}
          testId="action-outcome"
        >
          {actions.outcome.message}
          {actions.outcome.status === 'conflict'
            ? ' The evidence has been re-read; nothing was resubmitted.'
            : ''}
        </Notice>
      )}
    </Panel>
  );
}
