import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CANDIDATE_MODEL, UNSUPPORTED_APPROVED_MODEL } from '@/test/testFixtures';
import { makeFetch, renderRoute, type FetchStub } from '@/test/testUtils';
import { ModelsView, approvalIsSupported } from './ModelsView';

function renderModels(stub: FetchStub) {
  const original = globalThis.fetch;
  globalThis.fetch = stub.fetchImpl;
  renderRoute(<ModelsView />, { path: '/models', route: '/models' });
  return () => {
    globalThis.fetch = original;
  };
}

describe('candidate and approved are distinguished by evidence', () => {
  it('shows a candidate bundle as a candidate with no benchmark evidence', async () => {
    const stub = makeFetch([['/models', () => ({ body: { models: [CANDIDATE_MODEL] } })]]);
    const restore = renderModels(stub);

    expect(await screen.findByText('no report hash recorded')).toBeInTheDocument();
    const region = screen.getByRole('region', { name: 'Registered model bundles' });
    expect(within(region).getByText('candidate')).toBeInTheDocument();
    expect(screen.getByText('0 approved')).toBeInTheDocument();
    restore();
  });

  it('flags an approved bundle whose record references no benchmark report', async () => {
    const stub = makeFetch([
      ['/models', () => ({ body: { models: [UNSUPPORTED_APPROVED_MODEL] } })],
    ]);
    const restore = renderModels(stub);

    expect(await screen.findByTestId('unsupported-approval')).toHaveTextContent(
      'not supported by evidence in the record',
    );
    expect(
      screen.getAllByText(/approved with no benchmark report referenced/).length,
    ).toBeGreaterThan(0);
    restore();
  });

  it('offers no promotion control anywhere', async () => {
    const stub = makeFetch([['/models', () => ({ body: { models: [CANDIDATE_MODEL] } })]]);
    const restore = renderModels(stub);

    expect(await screen.findByTestId('no-promotion')).toHaveTextContent(
      'no automatic promotion exists anywhere in the product',
    );
    const buttons = screen.queryAllByRole('button', { name: /promote/i });
    expect(buttons).toEqual([]);
    restore();
  });

  it('names the missing artefact when nothing is registered', async () => {
    const stub = makeFetch([['/models', () => ({ body: { models: [] } })]]);
    const restore = renderModels(stub);
    expect(await screen.findByText(/missing artefact: model manifest/)).toBeInTheDocument();
    expect(
      screen.getByText(/No trained bundle exists in this build/),
    ).toBeInTheDocument();
    restore();
  });

  it('reports a declared support envelope, and its absence as unavailable', async () => {
    const stub = makeFetch([
      [
        '/models',
        () => ({
          body: {
            models: [CANDIDATE_MODEL, { ...CANDIDATE_MODEL, id: 'no-envelope', support_thresholds: null }],
          },
        }),
      ],
    ]);
    const restore = renderModels(stub);

    await screen.findByText(/disagreement ≤ 0.2/);
    const region = screen.getByRole('region', { name: 'Registered model bundles' });
    expect(within(region).getByText(/disagreement ≤ 0.2/)).toBeInTheDocument();
    expect(
      within(region).getByText(/not available — no support envelope declared/),
    ).toBeInTheDocument();
    restore();
  });
});

describe('approvalIsSupported', () => {
  it('is true for anything that does not claim approval', () => {
    expect(approvalIsSupported(CANDIDATE_MODEL)).toBe(true);
  });

  it('is false for an approval with no referenced report', () => {
    expect(approvalIsSupported(UNSUPPORTED_APPROVED_MODEL)).toBe(false);
  });

  it('is true for an approval that references one', () => {
    expect(
      approvalIsSupported({
        ...UNSUPPORTED_APPROVED_MODEL,
        benchmark_report_hash: 'sha256:845e91831319e89c4d656bdb80c278ac09a7230d61e5dfd2e1b1fbb436ac8917',
      }),
    ).toBe(true);
  });
});
