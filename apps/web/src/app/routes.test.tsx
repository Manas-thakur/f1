import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from './Providers';
import { AppRoutes } from './routes';
import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';
import { useSessionStore } from '../state/sessionStore';
import { SESSION_SNAPSHOT } from '../test/contractFixtures';

function hrefOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const SESSION_LIST = {
  sessions: [
    {
      id: 'synthetic-battle-001',
      mode: 'simulation',
      status: 'running',
      revision: 7,
      created_at: '2026-09-08T12:00:00Z',
      label: 'Synthetic battle',
      synthetic: true,
      scenario_id: 'battle-undercut-1',
    },
  ],
  next_cursor: null,
};

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Providers withRouter={false} queryClient={queryClient}>
        <AppRoutes />
      </Providers>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request) => {
      const url = hrefOf(input);


      if (url.includes('/snapshot')) {
        return jsonResponse(SESSION_SNAPSHOT);
      }
      if (url.includes('/models')) {
        return jsonResponse({ models: [] });
      }
      if (url.includes('/experiments')) {
        return jsonResponse([]);
      }
      if (url.includes('/sessions')) {
        return jsonResponse(SESSION_LIST);
      }
      return jsonResponse({ error: { code: 'not_found', message: 'no route', retryable: false, request_id: 'r' } }, 404);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('every route renders exactly one h1 and the required landmarks', () => {
  const routes: readonly [string, string | RegExp][] = [
    ['/', /Decide where electrical energy changes the race/],
    ['/simulation-lab', /Reproducible experiments/],
    ['/sessions', 'Sessions'],
    ['/lab', 'Simulation lab'],
    ['/settings', 'Settings'],
    ['/sessions/s1/engineer', 'Engineer console'],
    ['/sessions/s1/lab', 'Simulation lab'],
    ['/sessions/s1/replay', 'Replay'],
    ['/sessions/s1/driver', 'Driver display'],
    ['/experiments/e1/report', 'Experiment report'],
    ['/rulesets/r1', 'Ruleset'],
    ['/models', 'Models'],
    ['/nowhere', 'No such route'],
  ];

  for (const [path, heading] of routes) {
    it(`renders ${path}`, async () => {
      renderAt(path);
      const headings = await screen.findAllByRole('heading', { level: 1 });
      expect(headings).toHaveLength(1);
      expect(headings[0]).toHaveTextContent(heading);
      expect(screen.getByRole('main')).toBeInTheDocument();
      expect(screen.getByRole('contentinfo')).toBeInTheDocument();
      expect(screen.getByRole('banner')).toBeInTheDocument();
    });
  }
});

describe('the synthetic-data notice', () => {
  it('is visible on the product page and inside the workspace', async () => {
    const marketing = renderAt('/');
    expect(screen.getByTestId('synthetic-data-notice')).toHaveTextContent(SYNTHETIC_DATA_NOTICE);
    marketing.unmount();

    renderAt('/settings');
    expect(screen.getByTestId('synthetic-data-notice')).toHaveTextContent(SYNTHETIC_DATA_NOTICE);
  });
});

describe('feature routes render their own view', () => {
  it('the engineer console names its decision panel rather than a placeholder', async () => {
    renderAt('/sessions/s1/engineer');
    expect(await screen.findByRole('heading', { name: 'Decision' })).toBeInTheDocument();
    expect(screen.queryByText(/owned by/)).toBeNull();
  });

  it('the lab, replay and driver routes render their own controls', async () => {
    const lab = renderAt('/sessions/s1/lab');
    expect(await screen.findByRole('heading', { name: 'Run control' })).toBeInTheDocument();
    lab.unmount();

    const replay = renderAt('/sessions/s1/replay');
    expect(
      await screen.findByRole('heading', { name: 'Alignment and cursor' }),
    ).toBeInTheDocument();
    replay.unmount();

    renderAt('/sessions/s1/driver');
    expect(await screen.findByTestId('driver-primary')).toBeInTheDocument();
  });
});

describe('sessions route', () => {
  it('lists sessions from the control plane with their mode and source', async () => {
    renderAt('/sessions');
    expect(await screen.findByRole('link', { name: 'Synthetic battle' })).toBeInTheDocument();
    expect(screen.getByText('simulation')).toBeInTheDocument();
    expect(screen.getByText('synthetic')).toBeInTheDocument();
  });

  it('shows a named empty state when the control plane has no sessions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ sessions: [], next_cursor: null })));
    renderAt('/sessions');
    expect(await screen.findByText(/missing artefact: session manifest/)).toBeInTheDocument();
  });

  it('says which pack "current" means when no session is open', async () => {
    useSessionStore.getState().reset();
    renderAt('/rulesets/current');

    expect(
      await screen.findByText(/No session is loaded, so there is no current pack/),
    ).toBeInTheDocument();
  });

  it('sends an operator with no sessions somewhere that can create one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ sessions: [], next_cursor: null })));
    renderAt('/sessions');

    const link = await screen.findByRole('link', { name: /simulation laboratory/i });
    expect(link).toHaveAttribute('href', '/lab');
  });

  it('shows a typed error with its guidance and request id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'capability_unavailable',
              message: 'session store is offline',
              retryable: false,
              request_id: 'req-77',
            },
          },
          503,
        ),
      ),
    );
    renderAt('/sessions');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('session store is offline');
    expect(alert).toHaveTextContent('req-77');
  });
});

describe('settings route', () => {
  it('changes density and motion, and applies them to the document root', async () => {
    const user = userEvent.setup();
    renderAt('/settings');

    await user.click(screen.getByRole('radio', { name: /Compact/ }));
    await waitFor(() => expect(document.documentElement.dataset['density']).toBe('compact'));

    await user.click(screen.getByRole('radio', { name: /Reduce motion/ }));
    await waitFor(() => expect(document.documentElement.dataset['motion']).toBe('reduce'));

    await user.click(screen.getByRole('radio', { name: /Follow the operating system/ }));
    await waitFor(() => expect(document.documentElement.dataset['motion']).toBeUndefined());
  });

  it('opens the sample inspector and returns focus to its invoking control', async () => {
    const user = userEvent.setup();
    renderAt('/settings');
    const invoker = screen.getByRole('button', { name: 'Open a sample inspector' });
    await user.click(invoker);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(invoker).toHaveFocus();
  });
});

describe('module rail', () => {
  it('uses plain named modules with no numbering', async () => {
    renderAt('/sessions');
    const nav = await screen.findByRole('navigation', { name: 'Modules' });
    const links = within(nav).getAllByRole('link');
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link.textContent ?? '').not.toMatch(/^\s*\d/);
    }
  });
});
