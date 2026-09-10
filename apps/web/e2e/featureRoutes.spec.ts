import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { SESSION_ID, mockFeatureApi } from './featureMockApi';
import { measureOverflow } from './overflow';

const WIDTHS = [320, 375, 414, 768, 1024, 1440, 1920] as const;

const ROUTES = [
  '/lab',
  `/sessions/${SESSION_ID}/engineer`,
  `/sessions/${SESSION_ID}/lab`,
  `/sessions/${SESSION_ID}/replay`,
  `/sessions/${SESSION_ID}/driver`,
  '/experiments/exp-0001/report',
  '/rulesets/synthetic-pack-v1',
  '/models',
] as const;

test.describe('every feature route fits every supported width', () => {
  for (const width of WIDTHS) {
    for (const route of ROUTES) {
      test(`${route} at ${width}px has no horizontal overflow`, async ({ page }) => {
        await mockFeatureApi(page);
        await page.setViewportSize({ width, height: 900 });
        await page.goto(route);
        await page.getByRole('heading', { level: 1 }).waitFor();

        await page.waitForTimeout(250);

        const result = await measureOverflow(page);

        expect(
          result.bodyScrollWidth,
          `body.scrollWidth ${result.bodyScrollWidth} exceeds innerWidth ${result.innerWidth}`,
        ).toBeLessThanOrEqual(result.innerWidth);
        expect(
          result.offenders,
          `elements extend past the viewport: ${JSON.stringify(result.offenders)}`,
        ).toEqual([]);
      });
    }
  }
});

test.describe('axe-core reports no serious or critical violations', () => {
  for (const route of ROUTES) {
    test(`on ${route}`, async ({ page }) => {
      await mockFeatureApi(page);
      await page.goto(route);
      await page.getByRole('heading', { level: 1 }).waitFor();
      await page.waitForTimeout(250);

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
        .analyze();

      const blocking = results.violations.filter(
        (violation) => violation.impact === 'serious' || violation.impact === 'critical',
      );

      expect(
        blocking.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          nodes: violation.nodes.map((node) => node.target.join(' ')).slice(0, 3),
        })),
      ).toEqual([]);
    });
  }
});

test.describe('document structure', () => {
  for (const route of ROUTES) {
    test(`${route} has exactly one h1 and the workspace landmarks`, async ({ page }) => {
      await mockFeatureApi(page);
      await page.goto(route);
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
      await expect(page.getByRole('main')).toHaveCount(1);
      await expect(page.getByRole('banner')).toHaveCount(1);
      await expect(page.getByRole('contentinfo')).toHaveCount(1);
    });
  }
});
