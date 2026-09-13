import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import { connect, createServer } from 'node:net';
import type { Socket } from 'node:net';

async function applyAvailableBoost(page: Page, boost: Locator) {
  let rejected: unknown = null;
  for (let attempt = 0; attempt < 10; attempt++) {
    const [response] = await Promise.all([
      page.waitForResponse((candidate) => (
        candidate.request().method() === 'POST'
          && new URL(candidate.url()).pathname === '/race/boost'
      )),
      expect.poll(async () => boost.evaluate((button) => {
        if (!(button instanceof HTMLButtonElement) || button.disabled) {
          return false;
        }
        button.click();
        return true;
      }), { timeout: 60000 }).toBe(true),
    ]);
    const payload = await response.json();
    if (response.ok()) {
      return payload;
    }
    rejected = payload;
  }
  throw new Error(`Boost stayed unavailable: ${JSON.stringify(rejected)}`);
}

test('orbit attaches to the first observed car after start, reset and car switching', async ({ page }) => {
  test.slow();
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('madring');
  await page.getByLabel('Cars', { exact: true }).fill('2');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  const initialSelection = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/race/selection/car-01'
  ));
  await page.getByRole('button', { name: 'car-01', exact: true }).click();
  await initialSelection;
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await expect(page.getByRole('button', { name: 'Car orbit', exact: true })).toBeEnabled();
  const distanceToTarget = async () => scene.evaluate((element) => {
    const car = element.getAttribute('data-followed-position')?.split(',').map(Number);
    const target = element.getAttribute('data-camera-target')?.split(',').map(Number);
    if (car?.length !== 3 || target?.length !== 3) {
      return Infinity;
    }
    return Math.hypot((car[0] ?? 0) - (target[0] ?? 0), (car[2] ?? 0) - (target[2] ?? 0));
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt === 0) {
      await expect(scene).toHaveAttribute('data-followed-position', '');
      await scene.hover({ position: { x: 500, y: 450 } });
      await page.mouse.wheel(0, -60);
      await expect(scene).toHaveAttribute('data-camera-mode', 'orbit');
    } else {
      await page.getByRole('button', { name: 'Car orbit', exact: true }).click();
    }
    await page.getByRole('button', { name: 'Start race', exact: true }).click();
    await expect.poll(distanceToTarget).toBeLessThan(0.1);
    const switched = attempt === 0 ? page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/race/selection/car-02'
    )) : null;
    await page.getByRole('button', { name: 'Watch car behind', exact: true }).click();
    if (switched) {
      expect(await (await switched).json()).toMatchObject({ car_id: 'car-02', status: 'accepted' });
    }
    await expect.poll(distanceToTarget).toBeLessThan(0.1);
    await expect(scene).toHaveAttribute('data-camera-mode', 'orbit');
    await page.getByRole('button', { name: 'Pause race', exact: true }).click();
    await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  }
});

