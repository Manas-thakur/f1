import { Link } from 'react-router';
import type { SessionSummary } from '@contracts';

import { DataTable, type Column, type DataTableState } from '../components/DataTable';
import { StatusBadge } from '../components/StatusBadge';
import { guidanceFor, toApiError } from '../api/errors';
import { useSessions } from '../api/queries';
import styles from '../app/shell.module.css';

const COLUMNS: readonly Column<SessionSummary>[] = [
  {
    id: 'label',
    header: 'Session',
    cell: (row) => (
      <>
        <Link to={`/sessions/${row.id}/engineer`}>{row.label ?? row.id}</Link>
        <br />
        <span className="afterlap-mono afterlap-small afterlap-muted">{row.id}</span>
      </>
    ),
  },
  {
    id: 'mode',
    header: 'Mode',
    cell: (row) => <StatusBadge label="Session mode">{row.mode}</StatusBadge>,
  },
  {
    id: 'status',
    header: 'Status',
    cell: (row) => (
      <StatusBadge label="Status" tone={row.status === 'running' ? 'selection' : 'neutral'}>
        {row.status}
      </StatusBadge>
    ),
  },
  {
    id: 'source',
    header: 'Source',
    cell: (row) => (
      <StatusBadge label="Data source" tone="neutral">
        {row.synthetic === false ? 'recorded' : 'synthetic'}
      </StatusBadge>
    ),
  },
  { id: 'scenario', header: 'Scenario', cell: (row) => row.scenario_id ?? 'not recorded' },
  { id: 'revision', header: 'Revision', numeric: true, cell: (row) => row.revision },
  { id: 'created', header: 'Created', cell: (row) => row.created_at },
  {
    id: 'open',
    header: 'Open',
    cell: (row) => (
      <>
        <Link to={`/sessions/${row.id}/engineer`}>engineer</Link>
        {' · '}
        <Link to={`/sessions/${row.id}/lab`}>lab</Link>
        {' · '}
        <Link to={`/sessions/${row.id}/replay`}>replay</Link>
        {row.mode === 'simulation' ? (
          <>
            {' · '}
            <Link to={`/sessions/${row.id}/driver`}>driver</Link>
          </>
        ) : null}
      </>
    ),
  },
];


export function SessionsPage() {
  const query = useSessions();
  const sessions = query.data?.sessions ?? [];

  const state: DataTableState = query.isPending
    ? 'pending'
    : query.isError
      ? 'error'
      : sessions.length === 0
        ? 'empty'
        : 'ready';

  const apiError = query.error === null ? null : toApiError(query.error, 'sessions unavailable');

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1>Sessions</h1>
          <p>
            Choose a session to work in. The mode and source columns say what kind of data the
            session carries; a fixture never becomes live because a label changed.
          </p>
        </div>
      </div>

      <div className={styles.workAreaSingle}>
        <DataTable
          caption="Sessions"
          description="Sorted by the control plane. Selecting a row opens the engineer console for that session."
          columns={COLUMNS}
          rows={sessions}
          rowKey={(row) => row.id}
          state={state}
          {...(apiError === null
            ? {}
            : {
                errorMessage: `${apiError.message} ${guidanceFor(apiError) ?? ''} (request ${apiError.request_id})`,
              })}
          emptyArtefact="session manifest"
          emptyAction={
            <p>
              A session is created by the control plane from a scenario, a ruleset and a seed.
              Configure one in <Link to="/lab">the simulation laboratory</Link>; it cannot be
              created from this screen.
            </p>
          }
          footer={
            query.data?.next_cursor
              ? `More sessions available; cursor ${query.data.next_cursor}.`
              : `${sessions.length} session${sessions.length === 1 ? '' : 's'} listed.`
          }
        />
      </div>
    </>
  );
}
