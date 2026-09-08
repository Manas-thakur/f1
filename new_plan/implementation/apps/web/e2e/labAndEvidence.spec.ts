import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { SESSION_ID, mockFeatureApi } from './featureMockApi';
import { measureOverflow } from './overflow';

const LAB = `/sessions/${SESSION_ID}/lab`;
const REPLAY = `/sessions/${SESSION_ID}/replay`;
const REPORT = '/experiments/exp-0001/report';

test.describe('the laboratory', () => {
  test('creates a snapshot and shows the hash the server returned', async ({ page }) => {
    const log = await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(LAB);

    await page.getByRole('button', { name: 'Create snapshot' }).click();
    await expect(page.getByText('sha256:e2e-snapshot')).toBeVisible();
    expect(log.urls.filter((url) => url.includes('/snapshots')).length).toBe(1);
  });

  test('queues one paired experiment from that snapshot', async ({ page }) => {
    const log = await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(LAB);

    await page.getByRole('button', { name: 'Create snapshot' }).click();
    await expect(page.getByText('sha256:e2e-snapshot')).toBeVisible();

    const queue = page.getByRole('button', { name: 'Queue paired experiment' });
    await expect(queue).toBeEnabled();
    await queue.click();

    await expect(page.getByTestId('experiment-queued')).toContainText('Queued is not finished');
    expect(
      log.urls.filter((url) => url.startsWith('POST') && url.endsWith('/experiments')).length,
    ).toBe(1);
  });

  test('sends a run command with a lease-bearing operator id and no driver action', async ({
    page,
  }) => {
    const log = await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(LAB);

    await page.getByRole('button', { name: 'Start' }).click();
    await expect.poll(() => log.urls.filter((url) => url.includes('/commands')).length).toBe(1);
    expect(log.urls.filter((url) => url.includes('/simulator/driver-action'))).toEqual([]);
  });

  test('keeps the synthetic label and the unmeasured branch outcomes visible', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(LAB);

    await expect(page.getByTestId('lab-synthetic-label')).toBeVisible();
    await expect(page.getByTestId('branch-outcome-unavailable')).toContainText(
      'unmeasured here, not zero',
    );
    await expect(page.getByRole('region', { name: 'Branch outcomes' })).toContainText('unmeasured');
  });

  test('stacks its work areas at mobile width without overflowing', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto(LAB);
    await page.getByRole('heading', { level: 1 }).waitFor();

    const overflow = await measureOverflow(page);
    expect(overflow.offenders).toEqual([]);
  });
});

test.describe('replay', () => {
  test('drives every panel from the one shared cursor', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.goto(REPLAY);

    const sliders = page.getByRole('slider');
    await expect.poll(async () => sliders.count()).toBeGreaterThan(1);

    await sliders.first().focus();
    await page.keyboard.press('ArrowRight');

    const values = await sliders.evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLInputElement).value),
    );
    expect(new Set(values).size).toBe(1);
  });

  test('states the alignment and refuses to fake a seek', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto(REPLAY);

    await expect(page.getByTestId('seek-unavailable')).toContainText('there is no seek command');
    await expect(page.getByRole('button', { name: /Restore/ })).toBeDisabled();
    await expect(page.getByText(/common progress \(metres travelled\)/).first()).toBeVisible();
  });
});

test.describe('the experiment report', () => {
  test('renders the four learned rows as unavailable, with no win rate', async ({ page }) => {
    await mockFeatureApi(page, { serveReport: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(REPORT);

    const matrix = page.getByRole('region', { name: 'Comparison matrix rows' });
    await expect(matrix).toBeVisible();
    await expect(matrix.getByText('unavailable')).toHaveCount(4);
    await expect(matrix).toContainText('needs a trained actor');
    await expect(matrix).toContainText('needs a promoted model bundle');

    await expect(page.getByTestId('no-win-rate')).toContainText('No win rate');
    const text = (await page.locator('body').innerText()).toLowerCase();
    expect(text).not.toMatch(/win rate:\s*\d/);
  });

  test('is accessible and fits its widths with the report body served', async ({ page }) => {
    await mockFeatureApi(page, { serveReport: true });
    for (const width of [320, 768, 1440] as const) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(REPORT);
      await page.getByRole('heading', { level: 1 }).waitFor();
      const overflow = await measureOverflow(page);
      expect(overflow.offenders, `offenders at ${width}px`).toEqual([]);
    }

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
      .analyze();
    const blocking = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );
    expect(blocking.map((violation) => violation.id)).toEqual([]);
  });

  test('names the missing route when no report body is served', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto(REPORT);
    await expect(page.getByText(/missing artefact: benchmark report body/)).toBeVisible();
    await expect(page.getByText(/no route serves the report JSON/)).toBeVisible();
  });
});

test.describe('rules and models', () => {
  test('the ruleset names its unsupported conditions and its review state', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto('/rulesets/synthetic-pack-v1');

    await expect(page.getByTestId('unsupported-conditions')).toContainText(
      'overtake_gap_threshold_s',
    );
    await expect(page.getByText('not reviewed').first()).toBeVisible();
    await expect(page.getByRole('region', { name: 'Rule coverage' })).toContainText('unsupported');
  });

  test('the models route offers no promotion control', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto('/models');

    await expect(page.getByTestId('no-promotion')).toContainText('no automatic promotion exists');
    await expect(page.getByRole('button', { name: /promote/i })).toHaveCount(0);
    await expect(page.getByText('0 approved')).toBeVisible();
  });
});
