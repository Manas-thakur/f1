import type {
  ConstraintCheck,
  DecisionEvidenceResponse,
  IntervalValue,
  LearnedContribution,
  ProbabilityStatement,
  Recommendation,
  RecommendationAlternative,
  RuleContext,
} from '@contracts';

import {
  DataTable,
  Dialog,
  EmptyState,
  Notice,
  StatusBadge,
  checkTone,
  type Column,
} from '@/components';
import { UNAVAILABLE_TEXT, formatChannelValue } from '@/contracts/units';
import styles from '@/styles/workspace.module.css';

export interface EvidenceInspectorProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly evidence: DecisionEvidenceResponse | null;
  readonly loading: boolean;
  readonly errorMessage: string | null;
  
  readonly returnFocusTo: string;
}

function describeLearned(
  learned: LearnedContribution | null,
  enabled: boolean,
): string {
  if (learned === null) {
    return enabled ? 'enabled, but no learned record was published' : 'none offered';
  }
  if (!learned.enabled) {
    return `disabled — ${learned.baseline_identity} answered`;
  }
  const parts = [`enabled (${learned.bundle_id ?? 'unnamed bundle'})`];
  if (learned.continuation_value !== null && learned.continuation_value !== undefined) {
    parts.push(`continuation ${learned.continuation_value.toFixed(3)}`);
  } else {
    parts.push(`no continuation value (${learned.support_reason ?? 'out of support'})`);
  }
  if (learned.disagreement !== null && learned.disagreement !== undefined) {
    parts.push(`disagreement ${learned.disagreement.toFixed(3)}`);
  }
  return parts.join(' · ');
}

function describeInterval(interval: IntervalValue | null, unit: string): string {
  if (interval?.lower === null || interval?.upper === null || interval === null) {
    return UNAVAILABLE_TEXT;
  }
  return `${interval.lower.toFixed(2)}–${interval.upper.toFixed(2)} ${unit}`;
}

function formatScore(value: number | null | undefined): string {
  return value === null || value === undefined ? UNAVAILABLE_TEXT : value.toFixed(3);
}

const ALTERNATIVE_COLUMNS: readonly Column<RecommendationAlternative>[] = [
  { id: 'rank', header: 'Rank', numeric: true, cell: (row) => String(row.rank) },
  {
    id: 'plan',
    header: 'Plan',
    cell: (row) => (row.selected ? `${row.display_text} (recommended)` : row.display_text),
  },
  {
    id: 'status',
    header: 'Checker',
    cell: (row) => (
      <StatusBadge label="Checker verdict" tone={checkTone(row.constraint_status)}>
        {row.constraint_status}
      </StatusBadge>
    ),
  },
  { id: 'score', header: 'Score', numeric: true, cell: (row) => formatScore(row.final_score) },
  {
    id: 'benefit',
    header: 'Expected utility',
    numeric: true,
    cell: (row) => formatScore(row.expected_utility),
  },
  {
    id: 'downside',
    header: 'Tail loss',
    numeric: true,
    cell: (row) => formatScore(row.cvar_loss),
  },
  {
    id: 'energy',
    header: 'Future energy',
    numeric: true,
    cell: (row) => formatChannelValue('battery_energy_j', row.terminal_energy_j ?? null).text,
  },
  {
    id: 'switching',
    header: 'Switches',
    numeric: true,
    cell: (row) =>
      row.switch_count === null || row.switch_count === undefined
        ? UNAVAILABLE_TEXT
        : String(row.switch_count),
  },
  {
    id: 'reason',
    header: 'Why not recommended',
    cell: (row) => (row.selected ? '—' : (row.rejected_reason ?? UNAVAILABLE_TEXT)),
  },
];