test('overlays fit below the toolbar and above the minimap when the view narrows', async ({ page }) => {
  await page.goto('/race');
  for (const size of [{ width: 900, height: 650 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    if (size.width === 900) {
      await page.getByRole('button', { name: 'Race controls', exact: true }).click();
    } else {
      await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
    }
    await expect.poll(async () => page.evaluate(() => {
      const toolbar = document.querySelector('[class*="mapTools"]')?.getBoundingClientRect();
      const list = document.querySelector('[class*="classification"]')?.getBoundingClientRect();
      const map = document.querySelector('[class*="minimap"]')?.getBoundingClientRect();
      return Boolean(toolbar && list && map && list.top >= toolbar.bottom && list.bottom <= map.top);
    })).toBe(true);
  }
});

test('live race controls, circuit switching, checkpoint restore and telemetry export', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Chase', exact: true })).toBeEnabled();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('monza');
  await expect(page.getByRole('combobox', { name: 'Lap preset', exact: true })).toHaveValue('grand-prix');
  await expect(page.getByText('53 laps from the official 2026 circuit listing.')).toBeVisible();
  await page.getByRole('combobox', { name: 'Variability', exact: true }).selectOption('training');
  await page.getByRole('combobox', { name: 'Weather', exact: true }).selectOption('rainy');
  await page.getByLabel('Cars', { exact: true }).fill('2');
  await page.getByRole('combobox', { name: 'Lap preset', exact: true }).selectOption('custom');
  await page.getByLabel('Custom laps', { exact: true }).fill('5');
  await page.getByLabel('Time limit (s)').fill('1800');
  await expect(page.getByRole('combobox', { name: 'Circuit', exact: true })).toHaveValue('monza');
  await expect(page.getByLabel('Custom laps', { exact: true })).toHaveValue('5');
  expect(await page.locator('form').first().evaluate((form) => form instanceof HTMLFormElement && form.checkValidity())).toBe(true);
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await expect(page.getByLabel('Live circuit')).toContainText('MONZA');
  await expect(page.getByRole('application', { name: '3D camera controls' }))
    .toHaveAttribute('data-observed-time', '0');
  await expect(page.getByRole('application', { name: '3D camera controls' }))
    .toHaveAttribute('data-weather', 'rainy');
  await expect(page.getByText('Tire compound', { exact: true })).toBeVisible();
  await expect(page.getByText('Energy decision engine', { exact: true })).toBeVisible();
  await expect(page.getByText('Scenario boost classification', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Chase', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Step 0.01s', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
  await expect(page.getByLabel('Live circuit')).toContainText('MONZA');
  await expect(page.getByRole('button', { name: 'car-01', exact: true })).toBeVisible();
  await expect(page.getByLabel('Race lap', { exact: true })).toHaveText('LAP 1 / 5');
  await expect(page.getByLabel('Selected car lap', { exact: true })).toHaveText('LAP 1 / 5');
  await expect(page.getByRole('progressbar', { name: 'Selected car lap progress' })).toHaveAttribute(
    'value',
    /\d/,
  );
  await page.getByRole('button', { name: 'Pause race', exact: true }).click();
  await page.getByRole('button', { name: 'Save checkpoint' }).click();
  await expect(page.getByRole('button', { name: 'Restore checkpoint' })).toBeEnabled();
  await page.getByRole('button', { name: 'Step 0.01s' }).click();
  await page.getByRole('button', { name: 'Restore checkpoint' }).click();
  await page.getByRole('combobox', { name: 'Battery profile', exact: true }).selectOption('harvest');
  await page.getByRole('button', { name: 'Apply driver command' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download recent telemetry' }).click();
  expect((await download).suggestedFilename()).toContain('race-telemetry');
  await page.screenshot({ path: test.info().outputPath('race-control.png'), fullPage: true });
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('race-circuit.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath('race-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(errors).toEqual([]);
});

test('race websocket follows a forwarded dashboard port', async ({ page }) => {
  const sockets = new Set<Socket>();
  const forwarder = createServer((client) => {
    const port = Number(new URL(process.env['RACE_TEST_URL'] ?? `http://127.0.0.1:${process.env['RACE_WEB_PORT'] ?? '18860'}`).port);
    const upstream = connect(port, '127.0.0.1');
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
    await page.goto(`http://localhost:${address.port}/race/control`);
    await page.getByRole('button', { name: 'Race controls', exact: true }).click();
    await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
    await expect(page.locator('[data-socket-url]'))
      .toHaveAttribute('data-socket-url', `ws://localhost:${address.port}/race/socket`);
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

test('3D cameras, gestures, selection, paused telemetry and circuit reset', async ({ page }) => {
  test.slow();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await expect(page.getByText('● CONNECTED', { exact: true })).toBeVisible();
  await page.getByLabel('Cars', { exact: true }).fill('3');
  await page.getByLabel('Time limit (s)').fill('1800');
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('silverstone');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await expect(scene).toHaveAttribute('data-rendered-frames', /\d+/, { timeout: 60000 });
  await expect(page.getByRole('button', { name: 'Chase', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Selected car lap', { exact: true })).toContainText('LAP 1');
  await page.getByRole('button', { name: 'Pause race', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start race', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Car orbit', exact: true }).click();
  await expect(scene).toHaveAttribute('data-camera-mode', 'orbit');
  await expect.poll(async () => Number((await scene.getAttribute('data-camera-position'))?.split(',')[1]))
    .toBeCloseTo(3, 2);
  const before = await scene.getAttribute('data-camera-position');
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect.poll(() => scene.getAttribute('data-camera-position')).not.toBe(before);
  const zoomed = await scene.getAttribute('data-camera-position');
  await scene.focus();
  await page.keyboard.press('Meta+-');
  await expect.poll(() => scene.getAttribute('data-camera-position')).not.toBe(zoomed);
  await page.keyboard.press('2');
  await expect(scene).toHaveAttribute('data-camera-mode', 'cockpit');
  await expect.poll(async () => Number((await scene.getAttribute('data-camera-position'))?.split(',')[1]))
    .toBeCloseTo(0.86, 2);
  await expect(page.getByRole('button', { name: 'First person', exact: true }))
    .toHaveAttribute('aria-pressed', 'true');
  const order = await page.getByRole('button', { name: /^car-\d+$/ })
    .evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
  const first = order[0];
  const last = order.at(-1);
  if (!first || !last) {
    throw new Error('Race classification is empty');
  }
  await page.getByRole('button', { name: first, exact: true }).click();
  await page.keyboard.press('ArrowUp');
  await expect(page.getByRole('button', { name: last, exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(scene).toHaveAttribute('data-camera-mode', 'cockpit');
  const minimap = page.getByRole('img', { name: `Circuit minimap tracking ${last}` });
  await expect(minimap).toHaveAttribute('data-selected-car', last);
  await expect(minimap).toHaveAttribute('data-selected-position', /\d/);
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('button', { name: first, exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Minimap', exact: true }).click();
  await expect(page.getByRole('img', { name: /Circuit minimap/ })).toBeHidden();
  await page.keyboard.press('m');
  await expect(page.getByRole('img', { name: /Circuit minimap/ })).toBeVisible();
  await scene.focus();
  await page.keyboard.press('4');
  await expect(scene).toHaveAttribute('data-camera-mode', 'track');
  await page.getByRole('button', { name: 'Reset view', exact: true }).click();
  await expect(scene).toHaveAttribute('data-camera-mode', 'chase');
  const bounds = await scene.boundingBox();
  if (!bounds) {
    throw new Error('3D scene has no visible bounds');
  }
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 350);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 90, bounds.y + 380, { steps: 8 });
  await page.mouse.up();
  await expect(scene).toHaveAttribute('data-camera-mode', 'orbit');
  const dragged = await scene.getAttribute('data-camera-position');
  await page.mouse.wheel(0, -250);
  await expect.poll(() => scene.getAttribute('data-camera-position')).not.toBe(dragged);
  await page.getByRole('button', { name: 'car-03', exact: true }).click();
  await expect(page.getByRole('button', { name: 'car-03', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Controls', exact: true }).click();
  await expect(page.getByText('Explore the circuit', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Controls', exact: true }).click();
  const time = await scene.getAttribute('data-observed-time');
  await page.getByRole('button', { name: 'Car orbit', exact: true }).click();
  await expect.poll(() => scene.getAttribute('data-observed-time')).toBe(time);
  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(false);
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(scene).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Car orbit', exact: true }).click();
  await scene.scrollIntoViewIfNeeded();
  const mobileBounds = await scene.boundingBox();
  if (!mobileBounds) {
    throw new Error('Mobile scene has no bounds');
  }
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true });
  const x = mobileBounds.x + mobileBounds.width / 2;
  const y = mobileBounds.y + 430;
  const cameraBeforeTouch = await scene.getAttribute('data-camera-position');
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart',
    touchPoints: [{ x: x - 30, y, id: 0 }, { x: x + 30, y, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove',
    touchPoints: [{ x: x - 60, y: y + 10, id: 0 }, { x: x + 60, y: y + 10, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => scene.getAttribute('data-camera-position')).not.toBe(cameraBeforeTouch);
  await cdp.detach();
  await page.screenshot({ path: '/tmp/race-3d-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByLabel('Cars', { exact: true }).fill('1');
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('monza');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await expect(page.getByLabel('Live circuit')).toContainText('MONZA');
  await expect(page.getByRole('button', { name: 'car-01', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(scene).toHaveAttribute('data-rendered-frames', /\d+/, { timeout: 60000 });
  expect(errors).toEqual([]);
});

test('unavailable WebGL keeps race controls usable and offers recovery', async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement, kind: string, ...args: unknown[]
    ) {
      if (kind.startsWith('webgl')) {
        return null;
      }
      return Reflect.apply(getContext, this, [kind, ...args]);
    } as typeof getContext;
  });
  await page.goto('/race');
  await expect(page.getByLabel('Live circuit').getByRole('alert'))
    .toContainText('3D rendering is unavailable', { timeout: 60000 });
  await expect(page.getByRole('button', { name: 'Reload 3D view', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^(Start|Pause) race$/ })).toBeEnabled();
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reset race', exact: true })).toBeEnabled();
});

test('graphics quality and race weather drive the live renderer', async ({ page }) => {
  test.slow();
  await page.setViewportSize({ width: 960, height: 720 });
  await page.goto('/race');
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByLabel('Cars', { exact: true }).fill('1');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('combobox', { name: 'Weather', exact: true }).selectOption('rainy');
  await page.getByLabel('Wetness (0 dry, 1 wet)').fill('0.8');
  await page.getByLabel('Ambient (°C)').fill('18');
  await page.getByLabel('Wind (m/s)').fill('7.5');
  await expect(scene).toHaveAttribute('data-weather', 'rainy');
  await expect(scene).toHaveAttribute('data-weather-wetness', '0.80');
  await expect(scene).toHaveAttribute('data-weather-wind', '7.5');
  await expect(scene).toHaveAttribute('data-weather-temperature', '291.15');
  await expect(page.getByLabel('Live circuit')).toHaveAttribute('data-weather', 'HEAVY RAIN');
  const pausedRain = page.locator('[data-paused-rain="true"]');
  await expect(pausedRain).toBeVisible();
  await expect.poll(() => pausedRain.evaluate((element) => getComputedStyle(element).animationPlayState))
    .toBe('running');
  await page.getByRole('combobox', { name: 'Weather', exact: true }).selectOption('sunny');
  await expect(scene).toHaveAttribute('data-weather', 'sunny');
  await expect(pausedRain).toHaveCount(0);
  await expect(page.getByLabel('Live circuit')).toHaveAttribute('data-weather', 'WET TRACK');
  await expect(page.getByLabel('Graphics quality').locator('option')).toHaveText([
    'Ultra graphics', 'High graphics', 'Performance',
  ]);
  await page.getByLabel('Graphics quality').selectOption('ultra');
  await expect(scene).toHaveAttribute('data-render-path', 'postprocessed');
  await page.getByLabel('Graphics quality').selectOption('high');
  await expect(scene).toHaveAttribute('data-graphics-quality', 'high');
  await page.getByLabel('Graphics quality').selectOption('performance');
  await expect(scene).toHaveAttribute('data-graphics-quality', 'performance');
});

test('camera dragging keeps scenery details visible', async ({ page }) => {
  await page.goto('/race');
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await expect(scene).toHaveAttribute('data-rendered-frames', /\d+/, { timeout: 60000 });
  await page.getByLabel('Graphics quality').selectOption('high');
  await expect(scene).toHaveAttribute('data-scenery-details', 'visible');
  const bounds = await scene.boundingBox();
  if (!bounds) {
    throw new Error('3D scene has no visible bounds');
  }
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 40, bounds.y + bounds.height / 2 + 20,
    { steps: 4 });
  await expect(scene).toHaveAttribute('data-render-path', 'direct');
  await expect(scene).toHaveAttribute('data-scenery-details', 'visible');
  await page.mouse.up();
});


test('settings dock, float, drag, resize and keep camera above ground', async ({ page }) => {
  await page.goto('/race');
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByLabel('Cars', { exact: true }).fill('1');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await expect(scene).toHaveAttribute('data-rendered-frames', /\d+/, { timeout: 60000 });
  const full = await scene.boundingBox();
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  const panel = page.locator('[data-docked]');
  await expect(panel).toHaveAttribute('data-docked', 'true');
  await expect.poll(async () => (await scene.boundingBox())?.width).toBe((full?.width ?? 0) - 360);
  await page.getByRole('button', { name: 'Float', exact: true }).click();
  await expect.poll(async () => (await scene.boundingBox())?.width).toBe(full?.width);
  const handle = page.getByRole('button', { name: 'Move race controls' });
  const before = await panel.boundingBox();
  await handle.focus();
  await page.keyboard.press('Shift+ArrowLeft');
  await expect.poll(async () => (await panel.boundingBox())?.x).toBe((before?.x ?? 0) - 40);
  const grip = await handle.boundingBox();
  if (!grip) {
    throw new Error('Missing drag handle');
  }
  await page.mouse.move(grip.x + 20, grip.y + 10);
  await page.mouse.down();
  await page.mouse.move(grip.x - 100, grip.y + 60, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await panel.boundingBox())?.x).toBeLessThan((before?.x ?? 0) - 80);
  await page.getByRole('button', { name: 'Dock', exact: true }).click();
  const dock = await panel.boundingBox();
  if (!dock) {
    throw new Error('Missing docked panel');
  }
  await page.mouse.move(dock.x + 1, dock.y + dock.height / 2);
  await page.mouse.down();
  await page.mouse.move(dock.x - 70, dock.y + dock.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await panel.boundingBox())?.width).toBeGreaterThan(400);
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await page.getByRole('button', { name: 'Car orbit', exact: true }).click();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).evaluate((button) => {
    for (let i = 0; i < 35; i++) {
      (button as HTMLElement).click();
    }
  });
  await expect.poll(async () => Number((await scene.getAttribute('data-camera-position'))?.split(',')[1]))
    .toBeGreaterThanOrEqual(0.65);
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBe(true);
});

test('electrical boost drains the battery and freezes its observed timer when paused', async ({ page }) => {
  test.slow();
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('las-vegas');
  await page.getByLabel('Cars', { exact: true }).fill('3');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  const selectionResponse = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/race/selection/car-01'
  ));
  await page.getByRole('button', { name: 'car-01', exact: true }).click();
  await selectionResponse;
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  const hud = page.getByLabel('Battery and boost', { exact: true });
  await expect(hud).toHaveAttribute('data-energy-mode', /^(UNAVAILABLE|IDLE)$/);
  const boost = page.getByRole('button', { name: 'Apply boost to car-01', exact: true });
  await expect(boost).toBeDisabled();
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  expect(await applyAvailableBoost(page, boost)).toMatchObject({
    car_id: 'car-01', status: 'accepted',
  });
  await expect(boost).toHaveAttribute('data-active', 'true');
  await expect(hud).toHaveAttribute('data-energy-mode', 'BOOST');
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await expect(scene).toHaveAttribute('data-boosting-cars', 'car-01');
  const charge = hud.locator('progress');
  const initial = Number(await charge.getAttribute('value'));
  await expect.poll(async () => {
    if (await boost.isEnabled()) {
      await boost.click();
    }
    return initial - Number(await charge.getAttribute('value'));
  }, { timeout: 60000 }).toBeGreaterThan(0.5);
  await expect.poll(async () => {
    const duration = (await hud.textContent())?.match(/(?:Burst|Last burst) ([0-9.]+) s/)?.[1];
    return Number(duration ?? 0);
  }).toBeGreaterThan(0);
  await page.screenshot({ path: test.info().outputPath('battery-boost.png'), fullPage: true });
  await page.getByRole('button', { name: 'Pause race', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start race', exact: true })).toBeVisible();

  const frozen = await hud.textContent() ?? '';
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await expect(page.getByLabel('Lap energy telemetry')).toContainText('Total boost');
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await expect(hud).toHaveText(frozen);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(hud).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('trackside branding paints the run-off strips and rebuilds on a circuit change', async ({ page }) => {
  test.slow();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/race');
  const scene = page.getByRole('application', { name: '3D camera controls' });
  const decals = async () => Number(await scene.getAttribute('data-branding-decals'));
  await expect(page.getByRole('button', { name: 'Chase', exact: true })).toBeEnabled({ timeout: 60000 });
  await expect.poll(decals, { timeout: 60000 }).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('monaco');
  await page.getByLabel('Cars', { exact: true }).fill('1');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await expect(page.getByLabel('Live circuit')).toContainText('MONACO');
  await expect.poll(decals, { timeout: 60000 }).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await page.getByRole('button', { name: 'Full circuit', exact: true }).click();
  await page.screenshot({ path: test.info().outputPath('trackside-branding.png') });
  expect(errors).toEqual([]);
});
