import { expect, test } from '@playwright/test';
import * as THREE from 'three';

import { markerPosition, overviewLayout, overviewViewport } from '../src/features/race/overview';

test('overview fits wide and tall circuits into the unobscured viewport', () => {
  for (const [width, height] of [[1440, 900], [700, 900], [390, 844], [900, 450]] as const) {
    for (const [x, z] of [[400, 2800], [3000, 600]] as const) {
      const map = { id: 'fit', name: 'Fit', length_m: 5000,
        points: [[0, 0], [x, 0], [x, z], [0, z]] as [number, number][] };
      const w = width;
      const h = height;
      const fit = overviewLayout(map, w, h, 140);
      const camera = new THREE.PerspectiveCamera(58, w / h, 0.12, 100000);
      camera.position.set(x / 2, fit.distance, z / 2 + fit.distance * 0.0001);
      camera.lookAt(x / 2, 0, z / 2);
      camera.setViewOffset(w, h, fit.offsetX, fit.offsetY, w, h);
      camera.updateMatrixWorld();
      for (const [px, pz] of map.points) {
        const projected = new THREE.Vector3(px, 0, pz).project(camera);
        const screenX = (projected.x + 1) * w / 2;
        const screenY = (1 - projected.y) * h / 2;
        expect(screenX).toBeGreaterThan(w > 700 ? 220 : 24);
        expect(screenX).toBeLessThan(w - 24);
        expect(screenY).toBeGreaterThan(Math.min(h * 0.45, 140 + (w > 700 ? 55 : 100)));
        expect(screenY).toBeLessThan(h - 65);
      }
    }
  }
});

test('right menu, complete overview, driver selection and variability survive reset', async ({ page }) => {
  test.slow();
  await page.goto('/race');
  const menu = page.getByRole('button', { name: 'Race controls', exact: true });
  const fullscreen = page.getByRole('button', { name: 'Fullscreen', exact: true });
  await expect.poll(async () => (await menu.boundingBox())?.x ?? 0)
    .toBeGreaterThan((await fullscreen.boundingBox())?.x ?? Infinity);
  await menu.click();
  await page.getByLabel('Cars', { exact: true }).fill('3');
  await page.getByLabel('Seed', { exact: true }).fill('101');
  await expect(page.getByLabel('Reuse seed for replay')).toBeChecked();
  await page.getByText('Advanced variability', { exact: true }).click();
  await page.getByLabel('Vehicle variation', { exact: true }).fill('0.37');
  await page.getByLabel('Target wetness', { exact: true }).fill('0.63');
  await page.getByLabel('Weather response (s)').fill('120.5');
  await page.getByLabel('Driver trait overrides (JSON)').fill('{"car-01":{"pace":0.9}}');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await expect(page.locator('[aria-label="Classification"] button')).toHaveCount(3);
  await page.getByText('Advanced variability', { exact: true }).click();
  await expect(page.getByLabel('Vehicle variation', { exact: true })).toHaveValue('0.37');
  await expect(page.getByLabel('Target wetness', { exact: true })).toHaveValue('0.63');
  await expect(page.getByLabel('Weather response (s)')).toHaveValue('120.5');
  await expect(page.getByLabel('Driver trait overrides (JSON)')).toHaveValue(/0.9/);
  const names = await page.locator('[aria-label="Classification"] button').allTextContents();
  expect(names.join(' ')).not.toMatch(/CAR-0/i);
  await page.getByLabel('Reuse seed for replay').uncheck();
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await expect(page.getByLabel('Seed', { exact: true })).not.toHaveValue('101');
  await page.getByRole('button', { name: 'Start race', exact: true }).click();
  const scene = page.getByRole('application', { name: '3D camera controls' });
  await expect(scene).toHaveAttribute('data-followed-position', /\d/);
  await page.getByRole('button', { name: 'Pause race', exact: true }).click();
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await page.getByRole('button', { name: 'Full circuit', exact: true }).click();
  const markers = page.getByRole('group', { name: 'Circuit driver markers' });
  await expect(markers.getByRole('button')).toHaveCount(3);
  await expect(markers.getByRole('button').last()).toBeVisible();
  const id = await markers.getByRole('button').last().getAttribute('data-car-id');
  await markers.getByRole('button').last().click();
  await expect(page.locator(`[aria-label="Classification"] [data-car-id="${id}"]`)).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await page.getByRole('button', { name: 'Fit circuit', exact: true }).click();
  await expect(scene).toHaveAttribute('data-camera-mode', 'track');
  await page.screenshot({ path: test.info().outputPath('full-circuit.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(markers.getByRole('button').last()).toBeVisible();
  await page.getByRole('button', { name: 'First person', exact: true }).click();
  await expect(markers).toBeHidden();
  await expect.poll(async () => Number((await scene.getAttribute('data-camera-position'))?.split(',')[1])).toBeCloseTo(0.86, 2);
});


test('twenty clustered overview labels stay clear of controls and each other', () => {
  for (const [width, height] of [[1440, 900], [900, 450], [390, 844]] as const) {
    const bounds = overviewViewport(width, height, 130);
    for (const [px, py] of [[bounds.left + 10, bounds.top + 20],
      [width - bounds.right - 10, height - bounds.bottom - 20]]) {
      const occupied: { x: number; y: number }[] = [];
      for (let i = 0; i < 20; i++) {
        const point = markerPosition(px ?? 0, py ?? 0, occupied, width, height, 130);
        expect(point.x).toBeGreaterThanOrEqual(bounds.left + 16);
        expect(point.x).toBeLessThanOrEqual(width - bounds.right - 16);
        expect(point.y).toBeGreaterThanOrEqual(bounds.top + 16);
        expect(point.y).toBeLessThanOrEqual(height - bounds.bottom - 16);
        for (const other of occupied) {
          expect(Math.hypot(point.x - other.x, point.y - other.y)).toBeGreaterThanOrEqual(34);
        }
        occupied.push(point);
      }
    }
  }
});
