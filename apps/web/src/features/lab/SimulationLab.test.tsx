import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { SESSION_SNAPSHOT } from '@/test/contractFixtures';
import {
  apiClientFor,
  apiError,
  labClientFor,
  makeFetch,
  noSocket,
  renderRoute,
  type FetchStub,
  type RouteHandler,
} from '@/test/testUtils';
import { CANDIDATE_MODEL, RULE_MANIFEST, experimentJob } from '@/test/testFixtures';
import { SimulationLab } from './SimulationLab';
import { pacingIntervalMs } from './RunControl';

const SESSION_ID = SESSION_SNAPSHOT.session_id;
const SNAPSHOT_HASH = 'sha256:d1b0aae58822367cec0912e5e738b7b3807f359451fcedc10cf6ee02fc65930f';
const PATH = `/sessions/${SESSION_ID}/lab`;
const ROUTE = '/sessions/:sessionId/lab';

const SNAPSHOT_REFERENCE = {
  snapshot: {
    snapshot_id: 'snap-0001',
    session_id: SESSION_ID,
    snapshot_hash: SNAPSHOT_HASH,
    session_time_s: 12.3,
    label: 'before the attack',
    created_at: '2026-09-08T12:00:00Z',
  },
};

function handlers(overrides: readonly [string, RouteHandler][] = []) {
  return [
    ...overrides,
    [`/sessions/${SESSION_ID}/snapshots`, () => ({ status: 201, body: SNAPSHOT_REFERENCE })],
    ['/snapshot', () => ({ body: SESSION_SNAPSHOT })],
    ['/rulesets/', () => ({ body: { manifest: RULE_MANIFEST } })],
    ['/models', () => ({ body: { models: [CANDIDATE_MODEL] } })],
    ['/experiments', () => ({ body: [experimentJob()] })],
    ['/commands', () => ({ body: { accepted: true, revision: 8, sequence: 99, status: 'running' } })],
  ] as [string, RouteHandler][];
}

function renderLab(stub: FetchStub) {
  const lab = labClientFor(stub);
  const api = apiClientFor(stub);
  return renderRoute(
    <SimulationLab
      client={api}
      labClientOverride={lab}
      runtimeOptions={{ client: api, sourceFactory: noSocket() }}
    />,
    { path: PATH, route: ROUTE },
  );
}

describe('the synthetic label is persistent', () => {
  it('is on the page whatever the session says', async () => {
    const stub = makeFetch(handlers());
    renderLab(stub);
    expect(await screen.findByTestId('lab-synthetic-label')).toHaveTextContent(
      'nothing produced in this view is a measurement of a real car',
    );
  });
});

describe('run control', () => {
  it('sends a session command with the expected revision and an idempotency key', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers());
    renderLab(stub);

    const start = await screen.findByRole('button', { name: 'Start' });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);

    await waitFor(() => expect(stub.matching('/commands').length).toBe(1));
    const request = stub.matching('/commands')[0];
    expect(request?.body).toMatchObject({
      kind: 'start',
      expected_revision: SESSION_SNAPSHOT.revision,
      operator_id: 'console-operator',
    });
    expect(request?.headers['idempotency-key']).toBeTruthy();
  });

  it('changes wall-clock pacing only, never the simulated step duration', () => {
    expect(pacingIntervalMs(1)).toBe(1000);
    expect(pacingIntervalMs(4)).toBe(250);
    expect(pacingIntervalMs(0.25)).toBe(4000);
  });

  it('surfaces a stale-revision conflict rather than retrying', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(
      handlers([
        ['/commands', () => apiError('stale_revision', 'session revision moved', 409, 'req-c')],
      ]),
    );
    renderLab(stub);

    const start = await screen.findByRole('button', { name: 'Start' });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);

    expect(await screen.findByTestId('run-control-error')).toHaveTextContent(
      'session revision moved',
    );
    expect(stub.matching('/commands').length).toBe(1);
  });
});

