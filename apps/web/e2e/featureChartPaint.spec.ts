import { expect, test } from '@playwright/test';

import { isNumericLabel, looksLikeTime, numericValue, paintedText, recordCanvasText } from './canvasPaint';
import { SESSION_ID, mockFeatureApi } from './featureMockApi';


const ENGINEER = `/sessions/${SESSION_ID}/engineer`;

test.describe('the engineer console panels paint readable axes', () => {
  test('distance is a number on the x axis, never a wall-clock time', async ({ page }) => {
    await recordCanvasText(page);
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.goto(ENGINEER);
    await page.getByRole('heading', { name: 'Energy over distance' }).waitFor();
    await page.waitForTimeout(500);

    const painted = await paintedText(page);
    expect(painted.length, 'nothing was painted; the canvas never rendered').toBeGreaterThan(0);

    const timeLike = painted.filter((entry) => looksLikeTime(entry.text));
    expect(
      timeLike.map((entry) => entry.text),
      'a physical x coordinate was formatted as a clock time',
    ).toEqual([]);
  });

  test('energy ticks are in display units, not raw joules', async ({ page }) => {
    await recordCanvasText(page);
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.goto(ENGINEER);
    await page.getByRole('heading', { name: 'Energy over distance' }).waitFor();
    await page.waitForTimeout(500);

    const painted = await paintedText(page);
    const numeric = painted
      .filter((entry) => isNumericLabel(entry.text))
      .map((entry) => numericValue(entry.text));
    expect(numeric.length).toBeGreaterThan(0);


    const rawSiLooking = numeric.filter((value) => Math.abs(value) >= 100_000);
    expect(rawSiLooking, 'y ticks look like raw SI rather than display units').toEqual([]);
  });

  test('no tick is painted outside its canvas', async ({ page }) => {
    await recordCanvasText(page);
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.goto(ENGINEER);
    await page.getByRole('heading', { name: 'Energy over distance' }).waitFor();
    await page.waitForTimeout(500);

    const painted = await paintedText(page);
    const clipSlack = 32;
    const clipped = painted.filter(
      (entry) =>
        !entry.rotated && (entry.left < -clipSlack || entry.right > entry.canvasWidth + clipSlack),
    );
    expect(
      clipped.map((entry) => ({
        text: entry.text,
        left: Math.round(entry.left),
        right: Math.round(entry.right),
        canvasWidth: entry.canvasWidth,
      })),
      'a label was painted outside the canvas; reserve axis size from the widest tick',
    ).toEqual([]);
  });

  test('the axis caption names the unit the ticks are drawn in', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.goto(ENGINEER);

    const figure = page.locator('figure', { hasText: 'Energy over distance' }).first();
    await expect(figure).toContainText('MJ');
    await expect(figure).toContainText('distance');

    await expect(figure).toContainText('stored energy (MJ, simulated)');
    await expect(figure).toContainText('projected at checkpoints (MJ, estimated, reference, dashed)');
    await expect(figure).toContainText('energy floor (rule limit) (MJ, configured)');
  });
});
