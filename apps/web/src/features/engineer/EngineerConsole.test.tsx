import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSessionStore } from '@/state/sessionStore';
import { SESSION_SNAPSHOT } from '@/test/contractFixtures';
import { foreignEnvelope, recommendationEnvelope, telemetryEnvelope } from '@/test/envelopes';
import { EngineerConsole } from './EngineerConsole';
import type { FakeSocket } from './testUtils';
import {
  apiClientFor,
  apiError,
  hrefOf,
  makeFetch,
  noSocket,
  renderRoute,
  socketFactory,
  type FetchStub,
} from './testUtils';

const SESSION_ID = SESSION_SNAPSHOT.session_id;
const PATH = `/sessions/${SESSION_ID}/engineer`;
const ROUTE = '/sessions/:sessionId/engineer';

const DECISION_RECORD = {
  recommendation: SESSION_SNAPSHOT.recommendation,
  estimate_revision: 4,
  operator_events: [],
  execution_events: [],
};

function snapshotWith(overrides: Record<string, unknown> = {}): unknown {
  return { ...SESSION_SNAPSHOT, ...overrides };
}

function baseHandlers(
  actionHandler?: Parameters<typeof makeFetch>[0][number][1],
): Parameters<typeof makeFetch>[0] {
  return [
    [
      '/recommendations/',
      actionHandler ??
        (() => ({
          body: {
            recommendation: { ...SESSION_SNAPSHOT.recommendation, status: 'selected', revision: 2 },
            operator_event: {
              schema_version: '1.0',
              id: 'op-1',
              session_id: SESSION_ID,
              idempotency_key: 'k',
              recommendation_id: 'rec-001',
              expected_revision: 7,
              operator_id: 'console-operator',
              action: 'select',
              session_time_s: 12.5,
              sequence: 101,
              resulting_status: 'selected',
            },
          },
        })),
    ],
    ['/decisions/', () => ({ body: DECISION_RECORD })],
    ['/snapshot', () => ({ body: snapshotWith() })],
  ];
}

function renderConsole(stub: FetchStub, socketFactory = noSocket()) {
  const client = apiClientFor(stub);
  return renderRoute(
    <EngineerConsole
      client={client}
      runtimeOptions={{ client, socketFactory }}
    />,
    { path: PATH, route: ROUTE },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('selection', () => {
  it('sends one idempotent command with the expected revision and actuates nothing', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);

    const select = await screen.findByRole('button', { name: 'Select' });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);

    await waitFor(() => expect(stub.matching('/actions').length).toBe(1));
    const request = stub.matching('/actions')[0];
    expect(request?.method).toBe('POST');
    expect(request?.headers['idempotency-key']).toBeTruthy();
    expect(request?.body).toMatchObject({
      action: 'select',


      expected_revision: SESSION_SNAPSHOT.recommendation?.revision,
      operator_id: 'console-operator',
    });


    expect(stub.matching('/simulator/driver-action')).toEqual([]);
  });

  it('does not optimistically mark the recommendation selected', async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const stub = makeFetch(baseHandlers());
    const original = stub.fetchImpl;
    const slowFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (hrefOf(input).includes('/actions')) {
        await gate;
      }
      return original(input, init);
    }) as typeof fetch;

    const client = apiClientFor({ ...stub, fetchImpl: slowFetch });
    renderRoute(
      <EngineerConsole client={client} runtimeOptions={{ client, socketFactory: noSocket() }} />,
      { path: PATH, route: ROUTE },
    );

    const select = await screen.findByRole('button', { name: 'Select' });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);


    expect(await screen.findByText(/Select in flight — awaiting server/)).toBeInTheDocument();
    expect(useSessionStore.getState().server.recommendation?.status).toBe('proposed');

    release();
    await waitFor(() => expect(stub.matching('/actions').length).toBe(1));
  });

  it('blocks a duplicate submission while one is in flight', async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const stub = makeFetch(baseHandlers());
    const original = stub.fetchImpl;
    const slowFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (hrefOf(input).includes('/actions')) {
        await gate;
      }
      return original(input, init);
    }) as typeof fetch;

    const client = apiClientFor({ ...stub, fetchImpl: slowFetch });
    renderRoute(<EngineerConsole client={client} runtimeOptions={{ client, socketFactory: noSocket() }} />, {
      path: PATH,
      route: ROUTE,
    });

    const select = await screen.findByRole('button', { name: 'Select' });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);

    const pending = await screen.findByRole('button', { name: /Sending select/ });
    expect(pending).toBeDisabled();

    release();
    await waitFor(() => expect(stub.matching('/actions').length).toBe(1));
  });

  it('treats a 409 as a refresh, not a retry', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(
      baseHandlers(() => apiError('stale_revision', 'the session moved on', 409, 'req-409')),
    );
    renderConsole(stub);

    const select = await screen.findByRole('button', { name: 'Select' });
    await waitFor(() => expect(select).toBeEnabled());
    const snapshotsBefore = stub.matching('/snapshot').length;
    await user.click(select);

    const outcome = await screen.findByTestId('action-outcome');
    expect(outcome).toHaveTextContent('the session moved on');
    expect(outcome).toHaveTextContent('req-409');


    expect(stub.matching('/actions').length).toBe(1);
    await waitFor(() =>
      expect(stub.matching('/snapshot').length).toBeGreaterThan(snapshotsBefore),
    );
    expect(useSessionStore.getState().server.recommendation?.status).toBe('proposed');
  });

  it('keeps mark communicated as a separate action, unavailable while proposed', async () => {
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);

    const communicate = await screen.findByRole('button', { name: 'Mark communicated' });
    expect(communicate).toBeDisabled();
    expect(
      screen.getByText(/Communicated is a separate action taken after the server records/),
    ).toBeInTheDocument();
  });
});