const CHECK_COLUMNS: readonly Column<ConstraintCheck>[] = [
  { id: 'check', header: 'Check', cell: (row) => row.check_id },
  {
    id: 'status',
    header: 'Result',
    cell: (row) => (
      <StatusBadge label="Check result" tone={checkTone(row.status)}>
        {row.status}
      </StatusBadge>
    ),
  },
  {
    id: 'observed',
    header: 'Observed',
    numeric: true,
    cell: (row) =>
      row.observed === null || row.observed === undefined
        ? UNAVAILABLE_TEXT
        : `${row.observed} ${row.unit ?? ''}`.trim(),
  },
  {
    id: 'limit',
    header: 'Limit',
    numeric: true,
    cell: (row) =>
      row.limit === null || row.limit === undefined
        ? UNAVAILABLE_TEXT
        : `${row.limit} ${row.unit ?? ''}`.trim(),
  },
  {
    id: 'margin',
    header: 'Margin',
    numeric: true,
    cell: (row) =>
      row.margin === null || row.margin === undefined
        ? `${UNAVAILABLE_TEXT} — an unknown check reports no margin`
        : `${row.margin} ${row.unit ?? ''}`.trim(),
  },
  {
    id: 'where',
    header: 'At',
    cell: (row) =>
      row.at_progress_m === null || row.at_progress_m === undefined
        ? row.at_session_time_s === null || row.at_session_time_s === undefined
          ? UNAVAILABLE_TEXT
          : `${row.at_session_time_s.toFixed(2)} s`
        : `${row.at_progress_m.toFixed(0)} m`,
  },
  {
    id: 'source',
    header: 'Source',
    cell: (row) => {
      const references = row.references ?? [];
      if (references.length === 0) {
        return 'no source reference recorded';
      }
      return (
        <ul className={styles.inlineList}>
          {references.map((reference) => (
            <li key={`${reference.source_id}-${reference.article}`}>
              {reference.source_url === null || reference.source_url === undefined ? (
                <>
                  {reference.article} · {reference.source_id}
                </>
              ) : (
                <a href={reference.source_url} rel="noreferrer noopener" target="_blank">
                  {reference.article} · {reference.source_id}
                </a>
              )}
              {reference.reviewer === null || reference.reviewer === undefined
                ? ' · no reviewer recorded'
                : ` · reviewed by ${reference.reviewer}`}
            </li>
          ))}
        </ul>
      );
    },
  },
];

function ProbabilityRows({ items }: { readonly items: readonly ProbabilityStatement[] }) {
  if (items.length === 0) {
    return (
      <p className="afterlap-small afterlap-muted">
        The plan publishes no event forecast for this decision.
      </p>
    );
  }
  return (
    <ul className={styles.inlineList}>
      {items.map((item) => (
        <li key={`${item.event_definition}-${item.checkpoint_id ?? 'none'}`}>
          <span className="afterlap-mono">{item.event_definition}</span>:{' '}
          {item.value === null || item.value === undefined
            ? UNAVAILABLE_TEXT
            : `model frequency ${item.value.toFixed(2)}`}
          {item.sample_count === null || item.sample_count === undefined
            ? ''
            : ` from ${item.sample_count} scenario samples`}
          {' · calibration '}
          {item.calibration_status ?? 'unavailable'}
          {item.calibration_status === 'calibrated'
            ? ''
            : ' — not a calibrated probability, do not read it as one'}
        </li>
      ))}
    </ul>
  );
}


