import type { Page } from '@playwright/test';

/**
 * Reads what the chart actually paints.
 *
 * uPlot draws its axis ticks and labels straight onto a canvas, so no DOM
 * query can see them. This helper patches `CanvasRenderingContext2D.fillText`
 * before any page script runs and records every string that gets painted,
 * together with the box it occupies. That is the only way to assert on the
 * axis a reader really sees — the gap that let a distance axis render as
 * "5:30am … 1/1/70" through 154 unit tests and 48 browser tests.
 *
 * Coordinates are in device pixels, which is also what uPlot works in, so the
 * clipping comparison against the canvas width is apples to apples.
 */
export interface PaintedText {
  readonly text: string;
  readonly x: number;
  readonly y: number;
  readonly left: number;
  readonly right: number;
  readonly align: string;
  readonly canvasWidth: number;
  readonly canvasHeight: number;
  readonly rotated: boolean;
}

export async function recordCanvasText(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const store: unknown[] = [];
    (window as unknown as { __paintedText: unknown[] }).__paintedText = store;

    const original = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function patchedFillText(
      this: CanvasRenderingContext2D,
      text: string,
      x: number,
      y: number,
      maxWidth?: number,
    ): void {
      try {
        const value = String(text);
        const width = this.measureText(value).width;
        const transform = this.getTransform();
        // uPlot rotates the context when it paints a vertical axis label.
        const rotated = Math.abs(transform.b) > 0.01 || Math.abs(transform.c) > 0.01;
        let left = x;
        if (this.textAlign === 'center') {
          left = x - width / 2;
        } else if (this.textAlign === 'right' || this.textAlign === 'end') {
          left = x - width;
        }
        store.push({
          text: value,
          x,
          y,
          left,
          right: left + width,
          align: this.textAlign,
          canvasWidth: this.canvas.width,
          canvasHeight: this.canvas.height,
          rotated,
        });
      } catch {
        // Never let instrumentation break the page under test.
      }
      if (maxWidth === undefined) {
        original.call(this, text, x, y);
      } else {
        original.call(this, text, x, y, maxWidth);
      }
    };
  });
}

export async function paintedText(page: Page): Promise<PaintedText[]> {
  return page.evaluate(
    () => (window as unknown as { __paintedText: PaintedText[] }).__paintedText ?? [],
  ) as Promise<PaintedText[]>;
}

const NUMERIC = /^-?\d+(?:[.,]\d+)*$/;

export function isNumericLabel(text: string): boolean {
  return NUMERIC.test(text.trim());
}

export function numericValue(text: string): number {
  return Number(text.trim().replace(/,/g, ''));
}

/** Painted strings that look like a wall-clock time or a Unix-epoch date. */
export const TIME_LIKE = [
  /\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?/i,
  /\b1\/1\/70\b/,
  /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/,
  /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b/i,
] as const;

export function looksLikeTime(text: string): boolean {
  return TIME_LIKE.some((pattern) => pattern.test(text));
}
