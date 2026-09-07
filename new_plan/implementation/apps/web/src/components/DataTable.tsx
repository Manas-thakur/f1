import { useId, type ReactNode } from 'react';

import { EmptyState } from './EmptyState';
import styles from './primitives.module.css';

export interface Column<Row> {
  readonly id: string;
  readonly header: string;
  /** Rendered per row. Return null to render the unavailable marker. */
  readonly cell: (row: Row) => ReactNode;
  readonly numeric?: boolean;
  /** Unit shown in the header, e.g. "kW". */
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
  /** Named missing artefact and the action that would create it. */
  readonly emptyArtefact?: string;
  readonly emptyAction?: ReactNode;
  readonly selectedRowKey?: string | null;
  readonly onRowSelect?: (row: Row) => void;
  readonly footer?: ReactNode;
  readonly actions?: ReactNode;
}

/**
 * Tabular data with real headers.
 *
 * The scroll container is a labelled region with a tab stop, so a wide table
 * scrolls inside its panel and never widens the document. Column headers carry
 * `scope="col"` and their units.
 */
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
        <div
          className={styles.tableScroll}
          role="region"
          aria-labelledby={headingId}
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
        </div>
      ) : null}

      {footer === undefined ? null : <div className={styles.tableFoot}>{footer}</div>}
    </div>
  );
}
