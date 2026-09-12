import { expect, test } from '@playwright/test';
import { connect, createServer } from 'node:net';
import type { Socket } from 'node:net';

test('live race controls, circuit switching, checkpoint restore and telemetry export', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race/control');
  await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('monza');
  await page.getByLabel('Cars', { exact: true }).fill('2');
  await page.getByLabel('Laps', { exact: true }).fill('5');
  await page.getByLabel('Time limit (s)').fill('30');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Circuit view', exact: true }).click();
  await expect(page.getByLabel('Live circuit')).toContainText('MONZA');
  await expect(page.getByRole('button', { name: 'car-01', exact: true })).toBeVisible();
  await expect(page.getByLabel('Race lap', { exact: true })).toHaveText('LAP 1 / 5');
  await expect(page.getByLabel('Selected car lap', { exact: true })).toHaveText('LAP 1 / 5');
  await expect(page.getByRole('progressbar', { name: 'Selected car lap progress' })).toHaveAttribute(
    'value',
    /\d/,
  );
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

test('race websocket follows a forwarded dashboard port', async ({ page }) => {
  const sockets = new Set<Socket>();
  const forwarder = createServer((client) => {
    const upstream = connect(18760, '127.0.0.1');
    for (const socket of [client, upstream]) {
      sockets.add(socket);
      socket.on('close', () => sockets.delete(socket));
      socket.on('error', () => {
        client.destroy();
        upstream.destroy();
      });
    }
    client.pipe(upstream).pipe(client);
  });
  await new Promise<void>((resolve) => forwarder.listen(0, '127.0.0.1', resolve));
  try {
    const address = forwarder.address();
    if (!address || typeof address === 'string') {
      throw new Error('Forwarded port unavailable');
    }
    const websocketUrls: string[] = [];
    page.on('websocket', (websocket) => websocketUrls.push(websocket.url()));
    await page.goto(`http://localhost:${address.port}/race/control`);
    await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
    expect(websocketUrls).toContain(`ws://localhost:${address.port}/race/socket`);
    expect(websocketUrls.some((url) => url.includes(':18761'))).toBe(false);
    await page.getByLabel('Cars', { exact: true }).fill('1');
    await page.getByRole('button', { name: 'Reset race', exact: true }).click();
    await page.getByRole('button', { name: 'Start race', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Pause race', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Start race', exact: true })).toBeVisible();
  } finally {
    for (const socket of sockets) {
      socket.destroy();
    }
    await new Promise<void>((resolve) => forwarder.close(() => resolve()));
  }
});