describe('snapshot and compare from here', () => {
  it('creates a snapshot and shows the hash the server returned', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers());
    renderLab(stub);

    await user.click(await screen.findByRole('button', { name: 'Create snapshot' }));

    await waitFor(() => expect(stub.matching('/snapshots').length).toBe(1));
    expect(await screen.findByText(new RegExp(SNAPSHOT_HASH))).toBeInTheDocument();
    expect(stub.matching('/snapshots')[0]?.headers['idempotency-key']).toBeTruthy();
  });

  it('queues one paired experiment with the same seeds on both treatments', async () => {
    const user = userEvent.setup();
    const created = { job: experimentJob({ id: 'exp-42' }, 'queued').job };
    const stub = makeFetch(
      handlers([
        [
          '/experiments',
          (item) => (item.method === 'POST' ? { status: 202, body: created } : { body: [experimentJob()] }),
        ],
      ]),
    );
    renderLab(stub);

    await user.click(await screen.findByRole('button', { name: 'Create snapshot' }));
    await screen.findByText(new RegExp(SNAPSHOT_HASH));

    const queue = screen.getByRole('button', { name: 'Queue paired experiment' });
    await waitFor(() => expect(queue).toBeEnabled());
    await user.click(queue);

    await waitFor(() =>
      expect(stub.requests.filter((r) => r.method === 'POST' && r.url.endsWith('/experiments')).length).toBe(1),
    );
    const request = stub.requests.find(
      (r) => r.method === 'POST' && r.url.endsWith('/experiments'),
    );
    const body = request?.body as {
      snapshot_id: string;
      seeds: number[];
      treatments: { treatment_id: string }[];
    };
    expect(body.snapshot_id).toBe('snap-0001');
    expect(body.seeds).toEqual([1, 2, 3, 4]);
    expect(body.treatments.map((t) => t.treatment_id)).toEqual(['reference', 'candidate']);
    expect(await screen.findByTestId('experiment-queued')).toHaveTextContent(
      'Queued is not finished',
    );
  });

  it('refuses to queue a comparison of a controller with itself', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers());
    renderLab(stub);

    const candidate = await screen.findByLabelText('Candidate controller');
    await user.clear(candidate);
    await user.type(candidate, 'legal_fixed_schedule');

    expect(
      await screen.findByText(/comparing a controller with itself measures only seed noise/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Queue paired experiment' })).toBeDisabled();
  });

  it('labels the alignment and reports branch outcomes as unmeasured, not zero', async () => {
    const stub = makeFetch(handlers());
    renderLab(stub);

    const table = await screen.findByRole('region', { name: 'Branch outcomes' });
    const rows = within(table).getAllByRole('row');

    expect(rows).toHaveLength(3);
    expect(within(table).getAllByText('unmeasured')).toHaveLength(2);
    expect(table.textContent ?? '').not.toMatch(/\b0\.00\b/);

    expect(screen.getByTestId('branch-outcome-unavailable')).toHaveTextContent(
      'unmeasured here, not zero',
    );
    expect(
      screen.getAllByText(/common progress \(metres travelled\)/).length,
    ).toBeGreaterThan(0);
  });
});

describe('experiment jobs', () => {
  it('renders a cancelled job with partial results as incomplete', async () => {
    const stub = makeFetch(
      handlers([
        [
          '/experiments',
          () => ({
            body: [
              experimentJob(
                { id: 'exp-cancelled', progress: 0.4, partial_results: true, failure: 'cancelled by console-operator: stopped' },
                'cancelled',
              ),
            ],
          }),
        ],
      ]),
    );
    renderLab(stub);

    const region = await screen.findByRole('region', { name: 'Experiment job queue' });
    expect(within(region).getByText('cancelled')).toBeInTheDocument();
    expect(within(region).getByText('incomplete')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Cancel' })).toBeDisabled();
  });

  it('shows the seeds and evaluator as unavailable for a job it did not submit', async () => {
    const stub = makeFetch(handlers());
    renderLab(stub);
    const region = await screen.findByRole('region', { name: 'Experiment job queue' });
    expect(within(region).getAllByText('not available').length).toBeGreaterThan(0);
    expect(
      within(region).getByText(/the status response carries a manifest hash, not the manifest/),
    ).toBeInTheDocument();
  });

  it('cancels a running job through the control plane', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(
      handlers([
        [
          '/cancel',
          () => ({ body: experimentJob({ partial_results: true }, 'cancelled') }),
        ],
      ]),
    );
    renderLab(stub);

    const region = await screen.findByRole('region', { name: 'Experiment job queue' });
    await user.click(within(region).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(stub.matching('/cancel').length).toBe(1));
    expect(stub.matching('/cancel')[0]?.body).toMatchObject({
      reason: 'cancelled from the simulation lab',
    });
  });
});

describe('scenario configuration', () => {
  it('does not offer initial conditions the create-session contract cannot carry', async () => {
    const stub = makeFetch(handlers());
    renderLab(stub);
    const legend = await screen.findByText('Initial conditions and observation conditions');
    const fieldset = legend.closest('fieldset');
    expect(fieldset).not.toBeNull();
    expect(fieldset).toBeDisabled();
    expect(fieldset?.textContent ?? '').toContain('accepts no such fields');
  });
});
