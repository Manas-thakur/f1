import path from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { CreateSessionResponse, DriverActionResponse, SessionSnapshot } from '@contracts';

async function post(request: APIRequestContext, url: string, data: unknown) {
  const response = await request.post(`/api/v1${url}`, {
    data,
    headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-Operator-Id': 'console-operator' },
    timeout: 60_000,
  });
  expect(response.ok(), await response.text()).toBe(true);
  return response;
}

async function snapshot(request: APIRequestContext, id: string): Promise<SessionSnapshot> {
  const response = await request.get(`/api/v1/sessions/${id}/snapshot`);
  expect(response.ok()).toBe(true);
  return (await response.json()) as SessionSnapshot;
}

async function capture(page: Page, name: string): Promise<void> {
  const output = process.env.AFTERLAP_AUDIT_OUTPUT;
  if (output !== undefined) {
    await page.screenshot({ path: path.join(output, name), fullPage: false });
  }
}

test('browser-created session completes the engineer and driver lifecycle', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/lab');
  await page.getByLabel('Scenario id', { exact: false }).fill('two-straight-counterattack');
  await page.getByLabel('Rule pack id', { exact: false }).fill('synthetic-pack-v1');
  await page.getByLabel('Seed', { exact: false }).fill('42');
  await page.getByLabel('I acknowledge').check();
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/sessions') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create session', exact: true }).click();
  const response = await createdResponse;
  expect(response.status()).toBe(201);
  const created = (await response.json()) as CreateSessionResponse;
  const id = created.manifest.id;
  await page.getByRole('link', { name: 'Open its laboratory' }).click();
  const leaseResponse = page.waitForResponse((item) => item.url().endsWith('/control-lease'));
  await page.getByRole('button', { name: 'Acquire control', exact: true }).click();
  expect((await leaseResponse).ok()).toBe(true);
  await expect(page.getByRole('button', { name: 'Renew control' })).toBeVisible();
  const startedResponse = page.waitForResponse((item) => item.url().endsWith('/commands'));
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  expect((await startedResponse).ok()).toBe(true);
  let state = await snapshot(request, id);
  for (let step = 0; step < 60; step += 1) {
    if (
      state.recommendation !== null &&
      state.recommendation !== undefined &&
      state.recommendation.action_code !== 'withdraw_advice'
    ) {
      break;
    }
    await post(request, `/sessions/${id}/commands`, {
      kind: 'step',
      expected_revision: state.revision,
      operator_id: 'console-operator',
      step_duration_s: 1,
    });
    state = await snapshot(request, id);
  }
  expect(state.recommendation).not.toBeNull();
  expect(state.recommendation?.action_code).not.toBe('withdraw_advice');
  await page.goto(`/sessions/${id}/engineer`);
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await expect.poll(async () => (await snapshot(request, id)).recommendation?.status).toBe('selected');
  await page.getByRole('button', { name: 'Mark communicated', exact: true }).click();
  await expect.poll(async () => (await snapshot(request, id)).recommendation?.status).toBe('communicated');
  await capture(page, 'engineer.png');
  state = await snapshot(request, id);
  const profile = state.recommendation?.display_text.split(' ')[0]?.toLowerCase();
  expect(profile).toBeDefined();
  await page.goto(`/sessions/${id}/driver`);
  await capture(page, 'driver.png');
  const driverResponse = page.waitForResponse((item) => item.url().endsWith('/simulator/driver-action'));
  await page.getByRole('button', { name: profile ?? '', exact: true }).click();
  const executedResponse = await driverResponse;
  expect(executedResponse.ok()).toBe(true);
  const executed = (await executedResponse.json()) as DriverActionResponse;
  expect(executed.execution.recommendation_id).toBe(state.recommendation?.id);
  expect(['executing', 'completed']).toContain(executed.recommendation?.status);
  state = await snapshot(request, id);
  await post(request, `/sessions/${id}/commands`, {
    kind: 'step',
    expected_revision: state.revision,
    operator_id: 'console-operator',
    step_duration_s: 1,
  });
  state = await snapshot(request, id);
  await page.goto(`/sessions/${id}/lab`);
  await page.getByRole('button', { name: 'Create snapshot', exact: true }).click();
  await expect(page.getByText(/sha256:/).first()).toBeVisible();
  await page.getByLabel('Candidate controller', { exact: false }).fill('legal_greedy_attacker');
  const jobResponse = page.waitForResponse(
    (item) => item.url().endsWith('/experiments') && item.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Queue paired experiment' }).click();
  const job = (await (await jobResponse).json()) as { job: { id: string } };
  await expect
    .poll(
      async () => {
        const status = await request.get(`/api/v1/experiments/${job.job.id}`);
        const payload = (await status.json()) as { status: string };
        return payload.status;
      },
      { timeout: 180_000, intervals: [1000] },
    )
    .toBe('completed');
  await capture(page, 'lab.png');
  const exported = await post(request, '/exports', { session_id: id, format: 'json' });
  const exportBody = (await exported.json()) as { status: string; hashes: { content: string } };
  expect(exportBody.status).toBe('completed');
  expect(exportBody.hashes.content).toMatch(/^sha256:[a-f0-9]{64}$/);
  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([]);
  expect(errors).toEqual([]);
});

test('HTTP and stream boundaries reject malformed input without a server crash', async ({ request }) => {
  for (const seed of [true, '42', -1, 2 ** 32]) {
    const response = await request.post('/api/v1/sessions', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: {
        mode: 'simulation',
        scenario_id: 'two-straight-counterattack',
        ruleset_id: 'synthetic-pack-v1',
        seed,
      },
    });
    expect(response.status()).toBe(422);
  }
  expect((await request.post('/api/v1/sessions', { data: 'x'.repeat(65_537) })).status()).toBe(413);
  expect((await request.get('/api/v1/sessions/missing/stream?after_sequence=nan')).status()).toBe(400);
  expect((await request.get('/api/v1/health/live')).status()).toBe(200);
});

for (const route of [
  '/',
  '/simulation-lab',
  '/sessions',
  '/lab',
  '/models',
  '/settings',
  '/rulesets/synthetic-pack-v1',
  '/experiments/missing/report',
  '/missing-page',
]) {
  test(`live route and responsive layout: ${route}`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(route);
    await expect(page.locator('h1').first()).toBeVisible();
    for (const width of [320, 375, 414, 768, 1024, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(overflow, `${route} overflows at ${width}px`).toBe(false);
    }
    expect(errors).toEqual([]);
  });
}
