/**
 * The benchmark report bundle.
 *
 * A13 writes `ReportBundle.as_dict()`: `{ report, report_hash, detail }`. The
 * `report` half is the frozen `BenchmarkReport` contract and is imported from
 * the generated bundle. The `detail` half is deliberately outside the contract
 * — it carries what the contract cannot, including the comparison matrix and
 * its coverage — so its shape is declared here and validated at runtime rather
 * than trusted.
 *
 * The single rule for reading it: a row whose `status` is `"unmeasured"` is
 * **unavailable**, with its reason. It is not a zero, not a loss and not a
 * pending result, and the frontend never computes a win rate from the rows —
 * the report deliberately does not contain one.
 */
import type { BenchmarkComparison, BenchmarkReport } from '@contracts';

export const UNMEASURED = 'unmeasured';

export interface ComparisonMatrixRow {
  readonly controller: string;
  readonly reference: string | null;
  readonly purpose: string;
  readonly owner: string;
  readonly status: string;
  readonly reason: string | null;
  readonly comparison: BenchmarkComparison | null;
  readonly distribution: Record<string, unknown> | null;
}

export interface MatrixCoverageRow {
  readonly controller: string;
  readonly uses_actor: boolean;
  readonly uses_learned_return: boolean;
  readonly purpose: string;
  readonly owner: string;
  readonly status: string;
  readonly reason: string | null;
}

export interface ReportPopulation {
  readonly planned_units?: number;
  readonly completed_runs?: number;
  readonly unavailable_runs?: number;
  readonly failed_runs?: number;
  readonly scenario_ids?: readonly string[];
  readonly seeds?: readonly number[];
}

export interface ReportDetail {
  readonly manifest?: Record<string, unknown>;
  readonly environment?: Record<string, unknown>;
  readonly population?: ReportPopulation;
  readonly comparison_matrix?: readonly ComparisonMatrixRow[];
  readonly matrix_coverage?: readonly MatrixCoverageRow[];
  readonly gates?: Record<string, unknown>;
  readonly certification?: string;
}

export interface ReportBundleBody {
  readonly report: BenchmarkReport;
  readonly report_hash: string;
  readonly detail: ReportDetail;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Structural check before anything is rendered.
 *
 * Returns null rather than throwing, so a malformed body renders the same
 * named unavailable state as an absent one instead of a blank screen.
 */
export function parseReportBundle(value: unknown): ReportBundleBody | null {
  if (!isRecord(value)) {
    return null;
  }
  const report = value['report'];
  if (!isRecord(report) || typeof report['id'] !== 'string') {
    return null;
  }
  const detail = isRecord(value['detail']) ? (value['detail'] as ReportDetail) : {};
  return {
    report: report as unknown as BenchmarkReport,
    report_hash: typeof value['report_hash'] === 'string' ? value['report_hash'] : 'not recorded',
    detail,
  };
}

export function isUnmeasured(status: string | null | undefined): boolean {
  return status === UNMEASURED || status === null || status === undefined;
}

/** Rows the report says carry no number, with the reason each gives. */
export function unmeasuredRows(
  detail: ReportDetail,
): readonly { controller: string; reason: string }[] {
  const rows = detail.comparison_matrix ?? [];
  return rows
    .filter((row) => isUnmeasured(row.status))
    .map((row) => ({
      controller: row.controller,
      reason: row.reason ?? 'no reason recorded in the report',
    }));
}
