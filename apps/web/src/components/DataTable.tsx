import { useId, type ReactNode } from 'react';

import { EmptyState } from './EmptyState';
import styles from './primitives.module.css';

export interface Column<Row> {
  readonly id: string;
  readonly header: string;
  
  readonly cell: (row: Row) => ReactNode;
  readonly numeric?: boolean;
  
  readonly unit?: string;
  readonly width?: string;
}

export type DataTableState = 'ready' | 'pending' | 'error' | 'empty';

export interface DataTableProps<Row> {
  readonly caption: string;
  readonly description?: string;
  readonly columns: readonly Column<Row>[];
  readonly rows: readonly Row[];
  readonly rowKey: (row: Row) => string;
  readonly state?: DataTableState;
  readonly errorMessage?: string;
  
  readonly emptyArtefact?: string;
  readonly emptyAction?: ReactNode;
  readonly selectedRowKey?: string | null;
  readonly onRowSelect?: (row: Row) => void;
  readonly footer?: ReactNode;
  readonly actions?: ReactNode;
}


export function DataTable<Row>({
  caption,
  description,
  columns,
  rows,
  rowKey,
  state = 'ready',
  errorMessage,
  emptyArtefact,
  emptyAction,
  selectedRowKey = null,
  onRowSelect,
  footer,
  actions,
}: DataTableProps<Row>) {
  const id = useId();
  const headingId = `${id}-heading`;
  const effectiveState: DataTableState = state === 'ready' && rows.length === 0 ? 'empty' : state;

  return (
    <div className={styles.tableRegion}>
      <div className={styles.tableCaptionBar}>
        <div>
          <h3 id={headingId}>{caption}</h3>
          {description !== undefined ? (
            <p className={styles.fieldHint}>{description}</p>
          ) : null}
        </div>
        {actions}
      </div>

      {effectiveState === 'pending' ? (
        <p className={styles.tableFoot} aria-busy="true">
          Loading {caption.toLowerCase()}…
        </p>
      ) : null}

      {effectiveState === 'error' ? (
        <p className={styles.tableFoot} role="alert" data-tone="error">
          {errorMessage ?? `${caption} could not be loaded.`}
        </p>
      ) : null}

      {effectiveState === 'empty' ? (
        <div style={{ padding: 'var(--s4)' }}>
          <EmptyState
            artefact={emptyArtefact ?? caption}
            action={emptyAction}
            heading={`No ${caption.toLowerCase()} yet`}
          />
        </div>
      ) : null}

      {effectiveState === 'ready' ? (
        <section
          className={styles.tableScroll}
          aria-labelledby={headingId}
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
        >
          <table className={styles.table}>
            <caption className="afterlap-visually-hidden">{caption}</caption>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.id}
                    scope="col"
                    className={column.numeric === true ? styles.numeric : undefined}
                    style={column.width === undefined ? undefined : { width: column.width }}
                  >
                    {column.header}
                    {column.unit === undefined ? null : (
                      <>
                        {' '}
                        <span className="afterlap-muted">({column.unit})</span>
                      </>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const key = rowKey(row);
                return (
                  <tr
                    key={key}
                    data-selected={selectedRowKey === key ? 'true' : undefined}
                    onClick={onRowSelect === undefined ? undefined : () => onRowSelect(row)}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.id}
                        className={column.numeric === true ? styles.numeric : undefined}
                      >
                        {column.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {footer === undefined ? null : <div className={styles.tableFoot}>{footer}</div>}
    </div>
  );
}
