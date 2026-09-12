import { expect, test } from '@playwright/test';

test('live race controls, circuit switching, checkpoint restore and telemetry export', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race/control');
  await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('monza');
  await page.getByLabel('Cars', { exact: true }).fill('2');
  await page.getByLabel('Time limit (s)').fill('30');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Circuit view', exact: true }).click();
  await expect(page.getByLabel('Live circuit')).toContainText('MONZA');
  await expect(page.getByRole('button', { name: 'car-01', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pause race', exact: true }).click();
  await page.getByRole('link', { name: 'Race control', exact: true }).click();
  await page.getByRole('button', { name: 'Save checkpoint' }).click();
  await expect(page.getByRole('button', { name: 'Restore checkpoint' })).toBeEnabled();
  await page.getByRole('button', { name: 'Step 0.01s' }).click();
  await page.getByRole('button', { name: 'Restore checkpoint' }).click();
  await page.getByRole('combobox', { name: 'Battery profile', exact: true }).selectOption('harvest');
  await page.getByRole('button', { name: 'Apply driver command' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download recent telemetry' }).click();
  expect((await download).suggestedFilename()).toContain('race-telemetry');
  await page.screenshot({ path: '/tmp/race-control.png', fullPage: true });
  await page.getByRole('link', { name: 'Circuit view', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Race simulator', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/race-circuit.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '/tmp/race-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(errors).toEqual([]);
});
