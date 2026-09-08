import { useParams } from 'react-router';
import type { CoverageEntry, RuleReference } from '@contracts';

import { guidanceFor, toApiError } from '@/api/errors';
import { useRuleset } from '@/api/queries';
import {
  DataTable,
  EmptyState,
  Notice,
  Panel,
  StatusBadge,
  type Column,
  type DataTableState,
} from '@/components';
import { UNAVAILABLE_TEXT, formatChannelValue } from '@/contracts/units';
import styles from '../engineer/workspace.module.css';

function coverageTone(status: CoverageEntry['status']) {
  if (status === 'implemented_and_tested') return 'verified' as const;
  if (status === 'unsupported') return 'failure' as const;
  if (status === 'review_required') return 'attention' as const;
  return 'neutral' as const;
}

function ReferenceList({ references }: { readonly references: readonly RuleReference[] }) {
  if (references.length === 0) {
    return <span className="afterlap-small afterlap-muted">no source recorded</span>;
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
          {' · '}
          {reference.reviewer === null || reference.reviewer === undefined
            ? 'no reviewer recorded'
            : `reviewed by ${reference.reviewer}`}
          {reference.effective_date === null || reference.effective_date === undefined
            ? ''
            : ` · effective ${reference.effective_date}`}
        </li>
      ))}
    </ul>
  );
}

const COVERAGE_COLUMNS: readonly Column<CoverageEntry>[] = [
  { id: 'concern', header: 'Concern', cell: (row) => row.concern },
  {
    id: 'status',
    header: 'Coverage',
    cell: (row) => (
      <StatusBadge label="Coverage status" tone={coverageTone(row.status)}>
        {row.status.replace(/_/g, ' ')}
      </StatusBadge>
    ),
  },
  {
    id: 'sources',
    header: 'Source',
    cell: (row) => <ReferenceList references={row.references ?? []} />,
  },
  {
    id: 'tests',
    header: 'Tests',
    cell: (row) =>
      (row.test_ids ?? []).length === 0 ? (
        <span className="afterlap-small afterlap-muted">no test recorded</span>
      ) : (
        <span className="afterlap-mono afterlap-small">{(row.test_ids ?? []).join(', ')}</span>
      ),
  },
  { id: 'note', header: 'Note', cell: (row) => row.note ?? 'none' },
];

/**
 * `/rulesets/:rulesetId`.
 *
 * What the loaded pack covers, with its sources, and what it does not. An
 * article number records where a value would come from; it is not a claim that
 * the value was transcribed from there, and a pack with no reviewer says so on
 * every row.
 */
export function RulesetView() {
  const { rulesetId } = useParams();
  const query = useRuleset(rulesetId);
  const manifest = query.data?.manifest ?? null;
  const error =
    query.error === null || query.error === undefined
      ? null
      : toApiError(query.error, 'ruleset unavailable');

  const coverage = manifest?.coverage ?? [];
  const unknown = manifest?.unknown_conditions ?? [];

  const state: DataTableState = query.isPending
    ? 'pending'
    : query.isError
      ? 'error'
      : coverage.length === 0
        ? 'empty'
        : 'ready';

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Ruleset</h1>
          <p>
            Which conditions the loaded pack covers, with sources, and which it does not. An
            unresolved condition is not a pass.
          </p>
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Pack id">{rulesetId ?? 'none'}</StatusBadge>
          <StatusBadge
            label="Review state"
            tone={manifest?.reviewed === true ? 'verified' : 'attention'}
          >
            {manifest === null ? 'unknown' : manifest.reviewed === true ? 'reviewed' : 'not reviewed'}
          </StatusBadge>
          <StatusBadge label="Data class" tone="attention">
            {manifest?.synthetic === false ? 'transcribed' : 'synthetic'}
          </StatusBadge>
        </div>
      </div>

      {error === null ? null : (
        <Notice tone="failure" testId="ruleset-error">
          {error.message} {guidanceFor(error) ?? ''} (request {error.request_id})
        </Notice>
      )}

      {manifest === null ? (
        <Panel id="ruleset" title="Rule pack">
          {query.isPending ? (
            <p aria-busy="true">Reading the rule pack manifest…</p>
          ) : (
            <EmptyState
              artefact="rule pack manifest"
              heading="No rule pack manifest for this id"
              reason="The control plane resolves an immutable pack by id. Nothing is shown for an id it does not know."
            />
          )}
        </Panel>
      ) : (
        <>
          <Panel id="limits" title="Applicable limits">
            <dl className={styles.definitionList}>
              <dt>Season revision</dt>
              <dd>{manifest.season_revision}</dd>
              <dt>Event pack</dt>
              <dd>{manifest.event_pack_id ?? 'none loaded'}</dd>
              <dt>Absolute power ceiling</dt>
              <dd>
                {formatChannelValue('electrical_power_w', manifest.absolute_power_ceiling_w).text}
              </dd>
              <dt>Battery energy window</dt>
              <dd>
                {formatChannelValue('battery_energy_j', manifest.battery_energy_min_j).text} to{' '}
                {formatChannelValue('battery_energy_j', manifest.battery_energy_max_j).text}
              </dd>
              <dt>Recharge allowance per lap</dt>
              <dd>
                {formatChannelValue(
                  'battery_energy_j',
                  manifest.recharge_allowance_per_lap_j ?? null,
                ).text}
              </dd>
              <dt>Recharge measurement bus</dt>
              <dd>{manifest.recharge_measurement_bus ?? UNAVAILABLE_TEXT}</dd>
              <dt>Maximum power ramp</dt>
              <dd>
                {manifest.max_power_ramp_w_per_s === null ||
                manifest.max_power_ramp_w_per_s === undefined
                  ? UNAVAILABLE_TEXT
                  : `${(manifest.max_power_ramp_w_per_s / 1000).toFixed(0)} kW/s`}
              </dd>
              <dt>Detection lines</dt>
              <dd>
                {(manifest.detection_lines ?? []).length === 0
                  ? 'none declared'
                  : (manifest.detection_lines ?? [])
                      .map((line) => `${line.line_id} (${line.kind}) at ${line.s_m.toFixed(0)} m`)
                      .join('; ')}
              </dd>
            </dl>
          </Panel>

          {unknown.length === 0 ? null : (
            <Notice tone="failure" testId="unsupported-conditions">
              Unsupported conditions: {unknown.join(', ')}. While these remain unresolved the
              independent checker returns unknown rather than a permissive default, and advice is
              suppressed.
            </Notice>
          )}

          <Panel id="coverage" title="Coverage">
            <DataTable
              caption="Rule coverage"
              description="Declared per concern. There is no blanket coverage badge, and an implemented concern is not the same as a reviewed source."
              columns={COVERAGE_COLUMNS}
              rows={[...coverage]}
              rowKey={(row) => row.concern}
              state={state}
              errorMessage="The rule pack coverage could not be read."
              emptyArtefact="coverage entry"
              emptyAction={
                <p className="afterlap-small afterlap-muted">
                  This pack declares no per-concern coverage. An absent declaration is not
                  coverage.
                </p>
              }
            />
          </Panel>

          <Panel id="sources" title="Pack sources">
            <ReferenceList references={manifest.references ?? []} />
            <Notice tone="attention">
              Article numbers record where a real transcription would come from. They are not
              evidence that the values in this pack were read from those documents, and this pack
              declares {manifest.reviewed === true ? 'a review' : 'no review'}.
            </Notice>
          </Panel>
        </>
      )}
    </div>
  );
}