export function EvidenceInspector({
  open,
  onOpenChange,
  recommendation,
  ruleContext,
  evidence,
  loading,
  errorMessage,
  returnFocusTo,
}: EvidenceInspectorProps) {
  const subject = evidence?.recommendation ?? recommendation;
  const checks = subject?.constraint_result.checks ?? [];
  const unresolved = subject?.constraint_result.unresolved_conditions ?? [];
  const outcomes = subject?.outcomes ?? [];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Decision evidence"
      description={
        subject === null
          ? 'No decision is currently published.'
          : `Decision ${subject.id}, revision ${subject.revision}, against state revision ${subject.state_revision}.`
      }
      returnFocusTo={returnFocusTo}
    >
      {subject === null ? (
        <EmptyState
          artefact="decision evidence record"
          heading="No decision to inspect"
          reason="The control plane has published no recommendation for the current state revision, so there is no evidence record to read."
        />
      ) : (
        <div className={styles.stack}>
          {errorMessage === null ? null : (
            <Notice tone="failure" testId="evidence-error">
              {errorMessage}
            </Notice>
          )}
          {loading ? (
            <p aria-busy="true">Reading the decision record…</p>
          ) : null}

          <dl className={styles.definitionList}>
            <dt>Instruction</dt>
            <dd>{subject.display_text}</dd>
            <dt>Observed state revision</dt>
            <dd>{evidence?.estimate_revision ?? subject.state_revision}</dd>
            <dt>Observation cutoff</dt>
            <dd>{subject.observation_cutoff_s.toFixed(2)} s</dd>
            <dt>Valid window</dt>
            <dd>
              {subject.valid_from_s.toFixed(2)} s to {subject.expires_at_s.toFixed(2)} s
            </dd>
            <dt>Ruleset hash</dt>
            <dd>{subject.ruleset_hash}</dd>
            <dt>Model hash</dt>
            <dd>{subject.model_hash ?? 'no learned model bundle used'}</dd>
            <dt>Objective</dt>
            <dd>{subject.objective_version}</dd>
            <dt>Baseline identity</dt>
            <dd>{subject.baseline_identity ?? 'not recorded'}</dd>
            <dt>Planner</dt>
            <dd>{subject.planner_identity ?? 'not recorded'}</dd>
            <dt>Learned contribution</dt>
            <dd>{describeLearned(subject.learned ?? null, subject.learned_contribution_enabled ?? false)}</dd>
          </dl>

          {(subject.unavailable_reasons ?? []).length === 0 ? null : (
            <Notice tone="attention" testId="unavailable-reasons">
              Capabilities that did not contribute to this decision:{' '}
              {(subject.unavailable_reasons ?? []).join('; ')}.
            </Notice>
          )}

          <DataTable
            caption="Independent rule checks"
            description="Run by the constraint checker against the loaded pack, not by the planner that produced the plan."
            columns={CHECK_COLUMNS}
            rows={checks}
            rowKey={(row) => row.check_id}
            emptyArtefact="constraint check"
          />

          {unresolved.length === 0 ? null : (
            <Notice tone="attention" testId="unresolved-conditions">
              The checker could not resolve: {unresolved.join(', ')}. An unresolved condition is
              not a pass.
            </Notice>
          )}

          <h3>Predicted checkpoint outcomes</h3>
          {outcomes.length === 0 ? (
            <p className="afterlap-small afterlap-muted">
              The plan publishes no checkpoint outcome for this decision.
            </p>
          ) : (
            <ul className={styles.inlineList}>
              {outcomes.map((outcome) => (
                <li key={outcome.checkpoint_id}>
                  <span className="afterlap-mono">{outcome.checkpoint_id}</span> at{' '}
                  {outcome.progress_m.toFixed(0)} m · energy{' '}
                  {formatChannelValue('battery_energy_j', outcome.own_energy_j ?? null).text} ·
                  elapsed{' '}
                  {outcome.elapsed_time_s === null || outcome.elapsed_time_s === undefined
                    ? UNAVAILABLE_TEXT
                    : `${outcome.elapsed_time_s.toFixed(2)} s`}{' '}
                  · ahead of rival{' '}
                  {outcome.ahead_of_rival === null || outcome.ahead_of_rival === undefined
                    ? UNAVAILABLE_TEXT
                    : String(outcome.ahead_of_rival)}
                </li>
              ))}
            </ul>
          )}

          <h3>Event forecasts</h3>
          <ProbabilityRows items={subject.probabilities ?? []} />

          <h3>Outcome ranges across the scenario ensemble</h3>
          {(subject.outcome_ranges ?? []).length === 0 ? (
            <p className="afterlap-small afterlap-muted">
              No outcome range was published for this decision. A range needs scenario
              re-simulation; when it is off the reasons above say so.
            </p>
          ) : (
            <ul className={styles.inlineList} data-testid="outcome-ranges">
              {(subject.outcome_ranges ?? []).map((range) => (
                <li key={range.checkpoint_id}>
                  <span className="afterlap-mono">{range.checkpoint_id}</span> ·{' '}
                  {range.scenario_count} scenario(s), {(range.weight_covered * 100).toFixed(0)}% of
                  ensemble weight · elapsed {describeInterval(range.elapsed_time_s ?? null, 's')} ·
                  energy {describeInterval(range.own_energy_j ?? null, 'J')} · observed spread, not
                  a quantile
                </li>
              ))}
            </ul>
          )}

          <h3>Alternatives considered</h3>
          {(subject.alternatives ?? []).length === 0 ? (
            <p className="afterlap-small afterlap-muted">
              No alternative was recorded for this decision.
            </p>
          ) : (
            <DataTable
              caption="Candidates considered"
              description="Ranked as the planner ordered them. The constraint status is the independent checker's verdict, not the planner's."
              columns={ALTERNATIVE_COLUMNS}
              rows={subject.alternatives ?? []}
              rowKey={(row) => row.plan_id}
              emptyArtefact="alternative"
            />
          )}

          <h3>Rule context at the time of the decision</h3>
          {ruleContext === null ? (
            <p className="afterlap-small afterlap-muted">
              No resolved rule context is available for this session.
            </p>
          ) : (
            <dl className={styles.definitionList}>
              <dt>Season revision</dt>
              <dd>{ruleContext.season_revision}</dd>
              <dt>Eligibility</dt>
              <dd>{ruleContext.eligibility ?? 'unknown'}</dd>
              <dt>Admissible profiles</dt>
              <dd>
                {(ruleContext.admissible_profiles ?? []).length === 0
                  ? 'none — the pack admits no profile at this progress point'
                  : (ruleContext.admissible_profiles ?? []).join(', ')}
              </dd>
              <dt>Unknown conditions</dt>
              <dd>
                {(ruleContext.unknown_conditions ?? []).length === 0
                  ? 'none declared'
                  : (ruleContext.unknown_conditions ?? []).join(', ')}
              </dd>
            </dl>
          )}
        </div>
      )}
    </Dialog>
  );
}
