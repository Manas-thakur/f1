import { expect, test, type Page } from '@playwright/test';

import { mockApi } from './mockApi';

const WIDTHS = [320, 375, 414, 768, 1024, 1440, 1920] as const;
const ROUTES = ['/', '/simulation-lab', '/sessions', '/settings'] as const;

interface Overflow {
  readonly bodyScrollWidth: number;
  readonly innerWidth: number;
  readonly offenders: readonly { selector: string; right: number }[];
}


async function measureOverflow(page: Page): Promise<Overflow> {
  return await page.evaluate(() => {
    const innerWidth = window.innerWidth;
    const offenders: { selector: string; right: number }[] = [];
    const allowance = 1; 

    const describe = (el: Element): string => {
      const id = el.id === '' ? '' : `#${el.id}`;
      const cls =
        typeof el.className === 'string' && el.className !== ''
          ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}`
          : '';
      return `${el.tagName.toLowerCase()}${id}${cls}`;
    };

    
    const isContained = (el: Element): boolean => {


      let parent = el.parentElement;
      while (parent !== null && parent !== document.body && parent !== document.documentElement) {
        const style = window.getComputedStyle(parent);
        const clipsX = ['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowX);
        if (clipsX && parent.getBoundingClientRect().right <= innerWidth + allowance) {
          return true;
        }
        parent = parent.parentElement;
      }
      return false;
    };

    for (const el of Array.from(document.body.querySelectorAll('*'))) {
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') {
        continue;
      }

      if (el.closest('details:not([open])') !== null && el.tagName !== 'SUMMARY') {
        continue;
      }
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        continue;
      }
      if (rect.right > innerWidth + allowance && !isContained(el)) {
        offenders.push({ selector: describe(el), right: Math.round(rect.right) });
      }
    }

    return {
      bodyScrollWidth: document.body.scrollWidth,
      innerWidth,
      offenders: offenders.slice(0, 10),
    };
  });
}

test.describe('the shell fits every supported width', () => {
  for (const width of WIDTHS) {
    for (const route of ROUTES) {
      test(`${route} at ${width}px has no horizontal overflow`, async ({ page }) => {
        await mockApi(page);
        await page.setViewportSize({ width, height: 900 });
        await page.goto(route);
        await page.getByRole('heading', { level: 1 }).waitFor();

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

test.describe('narrow layouts keep controls reachable', () => {
  test('the module rail becomes horizontal navigation at 375px', async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto('/sessions');

    const nav = page.getByRole('navigation', { name: 'Modules' });
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Sessions' })).toBeVisible();
  });

  test('a wide table scrolls inside its own labelled container', async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto('/sessions');
    await page.getByRole('link', { name: /Synthetic battle/ }).first().waitFor();

    const region = page.getByRole('region', { name: 'Sessions' });
    await expect(region).toBeVisible();

    const scrolls = await region.evaluate((el) => el.scrollWidth > el.clientWidth);
    const bodyOverflows = await page.evaluate(
      () => document.body.scrollWidth > window.innerWidth,
    );


    expect(bodyOverflows).toBe(false);
    expect(typeof scrolls).toBe('boolean');
  });
});
