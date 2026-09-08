import type { Page } from '@playwright/test';

/**
 * Horizontal-overflow measurement.
 *
 * Same method as A12's `responsive.spec.ts`, extracted so the feature routes
 * can be checked the same way: the document must not widen, **and** no element
 * may extend past the viewport unless a real scroll container between it and
 * the viewport contains it. Checking only `document.body.scrollWidth` misses a
 * child inside an `overflow: hidden` ancestor, which is exactly how a broken
 * layout hides.
 */
export interface Overflow {
  readonly bodyScrollWidth: number;
  readonly innerWidth: number;
  readonly offenders: readonly { selector: string; right: number }[];
}

export async function measureOverflow(page: Page): Promise<Overflow> {
  return page.evaluate(() => {
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
