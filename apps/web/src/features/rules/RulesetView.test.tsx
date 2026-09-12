import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RULE_MANIFEST } from '@/test/testFixtures';
import { apiError, makeFetch, renderRoute, type FetchStub } from '@/test/testUtils';
import { RulesetView } from './RulesetView';

const PATH = '/rulesets/synthetic-pack-v1';
const ROUTE = '/rulesets/:rulesetId';

function renderRules(stub: FetchStub) {


  const original = globalThis.fetch;
  globalThis.fetch = stub.fetchImpl;
  const result = renderRoute(<RulesetView />, { path: PATH, route: ROUTE });
  return {
    result,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

describe('coverage is declared per concern and linked to a source', () => {
  it('renders each concern with its status, tests and source', async () => {
    const stub = makeFetch([['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })]]);
    const { restore } = renderRules(stub);

    const region = await screen.findByRole('region', { name: 'Rule coverage' });
    expect(within(region).getByText('deployment power ceiling')).toBeInTheDocument();
    expect(within(region).getByText('implemented and tested')).toBeInTheDocument();
    expect(within(region).getByText('test_power_ceiling')).toBeInTheDocument();
    expect(within(region).getByText('unsupported')).toBeInTheDocument();
    restore();
  });

  it('says when a concern has no source and no reviewer, rather than implying one', async () => {
    const stub = makeFetch([['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })]]);
    const { restore } = renderRules(stub);

    const region = await screen.findByRole('region', { name: 'Rule coverage' });
    expect(within(region).getAllByText('no source recorded').length).toBeGreaterThan(0);
    expect(await screen.findByText(/no reviewer recorded/)).toBeInTheDocument();
    restore();
  });

  it('names the unsupported conditions and what they do to advice', async () => {
    const stub = makeFetch([['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })]]);
    const { restore } = renderRules(stub);

    const notice = await screen.findByTestId('unsupported-conditions');
    expect(notice).toHaveTextContent('overtake_gap_threshold_s');
    expect(notice).toHaveTextContent('returns unknown rather than a permissive default');
    restore();
  });

  it('shows the review state as declared, never upgraded', async () => {
    const stub = makeFetch([['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })]]);
    const { restore } = renderRules(stub);
    expect(await screen.findByText('not reviewed')).toBeInTheDocument();
    expect(screen.getAllByText('synthetic').length).toBeGreaterThan(0);
    restore();
  });

  it('converts the configured limits through the channel registry', async () => {
    const stub = makeFetch([['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })]]);
    const { restore } = renderRules(stub);

    expect(await screen.findByText('350 kW')).toBeInTheDocument();
    expect(screen.getByText(/0\.00 MJ to 4\.00 MJ/)).toBeInTheDocument();
    restore();
  });
});

describe('an unknown pack', () => {
  it('names the missing manifest instead of rendering an empty page', async () => {
    const stub = makeFetch([['/rulesets/', () => apiError('not_found', 'no such pack', 404, 'req-x')]]);
    const { restore } = renderRules(stub);
    expect(await screen.findByText(/missing artefact: rule pack manifest/)).toBeInTheDocument();
    expect(screen.getByTestId('ruleset-error')).toHaveTextContent('req-x');
    restore();
  });
});
