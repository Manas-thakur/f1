import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { SESSION_ID, MANIFEST, mockFeatureApi, recommendation, snapshot } from './featureMockApi';
import { measureOverflow } from './overflow';

const ROUTE = `/sessions/${SESSION_ID}/driver`;

const COMMUNICATED = { recommendation: recommendation({ status: 'communicated' }) };

const LONG_CHECKPOINT = {
  recommendation: recommendation({
    status: 'communicated',
    end_condition:
      'Kontrollpunkt am Ausgang der Schikane nach der Aktivierungslinie, Rückgewinnungsabschnitt',
    display_text: 'Angriff in Kurve 7, halten bis zum Ausgangskontrollpunkt',
  }),
};

test.describe('the driver screen at both ends of the size range', () => {
  for (const viewport of [
    { width: 1920, height: 1080, name: 'large' },
    { width: 360, height: 640, name: 'small' },
  ] as const) {
    test(`renders one large instruction at ${viewport.name} size`, async ({ page }) => {
      await mockFeatureApi(page, { snapshotOverrides: COMMUNICATED });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(ROUTE);

      const primary = page.getByTestId('driver-primary');
      await expect(primary).toContainText('Attack into T7');

      const fontSize = await primary.evaluate(
        (node) => Number.parseFloat(window.getComputedStyle(node).fontSize),
      );
      expect(fontSize, 'the instruction is not large type').toBeGreaterThanOrEqual(26);

      const box = await primary.boundingBox();
      expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport.height);

      const overflow = await measureOverflow(page);
      expect(overflow.offenders).toEqual([]);
      expect(overflow.bodyScrollWidth).toBeLessThanOrEqual(overflow.innerWidth);
    });
  }

  test('keeps a long translated checkpoint name inside the layout', async ({ page }) => {
    await mockFeatureApi(page, { snapshotOverrides: LONG_CHECKPOINT });
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto(ROUTE);

    await expect(page.getByText(/Kontrollpunkt am Ausgang/)).toBeVisible();
    const overflow = await measureOverflow(page);
    expect(overflow.offenders).toEqual([]);
  });
});

test.describe('the simulator input', () => {
  test('is reachable and operable with the keyboard alone', async ({ page }) => {
    const log = await mockFeatureApi(page, { snapshotOverrides: COMMUNICATED });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(ROUTE);

    await expect(page.getByRole('button', { name: 'overtake' })).toBeEnabled();

    let reached = false;
    for (let index = 0; index < 40 && !reached; index += 1) {
      await page.keyboard.press('Tab');
      const label = await page.evaluate(() =>
        (document.activeElement?.textContent ?? '').trim(),
      );
      if (label === 'overtake') {
        reached = true;
      }
    }
    expect(reached, 'the overtake profile was not reachable by Tab').toBe(true);

    const outline = await page.evaluate(
      () => window.getComputedStyle(document.activeElement as Element).outlineWidth,
    );
    expect(outline).not.toBe('0px');

    await page.keyboard.press('Enter');
    await expect
      .poll(() => log.urls.filter((url) => url.includes('/simulator/driver-action')).length)
      .toBe(1);
    await expect(page.getByTestId('driver-execution')).toContainText('overtake · matched');
  });

  test('is refused for a session that is not a simulation', async ({ page }) => {
    const log = await mockFeatureApi(page, {
      snapshotOverrides: { manifest: { ...MANIFEST, mode: 'live_team' } },
    });
    await page.goto(ROUTE);

    await expect(page.getByTestId('driver-primary')).toContainText('NOT A SIMULATOR SESSION');
    const buttons = page.getByRole('button');
    const count = await buttons.count();
    for (let index = 0; index < count; index += 1) {
      await expect(buttons.nth(index)).toBeDisabled();
    }
    expect(log.urls.filter((url) => url.includes('/simulator/driver-action'))).toEqual([]);
  });
});

test.describe('what the driver screen refuses to show', () => {
  test('shows nothing for a proposal the engineer has not acted on', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto(ROUTE);
    await expect(page.getByTestId('driver-primary')).toContainText('NO INSTRUCTION');
    await expect(page.getByText('Attack into T7, hold through attack-exit')).toHaveCount(0);
  });

  test('carries no probability, no chat and no telemetry table', async ({ page }) => {
    await mockFeatureApi(page, { snapshotOverrides: COMMUNICATED });
    await page.goto(ROUTE);
    await expect(page.getByTestId('driver-primary')).toContainText('Attack into T7');

    const text = (await page.locator('body').innerText()).toLowerCase();
    expect(text).not.toContain('probability');
    expect(text).not.toContain('confidence');
    expect(text).not.toContain('likelihood');
    await expect(page.getByRole('table')).toHaveCount(0);
    await expect(page.getByRole('slider')).toHaveCount(0);
  });
});

test.describe('contrast', () => {
  test('the dark scope has no serious or critical contrast violation', async ({ page }) => {
    await mockFeatureApi(page, { snapshotOverrides: COMMUNICATED });
    await page.goto(ROUTE);
    await expect(page.getByTestId('driver-scope')).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .include('[data-testid="driver-scope"]')
      .analyze();

    const blocking = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );
    expect(
      blocking.map((violation) => ({ id: violation.id, nodes: violation.nodes.length })),
    ).toEqual([]);

    const contrast = results.violations.filter((violation) => violation.id === 'color-contrast');
    expect(contrast).toEqual([]);
  });

  test('the safety state is carried by text and shape, not only colour', async ({ page }) => {
    await mockFeatureApi(page, {
      frames: [],
      snapshotOverrides: {
        ...COMMUNICATED,
        estimate: {
          ...snapshot().estimate,
          race_context: { ...snapshot().estimate.race_context, flag_state: 'red', flag_known: true },
        },
      },
    });
    await page.goto(ROUTE);
    await expect(page.getByTestId('driver-primary')).toContainText('RED');
    await expect(page.getByLabel('Primary instruction')).toContainText('safety');
  });
});
