import { expect, test } from '@playwright/test';

test('race engineer console presents live evidence and labeled model placeholders', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race/engineer');
  await expect(page.getByText('RACE ENGINEERING', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Live camera wall')).toBeVisible();
  await expect(page.locator('figure')).toHaveCount(4);
  await expect(page.getByLabel('Model predictions')).toContainText('SCENARIO MOCK');
  await expect(page.getByLabel('Circuit tracker')).not.toContainText('Waiting for circuit');
  await expect(page.getByLabel('Energy deployment by lap')).toBeVisible();
  await expect(page.getByLabel('Decision execution')).toContainText('MOCK');
  await expect(page.getByLabel('Prediction validation')).toBeVisible();
  await expect(page.getByText('LIVE', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Live camera wall').locator('[data-rendered-frames]'))
    .toHaveCount(4, { timeout: 60000 });
  expect(errors).toEqual([]);
});

test('console remains usable on a narrow display', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/race/engineer');
  await expect(page.getByLabel('Live camera wall')).toBeVisible();
  await expect(page.getByRole('link', { name: 'FULL SIM' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
