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
  await expect(page.getByRole('navigation', { name: 'Pages' }).getByRole('link', { name: 'Engineer' }))
    .toHaveAttribute('aria-current', 'page');
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

test('site root opens the race view with shared page navigation', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/race$/);
  const nav = page.getByRole('navigation', { name: 'Pages' });
  await expect(nav.getByRole('link', { name: 'Race', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(nav.getByRole('link', { name: 'Engineer' })).toHaveAttribute('href', '/race/engineer');
});

test('simulator toolbar exposes shared navigation and a right-side controls menu', async ({ page }) => {
  await page.goto('/race');
  const toolbar = page.locator('header[aria-label="Site"]');
  const engineer = toolbar.getByRole('link', { name: 'Engineer' });
  await expect(engineer).toBeVisible();
  await expect(engineer).toHaveAttribute('href', '/race/engineer');
  await expect(toolbar).toHaveCSS('position', 'sticky');
  await expect(toolbar).toHaveCSS('top', '0px');
  await expect(toolbar).toHaveCSS('border-top-left-radius', '0px');
  const menu = page.getByRole('button', { name: 'Race controls', exact: true });
  const menuBox = await menu.boundingBox();
  const barBox = await toolbar.boundingBox();
  expect(menuBox && barBox).toBeTruthy();
  const menuRight = (menuBox?.x ?? 0) + (menuBox?.width ?? 0);
  const barRight = (barBox?.x ?? 0) + (barBox?.width ?? 0);
  expect(menuRight).toBeGreaterThan(barRight * 0.8);
});

test('console remains usable on a narrow display', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/race/engineer');
  await expect(page.getByLabel('Live camera wall')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Race', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
