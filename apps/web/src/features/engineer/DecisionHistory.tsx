import type { ExecutionEvent, OperatorEvent } from '@contracts';

import { DataTable, Notice, Panel, StatusBadge, type Column } from '@/components';

export interface TimelineEntry {
  readonly id: string;
  readonly sessionTimeS: number;
  readonly sequence: number;
  readonly kind: 'operator' | 'execution';
  readonly what: string;
  readonly detail: string;
  readonly resulting: string | null;
  readonly source: string;
}

export interface DecisionHistoryProps {
  readonly operatorEvents: readonly OperatorEvent[];
  readonly executionEvents: readonly ExecutionEvent[];
  readonly loading: boolean;
  readonly errorMessage: string | null;
  readonly decisionId: string | null;
}

export function toTimeline(
  operatorEvents: readonly OperatorEvent[],
  executionEvents: readonly ExecutionEvent[],
): readonly TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  for (const event of operatorEvents) {
    entries.push({
      id: `operator-${event.id}`,
      sessionTimeS: event.session_time_s,
      sequence: event.sequence,
      kind: 'operator',
      what: event.action,
      detail: event.reason ?? 'no reason recorded',
      resulting: event.resulting_status ?? null,
      source: `${event.operator_id} · key ${event.idempotency_key}`,
    });
  }
  for (const event of executionEvents) {
    entries.push({
      id: `execution-${event.id}`,
      sessionTimeS: event.start_time_s,
      sequence: event.sequence,
      kind: 'execution',
      what: `observed ${event.observed_profile_id}`,
      detail:
        event.match_status === 'matched'
          ? 'matched the communicated instruction'
          : `execution ${event.match_status}`,
      resulting: null,
      source: `${event.source}${
        event.delay_from_communication_s === null || event.delay_from_communication_s === undefined
          ? ''
          : ` · ${event.delay_from_communication_s.toFixed(2)} s after communication`
      }`,
    });
  }
  // Sequence is the server's own total order; session time only breaks ties
  // for records that share one.
  return entries.sort((a, b) => a.sequence - b.sequence || a.sessionTimeS - b.sessionTimeS);
}

const COLUMNS: readonly Column<TimelineEntry>[] = [
  { id: 'seq', header: 'Seq', numeric: true, cell: (row) => row.sequence },
  {
    id: 'time',
    header: 'Session time',
    unit: 's',
    numeric: true,
    cell: (row) => row.sessionTimeS.toFixed(2),
  },
  {
    id: 'kind',
    header: 'Kind',
    cell: (row) => (
      <StatusBadge label="Event kind" tone={row.kind === 'operator' ? 'selection' : 'neutral'}>
        {row.kind}
      </StatusBadge>
    ),
  },
  { id: 'what', header: 'Event', cell: (row) => row.what },
  { id: 'detail', header: 'Detail', cell: (row) => row.detail },
  {
    id: 'resulting',
    header: 'Resulting status',
    cell: (row) => row.resulting ?? 'not applicable',
  },
  {
    id: 'source',
    header: 'Recorded by',
    cell: (row) => <span className="afterlap-mono afterlap-small">{row.source}</span>,
  },
];

/**
 * The immutable decision timeline.
 *
 * Read from `GET /decisions/{id}`, which is the server's own record. The
 * console does not build a timeline from what it happened to observe on the
 * socket, because a client that reconnected would then show a different
 * history than one that did not.
 */
export function DecisionHistory({
  operatorEvents,
  executionEvents,
  loading,
  errorMessage,
  decisionId,
}: DecisionHistoryProps) {
  const rows = toTimeline(operatorEvents, executionEvents);

  return (
    <Panel id="history" title="Decision timeline">
      <DataTable
        caption="Decision timeline records"
        description={
          decisionId === null
            ? 'No decision is selected, so no timeline is read.'
            : `Server record for decision ${decisionId}. Operator actions and observed executions, in server sequence order.`
        }
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.id}
        state={loading ? 'pending' : errorMessage !== null ? 'error' : 'ready'}
        {...(errorMessage === null ? {} : { errorMessage })}
        emptyArtefact="operator or execution event"
        emptyAction={
          <p className="afterlap-small afterlap-muted">
            The timeline fills as the operator acts and as the simulator reports what the driver
            did. An empty timeline means neither has happened yet.
          </p>
        }
      />
      <Notice tone="attention">
        This is the timeline of one decision. The control plane exposes no session-wide decision
        list, so earlier decisions in this session cannot be listed here.
      </Notice>
    </Panel>
  );
}
