import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { useSessionStore } from '@/state/sessionStore';
import { SESSION_SNAPSHOT } from '@/test/contractFixtures';
import { telemetryEnvelope } from '@/test/envelopes';
import type {
  FakeSocket} from '../engineer/testUtils';
import {
  apiClientFor,
  makeFetch,
  renderRoute,
  socketFactory,
  type FetchStub,
} from '../engineer/testUtils';
import { ReplayView } from './ReplayView';

const SESSION_ID = SESSION_SNAPSHOT.session_id;
const PATH = `/sessions/${SESSION_ID}/replay`;
const ROUTE = '/sessions/:sessionId/replay';

function handlers(snapshot: unknown = SESSION_SNAPSHOT): Parameters<typeof makeFetch>[0] {
  return [['/snapshot', () => ({ body: snapshot })]];
}

function renderReplay(stub: FetchStub, sockets: FakeSocket[] = []) {
  const client = apiClientFor(stub);
  return renderRoute(
    <ReplayView runtimeOptions={{ client, socketFactory: socketFactory(sockets) }} />,
    { path: PATH, route: ROUTE },
  );
}

async function withTelemetry(stub: FetchStub): Promise<FakeSocket> {
  const sockets: FakeSocket[] = [];
  renderReplay(stub, sockets);
  await waitFor(() => expect(sockets.length).toBe(1));
  const socket = sockets[0] as FakeSocket;
  socket.emit(telemetryEnvelope(SESSION_SNAPSHOT.last_sequence + 1));
  await waitFor(() =>
    expect(Object.keys(useSessionStore.getState().server.telemetry).length).toBeGreaterThan(0),
  );
  return socket;
}

describe('alignment is stated, never implied', () => {
  it('labels the default alignment as common progress', async () => {
    const stub = makeFetch(handlers());
    renderReplay(stub);
    expect(
      (await screen.findAllByText(/common progress \(metres travelled\)/)).length,
    ).toBeGreaterThan(0);
  });

  it('switches to common elapsed time and relabels every panel', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers());
    await withTelemetry(stub);

    await user.click(
      screen.getByRole('radio', { name: /common elapsed time/ }),
    );

    await waitFor(() =>
      expect(useSessionStore.getState().view.cursorAxis).toBe('session_time_s'),
    );
    expect(
      screen.getAllByText(/Aligned at common elapsed time/).length,
    ).toBeGreaterThan(0);
  });

  it('says when a published series is indexed by a different coordinate', async () => {
    const user = userEvent.setup();
    const stub = makeFetch(handlers());
    await withTelemetry(stub);

    await user.click(screen.getByRole('radio', { name: /common elapsed time/ }));


    expect(await screen.findByTestId('axis-mismatch')).toHaveTextContent(
      'are not re-indexed, because re-indexing without a mapping would invent samples',
    );
  });
});

describe('the shared cursor', () => {
  it('is the workspace cursor, not a second chart-event protocol', async () => {
    const stub = makeFetch(handlers());
    await withTelemetry(stub);

    const sliders = await screen.findAllByRole('slider');
    expect(sliders.length).toBeGreaterThan(0);
    const slider = sliders[0] as HTMLInputElement;


    fireEvent.change(slider, { target: { value: '15' } });

    await waitFor(() => expect(useSessionStore.getState().view.cursorValue).not.toBeNull());
    expect(await screen.findByText(/Current position/)).toBeInTheDocument();
  });
});

describe('seeking', () => {
  it('offers no snapshot restore, and says exactly why', async () => {
    const stub = makeFetch(handlers());
    renderReplay(stub);
    const notice = await screen.findByTestId('seek-unavailable');
    expect(notice).toHaveTextContent('there is no seek command');
    expect(notice).toHaveTextContent('changes no server state');
    expect(screen.getByRole('button', { name: /Restore/ })).toBeDisabled();
  });

  it('refuses to seek a live-team session’s authoritative clock', async () => {
    const stub = makeFetch(
      handlers({
        ...SESSION_SNAPSHOT,
        manifest: { ...SESSION_SNAPSHOT.manifest, mode: 'live_team' },
      }),
    );
    renderReplay(stub);
    await waitFor(() =>
      expect(screen.getByTestId('seek-unavailable')).toHaveTextContent(
        'cannot seek its authoritative clock',
      ),
    );
  });
});

describe('nothing is drawn that did not arrive', () => {
  it('names the missing artefact instead of a placeholder trajectory', async () => {
    const stub = makeFetch(handlers());
    renderReplay(stub);
    expect(
      await screen.findByText(/missing artefact: telemetry_view series/),
    ).toBeInTheDocument();
  });
});