describe('stream handling', () => {
  it('ignores an envelope for another session and applies one for this session', async () => {
    const sockets: FakeSocket[] = [];
    const stub = makeFetch(baseHandlers());
    renderConsole(stub, socketFactory(sockets));

    await waitFor(() => expect(sockets.length).toBe(1));
    const socket = sockets[0] as FakeSocket;
    const rejectedBefore = useSessionStore.getState().stream.rejectedEnvelopes;

    socket.emit(foreignEnvelope(SESSION_SNAPSHOT.last_sequence + 1));
    await waitFor(() =>
      expect(useSessionStore.getState().stream.rejectedEnvelopes).toBe(rejectedBefore + 1),
    );
    expect(
      useSessionStore.getState().stream.rejections.at(-1)?.reason,
    ).toBe('wrong_session');

    socket.emit(telemetryEnvelope(SESSION_SNAPSHOT.last_sequence + 1));
    await waitFor(() =>
      expect(Object.keys(useSessionStore.getState().server.telemetry).length).toBeGreaterThan(0),
    );
  });

  it('asks for a resync when the sequence jumps', async () => {
    const sockets: FakeSocket[] = [];
    const stub = makeFetch(baseHandlers());
    renderConsole(stub, socketFactory(sockets));

    await waitFor(() => expect(sockets.length).toBe(1));
    const socket = sockets[0] as FakeSocket;
    const snapshotsBefore = stub.matching('/snapshot').length;

    socket.emit(recommendationEnvelope(SESSION_SNAPSHOT.last_sequence + 5));

    await waitFor(() =>
      expect(stub.matching('/snapshot').length).toBeGreaterThan(snapshotsBefore),
    );
    expect(useSessionStore.getState().stream.resyncCount).toBeGreaterThan(0);
  });
});

describe('evidence inspector', () => {
  it('opens, closes on Escape and restores focus to the control that opened it', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);


    await waitFor(() => expect(screen.getByRole('button', { name: 'Select' })).toBeEnabled());
    const invoker = screen.getByRole('button', { name: 'Open evidence' });
    await user.click(invoker);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: 'Decision evidence' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.getElementById('engineer-open-evidence')).toHaveFocus();
  });
});

describe('battle region', () => {
  it('renders the rival energy interval as a model quantile and never as a confidence bound', async () => {
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);

    const note = await screen.findByTestId('rival-energy-quantile-note');
    expect(note).toHaveTextContent('Model quantile');
    expect(note).toHaveTextContent('0.7885');
    expect(note.textContent ?? '').not.toMatch(/confidence/i);

    const kindLines = await screen.findAllByText('model quantile, nominal 90% label');
    expect(kindLines.length).toBeGreaterThan(0);
  });

  it('says lateral geometry is unknown rather than drawing a contact likelihood', async () => {
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);
    expect(await screen.findByTestId('lateral-geometry-note')).toHaveTextContent(
      'no side-by-side or contact likelihood is computed or drawn',
    );
  });
});

describe('unavailable values', () => {
  it('renders a null stored-energy reading as text, never as 0', async () => {
    const withoutEnergy = snapshotWith({
      estimate: {
        ...SESSION_SNAPSHOT.estimate,
        own_car: {
          ...SESSION_SNAPSHOT.estimate?.own_car,
          battery_energy_j: {
            ...SESSION_SNAPSHOT.estimate?.own_car.battery_energy_j,
            value: null,
            quality: 'missing',
          },
        },
      },
    });
    const stub = makeFetch([
      ['/decisions/', () => ({ body: DECISION_RECORD })],
      ['/snapshot', () => ({ body: withoutEnergy })],
    ]);
    renderConsole(stub);

    const readouts = await screen.findAllByText('not available');
    expect(readouts.length).toBeGreaterThan(0);

    const energyReadouts = document.querySelectorAll('[data-channel="battery_energy_j"]');
    expect(energyReadouts.length).toBeGreaterThan(0);
    for (const node of Array.from(energyReadouts)) {
      const value = node.querySelector('[data-available]');
      if (value?.getAttribute('data-available') === 'false') {
        expect(value.textContent?.trim()).not.toBe('0');
        expect(value.textContent).toContain('not available');
      }
    }
  });
});

describe('narrow viewports', () => {
  beforeEach(() => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('768'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));
  });

  it('becomes a read-only summary with no operational commands', async () => {
    const stub = makeFetch(baseHandlers());
    renderConsole(stub);

    expect(await screen.findByTestId('read-only-summary')).toHaveTextContent(
      'Operational commands are not offered at this width',
    );
    const select = screen.getByRole('button', { name: 'Select' });
    expect(select).toBeDisabled();
  });
});
