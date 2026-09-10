import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { SESSION_SNAPSHOT } from '@/test/contractFixtures';
import {
  apiClientFor,
  makeFetch,
  noSocket,
  renderRoute,
  type FetchStub,
} from '@/test/testUtils';
import { DriverDisplay } from './DriverDisplay';

const SESSION_ID = SESSION_SNAPSHOT.session_id;
const PATH = `/sessions/${SESSION_ID}/driver`;
const ROUTE = '/sessions/:sessionId/driver';

function snapshot(overrides: Record<string, unknown> = {}): unknown {
  return { ...SESSION_SNAPSHOT, ...overrides };
}

function withRecommendationStatus(status: string): unknown {
  return snapshot({
    recommendation: { ...SESSION_SNAPSHOT.recommendation, status },
  });
}

const EXECUTION_RESPONSE = {
  execution: {
    schema_version: '1.0',
    id: 'exec-9',
    session_id: SESSION_ID,
    recommendation_id: 'rec-001',
    source: 'simulated',
    observed_profile_id: 'overtake',
    start_time_s: 12.6,
    end_time_s: null,
    evidence_event_ids: [],
    match_status: 'matched',
    sequence: 200,
    delay_from_communication_s: 0.4,
  },
  recommendation: { ...SESSION_SNAPSHOT.recommendation, status: 'executing' },
};

function renderDriver(stub: FetchStub, watchdogMs = 60_000) {
  const client = apiClientFor(stub);
  return renderRoute(
    <DriverDisplay
      client={client}
      watchdogMs={watchdogMs}
      runtimeOptions={{ client, socketFactory: noSocket() }}
    />,
    { path: PATH, route: ROUTE },
  );
}

function handlers(body: unknown): Parameters<typeof makeFetch>[0] {
  return [
    ['/simulator/driver-action', () => ({ body: EXECUTION_RESPONSE })],
    ['/snapshot', () => ({ body })],
  ];
}

describe('the instruction lifecycle on the driver screen', () => {
  it('shows nothing for a proposed recommendation the engineer has not acted on', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('proposed')));
    renderDriver(stub);
    await waitFor(() =>
      expect(screen.getByTestId('driver-primary')).toHaveTextContent('NO INSTRUCTION'),
    );
    expect(screen.queryByText(SESSION_SNAPSHOT.recommendation?.display_text ?? '')).toBeNull();
  });

  it('shows the instruction once the engineer has communicated it', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub);
    await waitFor(() =>
      expect(screen.getByTestId('driver-primary')).toHaveTextContent(
        SESSION_SNAPSHOT.recommendation?.display_text ?? '',
      ),
    );
    expect(screen.getByText(/^FROM /)).toBeInTheDocument();
    expect(screen.getByText(/^UNTIL /)).toBeInTheDocument();
  });

  it('clears the instruction when the local watchdog fires', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub, 300);

    await waitFor(() =>
      expect(screen.getByTestId('driver-primary')).toHaveTextContent(
        SESSION_SNAPSHOT.recommendation?.display_text ?? '',
      ),
    );

    await waitFor(
      () => expect(screen.getByTestId('driver-primary')).toHaveTextContent('NO LIVE DATA'),
      { timeout: 3_000 },
    );
    expect(screen.getByTestId('aged-context')).toHaveTextContent('not being updated');
  });
});

describe('simulator input', () => {
  it('is operable from the keyboard and reports an execution', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub);

    const overtake = await screen.findByRole('button', { name: 'overtake' });
    overtake.focus();
    expect(overtake).toHaveFocus();
    await user.keyboard('{Enter}');

    await waitFor(() => expect(stub.matching('/simulator/driver-action').length).toBe(1));
    const request = stub.matching('/simulator/driver-action')[0];
    expect(request?.method).toBe('POST');
    expect(request?.headers['idempotency-key']).toBeTruthy();
    expect(request?.body).toMatchObject({ profile_id: 'overtake', recommendation_id: 'rec-001' });
    expect(await screen.findByTestId('driver-execution')).toHaveTextContent('overtake · matched');
  });

  it('refuses to offer a driver action for a session that is not a simulation', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(
      handlers(
        snapshot({ manifest: { ...SESSION_SNAPSHOT.manifest, mode: 'live_team' } }),
      ),
    );
    renderDriver(stub);

    await waitFor(() =>
      expect(screen.getByTestId('driver-primary')).toHaveTextContent('NOT A SIMULATOR SESSION'),
    );
    const buttons = screen.getAllByRole('button');
    for (const button of buttons) {
      expect(button).toBeDisabled();
    }
    await user.click(buttons[0] as HTMLElement);
    expect(stub.matching('/simulator/driver-action')).toEqual([]);
  });
});

describe('what the driver screen never shows', () => {
  it('carries no probability, no percentage forecast and no telemetry log', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub);
    await waitFor(() =>
      expect(screen.getByTestId('driver-primary')).toHaveTextContent(
        SESSION_SNAPSHOT.recommendation?.display_text ?? '',
      ),
    );

    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/probabilit/i);
    expect(text).not.toMatch(/confidence/i);
    expect(text).not.toMatch(/\b\d{1,3}\s?% (chance|likely|probability)/i);
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('states the energy target with a shape as well as words', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub);
    const target = await screen.findByTestId('energy-target');
    expect(target.textContent ?? '').toMatch(/ENERGY (ABOVE|BELOW) TARGET|TARGET UNKNOWN/);
  });

  it('applies the dark driver token scope and nothing else does', async () => {
    const stub = makeFetch(handlers(withRecommendationStatus('communicated')));
    renderDriver(stub);
    const scope = await screen.findByTestId('driver-scope');
    expect(scope.className).toContain('afterlap-driver-scope');
  });
});
