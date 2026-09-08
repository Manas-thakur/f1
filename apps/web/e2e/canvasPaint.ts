import type { Page } from '@playwright/test';


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
        const value = text;
        const width = this.measureText(value).width;
        const transform = this.getTransform();

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
  );
}

const NUMERIC = /^-?\d+(?:[.,]\d+)*$/;

export function isNumericLabel(text: string): boolean {
  return NUMERIC.test(text.trim());
}

export function numericValue(text: string): number {
  return Number(text.trim().replace(/,/g, ''));
}


export const TIME_LIKE = [
  /\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?/i,
  /\b1\/1\/70\b/,
  /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/,
  /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b/i,
] as const;

export function looksLikeTime(text: string): boolean {
  return TIME_LIKE.some((pattern) => pattern.test(text));
}
