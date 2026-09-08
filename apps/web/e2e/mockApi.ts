import type { Page, Route } from '@playwright/test';


export const MOCK_SESSIONS = {
  sessions: [
    {
      id: 'synthetic-battle-001',
      mode: 'simulation',
      status: 'running',
      revision: 7,
      created_at: '2026-09-08T12:00:00Z',
      label: 'Synthetic battle, undercut window',
      synthetic: true,
      scenario_id: 'battle-undercut-1',
    },
    {
      id: 'synthetic-battle-002',
      mode: 'replay',
      status: 'completed',
      revision: 22,
      created_at: '2026-09-08T13:30:00Z',
      label: 'Replay, defended attack',
      synthetic: true,
      scenario_id: 'battle-defend-2',
    },
  ],
  next_cursor: null,
} as const;

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

export async function mockApi(page: Page): Promise<void> {


  await page.route('**/api/v1/**', (route) =>
    json(
      route,
      {
        error: {
          code: 'not_found',
          message: 'not mocked in the end-to-end suite',
          retryable: false,
          request_id: 'e2e',
        },
      },
      404,
    ),
  );
  await page.route('**/api/v1/sessions*', (route) => json(route, MOCK_SESSIONS));
  await page.route('**/api/v1/models*', (route) => json(route, { models: [] }));
}


export async function mockEmptyApi(page: Page): Promise<void> {
  await page.route('**/api/v1/sessions*', (route) =>
    json(route, { sessions: [], next_cursor: null }),
  );
}
