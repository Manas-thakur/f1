import { expect, test } from '@playwright/test';

import {
  isNumericLabel,
  looksLikeTime,
  numericValue,
  paintedText,
  recordCanvasText,
  type PaintedText,
} from './canvasPaint';
import { mockApi } from './mockApi';

/**
 * Regression coverage for what the chart paints.
 *
 * Every assertion here fails on the build that shipped before this file
 * existed: the x axis rendered wall-clock times on 1/1/70, the y axis was
 * clipped to ")00,000", and its raw-SI magnitudes contradicted a legend that
 * claimed kW and MJ.
 */
async function loadSpecimen(page: import('@playwright/test').Page, width = 1500) {
  await recordCanvasText(page);
  await mockApi(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto('/');
  await page.getByRole('heading', { level: 1 }).waitFor();
  // Wait until the plot has actually painted something.
  await expect.poll(async () => (await paintedText(page)).length).toBeGreaterThan(4);
  return paintedText(page);
}

/** Horizontal tick labels sit on one row near the bottom of the canvas. */
function bottomAxisTicks(records: readonly PaintedText[]): PaintedText[] {
  const horizontal = records.filter((r) => !r.rotated && r.align === 'center');
  return horizontal.filter((r) => isNumericLabel(r.text));
}

function sideAxisTicks(records: readonly PaintedText[]): PaintedText[] {
  return records.filter(
    (r) => !r.rotated && (r.align === 'right' || r.align === 'left') && isNumericLabel(r.text),
  );
}

test.describe('the painted x axis is a physical coordinate', () => {
  test('never renders a clock time or an epoch date', async ({ page }) => {
    const records = await loadSpecimen(page);
    const timeLike = records.filter((r) => looksLikeTime(r.text)).map((r) => r.text);
    expect(
      timeLike,
      'uPlot formatted a distance axis as a wall-clock time; set scales.x.time = false',
    ).toEqual([]);
  });

  test('paints numeric metre ticks spanning the lap', async ({ page }) => {
    const records = await loadSpecimen(page);
    const ticks = bottomAxisTicks(records);

    expect(ticks.length, 'no numeric x tick labels were painted').toBeGreaterThan(2);

    const values = ticks.map((t) => numericValue(t.text));
    expect(values.every((v) => Number.isFinite(v))).toBe(true);
    // The specimen lap is 5300 m; a timestamp axis would never produce these.
    expect(Math.max(...values)).toBeGreaterThan(1000);
    expect(Math.min(...values)).toBeGreaterThanOrEqual(0);
  });

  test('paints the x axis unit beside the axis', async ({ page }) => {
    const records = await loadSpecimen(page);
    const labels = records.map((r) => r.text);
    expect(labels).toContain('distance (m)');
  });
});

test.describe('the painted y axes agree with the legend', () => {
  test('label each axis with the display unit shown in the legend', async ({ page }) => {
    const records = await loadSpecimen(page);
    const labels = records.map((r) => r.text);

    // The legend declares kW for deployment and MJ for stored energy.
    await expect(page.getByText(/Own car deployment \(kW/)).toBeVisible();
    await expect(page.getByText(/Own car stored energy \(MJ/)).toBeVisible();

    expect(labels, 'the left axis must be labelled in kW').toContain('kW');
    expect(labels, 'the right axis must be labelled in MJ').toContain('MJ');
  });

  test('never paint raw SI magnitudes against a kW / MJ legend', async ({ page }) => {
    const records = await loadSpecimen(page);
    const ticks = sideAxisTicks(records);

    expect(ticks.length, 'no numeric y tick labels were painted').toBeGreaterThan(2);

    const magnitudes = ticks.map((t) => Math.abs(numericValue(t.text)));
    const worst = Math.max(...magnitudes);
    // Raw watts would put 350000 on this axis; kW tops out near 350 and MJ
    // near 4. Anything in the thousands means the conversion was skipped.
    expect(
      worst,
      `y tick magnitudes ${JSON.stringify(ticks.map((t) => t.text))} look like raw SI, not display units`,
    ).toBeLessThan(1000);
  });

  test('use separate scales, so a kW trace is not flattened by an MJ trace', async ({ page }) => {
    const records = await loadSpecimen(page);
    const left = records.filter((r) => !r.rotated && r.align === 'right' && isNumericLabel(r.text));
    const right = records.filter((r) => !r.rotated && r.align === 'left' && isNumericLabel(r.text));

    expect(left.length, 'no left-hand axis ticks').toBeGreaterThan(1);
    expect(right.length, 'no right-hand axis ticks; the two units share one scale').toBeGreaterThan(
      1,
    );

    const leftMax = Math.max(...left.map((t) => Math.abs(numericValue(t.text))));
    const rightMax = Math.max(...right.map((t) => Math.abs(numericValue(t.text))));
    // kW reaches the hundreds; MJ stays in single digits. Two ranges this far
    // apart on one scale is exactly what made the power trace unreadable.
    expect(leftMax).toBeGreaterThan(50);
    expect(rightMax).toBeLessThan(50);
  });
});

test.describe('no painted axis label is clipped', () => {
  for (const width of [768, 1024, 1500]) {
    test(`every tick label is fully inside the canvas at ${width}px`, async ({ page }) => {
      const records = await loadSpecimen(page, width);
      const clipped = records
        .filter((r) => !r.rotated)
        .filter((r) => r.left < -0.5 || r.right > r.canvasWidth + 0.5)
        .map((r) => ({
          text: r.text,
          left: Math.round(r.left),
          right: Math.round(r.right),
          canvasWidth: r.canvasWidth,
        }));

      expect(
        clipped,
        'a label was painted outside the canvas; reserve axis size from the widest tick',
      ).toEqual([]);
    });
  }

  test('reserves enough width that the leading digit survives', async ({ page }) => {
    const records = await loadSpecimen(page);
    const leftTicks = records.filter(
      (r) => !r.rotated && r.align === 'right' && isNumericLabel(r.text),
    );
    expect(leftTicks.length).toBeGreaterThan(1);
    for (const tick of leftTicks) {
      expect(tick.left, `"${tick.text}" starts left of the canvas edge`).toBeGreaterThanOrEqual(
        -0.5,
      );
    }
  });
});

test.describe('the accessible caption states the same axes', () => {
  test('names the x coordinate and both y units in the DOM', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');
    const caption = page.getByText(/x axis: distance \(m\)/).first();
    await expect(caption).toBeVisible();
    await expect(caption).toContainText('left axis in kW');
    await expect(caption).toContainText('right axis in MJ');
  });
});
