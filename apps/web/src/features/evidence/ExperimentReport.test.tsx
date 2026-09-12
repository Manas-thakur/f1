import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { REPORT_BUNDLE, experimentJob } from '@/test/testFixtures';
import {
  apiError,
  labClientFor,
  makeFetch,
  renderRoute,
  type FetchStub,
  type RouteHandler,
} from '@/test/testUtils';
import { ExperimentReport } from './ExperimentReport';
import { parseReportBundle, unmeasuredRows } from './reportTypes';

const PATH = '/experiments/exp-0001/report';
const ROUTE = '/experiments/:experimentId/report';


function renderReport(stub: FetchStub) {
  const original = globalThis.fetch;
  globalThis.fetch = stub.fetchImpl;
  const result = renderRoute(<ExperimentReport client={labClientFor(stub)} />, {
    path: PATH,
    route: ROUTE,
  });
  restoreFetch = () => {
    globalThis.fetch = original;
  };
  return result;
}

let restoreFetch: (() => void) | null = null;

afterEach(() => {
  restoreFetch?.();
  restoreFetch = null;
});

function handlers(reportHandler: RouteHandler): Parameters<typeof makeFetch>[0] {
  return [
    ['/report', reportHandler],
    ['/experiments/', () => ({ body: experimentJob({ report_hash: 'sha256:r' }, 'completed') })],
  ];
}

describe('absent evidence reads as absent', () => {
  it('names the missing route when the control plane serves no report body', async () => {
    const stub = makeFetch(
      handlers(() => apiError('not_found', 'no report route', 404, 'req-r')),
    );
    renderReport(stub);

    expect(await screen.findByText(/missing artefact: benchmark report body/)).toBeInTheDocument();
    expect(await screen.findByText(/no route serves the report JSON/)).toBeInTheDocument();

    expect(screen.queryByRole('region', { name: 'Comparison matrix rows' })).toBeNull();
  });

  it('still shows the job record, including that a run is incomplete', async () => {
    const stub = makeFetch([
      ['/report', () => apiError('not_found', 'no report route', 404)],
      [
        '/experiments/',
        () => ({ body: experimentJob({ partial_results: true, progress: 0.4 }, 'cancelled') }),
      ],
    ]);
    renderReport(stub);

    expect(
      await screen.findByText(/yes — this run is incomplete and is excluded from headline aggregates/),
    ).toBeInTheDocument();
    expect(screen.getAllByText('cancelled').length).toBeGreaterThan(0);
  });

  it('says the report route is unimplemented, with the code and request id', async () => {
    const stub = makeFetch(
      handlers(() => apiError('not_found', 'no report route', 404, 'req-r')),
    );
    renderReport(stub);

    const reason = await screen.findByText(
      /GET \/api\/v1\/experiments\/\{experiment_id\}\/report is not implemented/,
    );
    expect(reason).toHaveTextContent('not_found');
    expect(reason).toHaveTextContent('req-r');
  });

  it('renders a malformed body as unavailable rather than a blank panel', async () => {
    const stub = makeFetch(handlers(() => ({ body: { nonsense: true } })));
    renderReport(stub);
    expect(await screen.findByText(/missing artefact: benchmark report body/)).toBeInTheDocument();
    expect(
      await screen.findByText(/is not a benchmark report bundle this view can read/),
    ).toBeInTheDocument();
  });
});

describe('the comparison matrix', () => {
  it('renders the four learned rows as unavailable with their reasons', async () => {
    const stub = makeFetch(handlers(() => ({ body: REPORT_BUNDLE })));
    renderReport(stub);

    const matrix = await screen.findByRole('region', { name: 'Comparison matrix rows' });
    const unavailable = within(matrix).getAllByText('unavailable');
    expect(unavailable).toHaveLength(4);

    expect(within(matrix).getByText(/needs a trained actor/)).toBeInTheDocument();
    expect(within(matrix).getByText(/needs a trained continuation ensemble/)).toBeInTheDocument();
    expect(within(matrix).getByText(/needs a promoted model bundle/)).toBeInTheDocument();
    expect(within(matrix).getByText(/not wired into run_benchmark/)).toBeInTheDocument();
  });

  it('shows no paired difference where none was computed, and never a zero', async () => {
    const stub = makeFetch(handlers(() => ({ body: REPORT_BUNDLE })));
    renderReport(stub);

    const matrix = await screen.findByRole('region', { name: 'Comparison matrix rows' });
    const cells = within(matrix).getAllByText(
      /not available — no paired estimate was computed for this row/,
    );
    expect(cells).toHaveLength(5);
    expect(matrix.textContent ?? '').toContain('14.8000 s');
  });

  it('computes no win rate anywhere on the page', async () => {
    const stub = makeFetch(handlers(() => ({ body: REPORT_BUNDLE })));
    renderReport(stub);

    expect(await screen.findByTestId('no-win-rate')).toHaveTextContent(
      'No win rate, success percentage or aggregate score is computed on this screen',
    );
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/win rate:/i);
    expect(text).not.toMatch(/\d+\s?% (wins|success|win rate)/i);
  });

  it('carries the report’s own notes about what was not measured', async () => {
    const stub = makeFetch(handlers(() => ({ body: REPORT_BUNDLE })));
    renderReport(stub);
    expect(
      await screen.findByText(/calibration is unmeasured rather than perfect/),
    ).toBeInTheDocument();
  });
});

describe('report parsing', () => {
  it('accepts A13’s bundle shape', () => {
    const parsed = parseReportBundle(REPORT_BUNDLE);
    expect(parsed?.report.id).toBe('report-commissioning-smoke');
    expect(parsed?.detail.comparison_matrix).toHaveLength(6);
  });

  it('rejects anything that is not a bundle, without throwing', () => {
    expect(parseReportBundle(null)).toBeNull();
    expect(parseReportBundle({})).toBeNull();
    expect(parseReportBundle({ report: {} })).toBeNull();
    expect(parseReportBundle('a string')).toBeNull();
  });

  it('lists exactly the unmeasured rows with their reasons', () => {
    const parsed = parseReportBundle(REPORT_BUNDLE);
    const rows = unmeasuredRows(parsed?.detail ?? {});
    expect(rows.map((row) => row.controller)).toEqual([
      'mpc_only',
      'mpc_plus_actor',
      'mpc_plus_value',
      'full_system',
    ]);
    expect(rows.every((row) => row.reason.length > 0)).toBe(true);
  });
});

describe('job errors', () => {
  it('reports a typed control-plane error with its request id', async () => {
    const stub = makeFetch([
      ['/report', () => apiError('not_found', 'no report route', 404)],
      ['/experiments/', () => apiError('not_found', 'no such job', 404, 'req-job')],
    ]);
    renderReport(stub);
    await waitFor(() =>
      expect(screen.getByTestId('job-error')).toHaveTextContent('req-job'),
    );
  });
});
