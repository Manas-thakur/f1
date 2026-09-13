import { chromium, expect } from '@playwright/test';
import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';
import { chapters, WIDTH, HEIGHT, SECONDS, REVISION } from '../src/story';
const origin = process.env.DECK_URL ?? 'http://127.0.0.1:18940';
await mkdir('dist/slides', { recursive: true });
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
try {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (let attempt = 0; attempt < 40; attempt++) {
    try { if ((await fetch(origin)).ok) break; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  await page.goto(`${origin}/?capture`);
  await page.waitForFunction(() => window.showShahReady);
  const images: string[] = [];
  for (let index = 0; index < chapters.length; index++) {
    await page.evaluate((value) => window.deck.slide(value), index);
    await expect(page.locator('section.present h1')).toHaveText(chapters[index].title);
    const slide = page.locator('section.present');
    expect((await slide.boundingBox())?.height).toBeGreaterThan(1000);
    await expect(slide.locator('.visual canvas, .visual img')).toBeVisible();
    await page.waitForTimeout(1000);
    const path = `dist/slides/${String(index + 1).padStart(2, '0')}.jpg`;
    await slide.locator('.slide-art').screenshot({ path, type: 'jpeg', quality: 93 });
    images.push((await readFile(path)).toString('base64'));
  }
  if (errors.length) throw new Error(errors.join('\n'));
  const print = await browser.newPage();
  await print.setContent(`<html><head><style>@page{size:1920px 1080px;margin:0}body{margin:0}img{display:block;width:1920px;height:1080px;break-after:page}</style></head><body>${images.map((data) => `<img src="data:image/jpeg;base64,${data}" />`).join('')}</body></html>`);
  await print.pdf({ path: 'dist/show-shah.pdf', printBackground: true, preferCSSPageSize: true });
  const timestamp = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}.000`;
  await writeFile('dist/show-shah.vtt', `WEBVTT\n\n${chapters.map((c, i) => `${i + 1}\n00:${timestamp(i * SECONDS)} --> 00:${timestamp((i + 1) * SECONDS)}\n${c.caption}\n`).join('\n')}`);
  await writeFile('dist/speaker-notes.md', chapters.map((c, i) => `## ${i + 1}. ${c.title.replace('\n', ' ')}\n\n${c.notes}\n\nSources: ${c.sources.map((path) => `[${path}](https://github.com/Manas-thakur/f1/blob/${REVISION}/${path})`).join(', ')}\n`).join('\n'));
  await copyFile('SOURCES.md', 'dist/SOURCES.md');
  console.log(`Exported ${chapters.length} slides, PDF, captions and speaker notes; no browser errors.`);
} finally { await browser.close(); }
