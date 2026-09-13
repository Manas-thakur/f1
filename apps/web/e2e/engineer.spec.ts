import { expect, test } from '@playwright/test';

test('hardware POST to the engineer address reaches the boost API', async ({ request }) => {
  const response = await request.post('/race/engineer');
  expect(response.headers()['content-type']).toContain('application/json');
  expect([200, 409]).toContain(response.status());
  const payload = await response.json();
  expect(payload.operation === 'boost' || typeof payload.error === 'string').toBe(true);
  const release = await request.post('/race/boost/off');
  expect(release.status()).toBe(200);
  await expect(release.json()).resolves.toMatchObject({ operation: 'boost-off', status: 'accepted' });
});

test('race engineer console presents live evidence and labeled model placeholders', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race/engineer');
  await expect(page.getByText('RACE ENGINEERING', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Live camera wall')).toBeVisible();
  await expect(page.locator('figure')).toHaveCount(6);
  await expect(page.getByLabel('Model predictions')).toContainText('SCENARIO MOCK');
  await expect(page.getByLabel('Circuit tracker')).not.toContainText('Waiting for circuit');
  await expect(page.getByLabel('Energy deployment by lap')).toBeVisible();
  await expect(page.getByLabel('Decision execution')).toContainText('MOCK');
  await expect(page.getByLabel('Prediction validation')).toBeVisible();
  await expect(page.getByText('LIVE', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Live camera wall').locator('[data-rendered-frames]'))
    .toHaveCount(6, { timeout: 60000 });
  await expect(page.getByLabel('Live camera wall').locator('[data-camera-mode="trackside"]'))
    .toHaveCount(6);
  await expect(page.getByLabel('Decision execution').locator('ol > li')).toHaveCount(3);
  await expect(page.getByLabel('Prediction validation'))
    .toContainText('Opportunity present · boost used');
  expect(errors).toEqual([]);
});

test('simulator toolbar exposes the dashboard in a flush sticky header', async ({ page }) => {
  await page.goto('/race');
  const dashboard = page.getByRole('link', { name: 'Dashboard' });
  await expect(dashboard).toBeVisible();
  await expect(dashboard).toHaveAttribute('href', '/race/engineer');
  const toolbar = dashboard.locator('..');
  await expect(toolbar).toHaveCSS('position', 'sticky');
  await expect(toolbar).toHaveCSS('top', '0px');
  await expect(toolbar).toHaveCSS('border-top-left-radius', '0px');
});

test('console remains usable on a narrow display', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/race/engineer');
  await expect(page.getByLabel('Live camera wall')).toBeVisible();
  await expect(page.getByRole('link', { name: 'FULL SIM' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
