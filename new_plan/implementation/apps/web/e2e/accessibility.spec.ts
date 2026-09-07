import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { mockApi, mockEmptyApi } from './mockApi';

const ROUTES = ['/', '/simulation-lab', '/sessions', '/settings'] as const;

test.describe('axe-core reports no serious or critical violations', () => {
  for (const route of ROUTES) {
    test(`on ${route}`, async ({ page }) => {
      await mockApi(page);
      await page.goto(route);
      await page.getByRole('heading', { level: 1 }).waitFor();

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
        .analyze();

      const blocking = results.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      );

      expect(
        blocking.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes.map((n) => n.target.join(' ')).slice(0, 3),
        })),
      ).toEqual([]);
    });
  }
});

test.describe('document structure', () => {
  for (const route of ROUTES) {
    test(`${route} has exactly one h1 and the expected landmarks`, async ({ page }) => {
      await mockApi(page);
      await page.goto(route);
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
      await expect(page.getByRole('main')).toHaveCount(1);
      await expect(page.getByRole('banner')).toHaveCount(1);
      await expect(page.getByRole('contentinfo')).toHaveCount(1);
    });
  }
});

test.describe('the synthetic-data notice', () => {
  for (const route of ROUTES) {
    test(`is visible on ${route}`, async ({ page }) => {
      await mockApi(page);
      await page.goto(route);
      const notice = page.getByTestId('synthetic-data-notice');
      await expect(notice).toBeVisible();
      await expect(notice).toContainText('simulated');
    });
  }
});

test.describe('keyboard-only navigation', () => {
  test('reaches every interactive control in the workspace shell', async ({ page }) => {
    await mockApi(page);
    await page.goto('/sessions');
    await page.getByRole('heading', { level: 1 }).waitFor();

    const interactive = await page.evaluate(() => {
      const selector =
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
      return Array.from(document.querySelectorAll(selector))
        .filter((el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 0;
        })
        .map((el, index) => {
          el.setAttribute('data-e2e-focusable', String(index));
          return String(index);
        });
    });

    expect(interactive.length).toBeGreaterThan(5);

    const reached = new Set<string>();
    // One tab per control plus a margin for the browser's own chrome stops.
    for (let i = 0; i < interactive.length + 6; i += 1) {
      await page.keyboard.press('Tab');
      const marker = await page.evaluate(() =>
        document.activeElement?.getAttribute('data-e2e-focusable'),
      );
      if (marker !== null && marker !== undefined) {
        reached.add(marker);
      }
    }

    const missed = interactive.filter((id) => !reached.has(id));
    const missedDescriptions = await page.evaluate(
      (ids) =>
        ids.map((id) => {
          const el = document.querySelector(`[data-e2e-focusable="${id}"]`);
          return el === null ? id : `${el.tagName.toLowerCase()}: ${el.textContent?.trim() ?? ''}`;
        }),
      missed,
    );

    expect(missedDescriptions, 'these controls were never focused by Tab alone').toEqual([]);
  });

  test('the skip link is the first tab stop and moves focus into main', async ({ page }) => {
    await mockApi(page);
    await page.goto('/sessions');
    await page.keyboard.press('Tab');

    const skip = page.getByRole('link', { name: 'Skip to main content' });
    await expect(skip).toBeFocused();

    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#main-content$/);
  });

  test('every focused control has a visible focus indicator', async ({ page }) => {
    await mockApi(page);
    await page.goto('/settings');
    await page.getByRole('heading', { level: 1 }).waitFor();

    await page.keyboard.press('Tab');
    for (let i = 0; i < 12; i += 1) {
      const hasRing = await page.evaluate(() => {
        const el = document.activeElement;
        if (el === null || el === document.body) {
          return true;
        }
        const style = window.getComputedStyle(el);
        return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
      });
      expect(hasRing).toBe(true);
      await page.keyboard.press('Tab');
    }
  });
});

test.describe('the inspector dialog', () => {
  test('opens, traps focus, closes on Escape and restores focus', async ({ page }) => {
    await mockApi(page);
    await page.goto('/settings');

    const invoker = page.getByRole('button', { name: 'Open a sample inspector' });
    await invoker.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('heading', { name: 'Sample inspector' })).toBeVisible();

    for (let i = 0; i < 5; i += 1) {
      await page.keyboard.press('Tab');
      const inside = await page.evaluate(() => {
        const dialogEl = document.querySelector('[role="dialog"]');
        return dialogEl !== null && dialogEl.contains(document.activeElement);
      });
      expect(inside).toBe(true);
    }

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(invoker).toBeFocused();
  });
});

test.describe('charts', () => {
  test('expose a keyboard cursor and a numeric summary', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');

    const slider = page.getByRole('slider', { name: /Shared cursor position/ }).first();
    await expect(slider).toBeVisible();
    await slider.focus();
    const before = await slider.inputValue();
    await page.keyboard.press('ArrowRight');
    await expect
      .poll(async () => await slider.inputValue())
      .not.toBe(before);

    await page.getByText('Numeric summary and sampling detail').first().click();
    await expect(page.getByRole('columnheader', { name: 'Minimum' }).first()).toBeVisible();
  });
});

test.describe('the sessions empty state', () => {
  test('names the missing artefact instead of showing an empty grid', async ({ page }) => {
    await mockEmptyApi(page);
    await page.goto('/sessions');
    await expect(page.getByText('missing artefact: session manifest')).toBeVisible();
    await expect(page.getByRole('link', { name: 'The simulation lab page' })).toBeVisible();
  });
});
