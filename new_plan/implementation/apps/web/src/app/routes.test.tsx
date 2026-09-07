import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from './Providers';
import { AppRoutes } from './routes';
import { SYNTHETIC_DATA_NOTICE } from '../fixtures/notices';

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
      const url = String(input);
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
    ['/', /Energy deployment decisions/],
    ['/simulation-lab', /Reproducible experiments/],
    ['/sessions', 'Sessions'],
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

describe('feature route placeholders', () => {
  it('name the owning agent and the missing artefact, and draw no fake chart', async () => {
    renderAt('/sessions/s1/engineer');
    expect(await screen.findByText(/owned by/)).toHaveTextContent('A09');
    expect(screen.getByText(/missing artefact:/)).toBeInTheDocument();
    expect(screen.queryByRole('slider')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('names A10 for the lab and replay routes and A11 for the driver route', async () => {
    const lab = renderAt('/sessions/s1/lab');
    expect(await screen.findByText(/owned by/)).toHaveTextContent('A10');
    lab.unmount();

    const replay = renderAt('/sessions/s1/replay');
    expect(await screen.findByText(/owned by/)).toHaveTextContent('A10');
    replay.unmount();

    renderAt('/sessions/s1/driver');
    expect(await screen.findByText(/owned by/)).toHaveTextContent('A11');
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
