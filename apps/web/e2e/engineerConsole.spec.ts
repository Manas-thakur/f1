import { expect, test } from '@playwright/test';

import {
  LAST_SEQUENCE,
  SESSION_ID,
  mockFeatureApi,
  recommendation,
  resyncFrame,
  telemetryFrame,
} from './featureMockApi';
import { measureOverflow } from './overflow';

const ROUTE = `/sessions/${SESSION_ID}/engineer`;

test.describe('selecting a recommendation records a decision and actuates nothing', () => {
  test('issues one recommendation action and no driver action', async ({ page }) => {
    const log = await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);

    const select = page.getByRole('button', { name: 'Select', exact: true });
    await expect(select).toBeEnabled();
    await select.click();

    await expect
      .poll(() => log.urls.filter((url) => url.includes('/recommendations/')).length)
      .toBe(1);


    expect(log.urls.filter((url) => url.includes('/simulator/driver-action'))).toEqual([]);
    expect(log.urls.filter((url) => url.includes('/commands'))).toEqual([]);
  });

  test('reports an expiry rejection and does not retry', async ({ page }) => {
    const log = await mockFeatureApi(page, {
      actionError: {
        code: 'recommendation_expired',
        message: 'this recommendation expired before it was acted on',
        status: 422,
      },
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);

    const select = page.getByRole('button', { name: 'Select', exact: true });
    await expect(select).toBeEnabled();
    await select.click();

    const outcome = page.getByTestId('action-outcome');
    await expect(outcome).toContainText('expired');
    await expect(outcome).toContainText('A newer one may be available');

    await page.waitForTimeout(500);
    expect(log.urls.filter((url) => url.includes('/recommendations/')).length).toBe(1);
  });

  test('offers no selectable action once the recommendation has passed its expiry', async ({
    page,
  }) => {
    await mockFeatureApi(page, {


      frames: [],
      snapshotOverrides: { session_time_s: 25.0, recommendation: recommendation() },
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);

    await expect(page.getByTestId('console-state')).toContainText(
      'Recommendation no longer actionable',
    );
    await expect(page.getByRole('button', { name: 'Select', exact: true })).toBeDisabled();
  });
});

test.describe('the stream', () => {
  test('resynchronises from a REST snapshot when the server asks for one', async ({ page }) => {
    const log = await mockFeatureApi(page, {
      frames: [telemetryFrame(LAST_SEQUENCE + 1), resyncFrame(LAST_SEQUENCE + 2)],
    });
    await page.goto(ROUTE);


    await expect
      .poll(() => log.urls.filter((url) => url.includes('/snapshot')).length, { timeout: 10_000 })
      .toBeGreaterThan(1);
  });

  test('shows provenance and data age from the stream, not from a heartbeat', async ({ page }) => {
    await mockFeatureApi(page);
    await page.goto(ROUTE);

    const sources = page.locator('#sources');
    await expect(sources).toContainText('Data age');
    await expect(sources).toContainText('session time');
    await expect(sources).toContainText('synthetic');

    await expect(page.getByText('simulated').first()).toBeVisible();
    await expect(page.getByText('estimated').first()).toBeVisible();

    await expect(page.getByLabel('Session context')).toContainText('Data age');
  });
});

test.describe('the shared chart cursor', () => {
  test('moves every panel, and is keyboard operable', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 1200 });
    await page.goto(ROUTE);

    const sliders = page.getByRole('slider');
    await expect.poll(async () => sliders.count()).toBeGreaterThan(2);

    const first = sliders.first();
    await first.focus();
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');

    const values = await sliders.evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLInputElement).value),
    );

    expect(new Set(values).size).toBe(1);
    await expect(first).toHaveAttribute('aria-valuetext', /metres|seconds/);
  });
});

test.describe('keyboard navigation and focus order', () => {
  test('reaches the decision controls by Tab alone, with a visible ring', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);
    await expect(page.getByRole('button', { name: 'Select', exact: true })).toBeEnabled();

    await page.keyboard.press('Tab');
    await expect(page.locator(':focus')).toHaveText('Skip to main content');

    const seen: string[] = [];
    let reachedSelect = false;
    for (let index = 0; index < 60 && !reachedSelect; index += 1) {
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => {
        const element = document.activeElement as HTMLElement | null;
        if (element === null) {return null;}
        const style = window.getComputedStyle(element);
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? '').trim().slice(0, 40),
          outlineWidth: style.outlineWidth,
        };
      });
      if (focused === null) {break;}
      seen.push(`${focused.tag}:${focused.text}`);
      if (focused.text === 'Select') {
        reachedSelect = true;
        expect(focused.outlineWidth, 'the focused control has no focus ring').not.toBe('0px');
      }
    }
    expect(reachedSelect, `never reached Select; tab order was ${seen.join(' > ')}`).toBe(true);
  });

  test('the evidence dialog traps focus, closes on Escape and restores it', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);

    const invoker = page.locator('#engineer-open-evidence');
    await invoker.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    for (let index = 0; index < 6; index += 1) {
      await page.keyboard.press('Tab');
      const inside = await page.evaluate(() => {
        const dialogNode = document.querySelector('[role="dialog"]');
        return dialogNode?.contains(document.activeElement) === true;
      });
      expect(inside, 'focus escaped the modal').toBe(true);
    }

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(invoker).toBeFocused();
  });
});

test.describe('layout', () => {
  test('shows the recommendation without scrolling at desktop width', async ({ page }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ROUTE);

    const instruction = page.getByText('Attack into T7, hold through attack-exit');
    await expect(instruction).toBeVisible();

    const box = await instruction.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.y ?? 0).toBeGreaterThanOrEqual(0);
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(900);


    expect(await page.evaluate(() => window.scrollY)).toBe(0);


    const selectBox = await page.getByRole('button', { name: 'Select', exact: true }).boundingBox();
    expect((selectBox?.y ?? 0) + (selectBox?.height ?? 0)).toBeLessThanOrEqual(900);
  });

  test('is a read-only summary at mobile width, with laboratory controls elsewhere', async ({
    page,
  }) => {
    await mockFeatureApi(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(ROUTE);

    await expect(page.getByTestId('read-only-summary')).toContainText(
      'Operational commands are not offered at this width',
    );
    await expect(page.getByRole('button', { name: 'Select', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Mark communicated' })).toBeDisabled();


    await expect(page.getByRole('button', { name: 'Create snapshot' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Queue paired experiment' })).toHaveCount(0);

    const overflow = await measureOverflow(page);
    expect(overflow.offenders).toEqual([]);
  });
});
