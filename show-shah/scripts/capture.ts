import { chromium, expect, type Page } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';

const origin = process.env.RACE_DEMO_URL ?? 'http://127.0.0.1:18950';
if (!['127.0.0.1', 'localhost'].includes(new URL(origin).hostname)) throw new Error('Use an isolated local demo runtime.');
const ffmpeg = process.env.FFMPEG_PATH ?? 'ffmpeg';
await mkdir('.build/capture', { recursive: true });
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
const records: { name: string; [key: string]: unknown }[] = process.env.CAPTURE_ONLY ? JSON.parse(await readFile('public/capture.json', 'utf8')).clips : [];
const warm = await browser.newPage();
await warm.goto(`${origin}/tel/car-01`);
if (!process.env.CAPTURE_ONLY) await command(warm, 'reset', { settings: { circuit: 'monza', cars: 3, seed: 42 } });
await warm.close();
async function capture(name: string, route: string, prepare: (page: Page) => Promise<void>, action?: (page: Page) => Promise<void>) {
  if (process.env.CAPTURE_ONLY && !process.env.CAPTURE_ONLY.split(',').includes(name)) return;
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: '.build/capture', size: { width: 1280, height: 720 } } });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(origin + route);
  await prepare(page);
  await page.waitForTimeout(2000);
  const actionPromise = action?.(page);
  await page.waitForTimeout(4000);
  await actionPromise;
  await page.waitForTimeout(13000);
  const video = page.video()!;
  await context.close();
  const path = await video.path();
  execFileSync(ffmpeg, ['-y', '-sseof', '-12', '-i', path, '-t', '12', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'fast', '-movflags', '+faststart', `public/${name}.mp4`], { stdio: 'pipe' });
  execFileSync(ffmpeg, ['-y', '-ss', '6', '-i', `public/${name}.mp4`, '-frames:v', '1', '-q:v', '2', `public/${name}.jpg`], { stdio: 'pipe' });
  if (errors.length) throw new Error(errors.join('\n'));
  const prior = records.findIndex((record) => record.name === name);
  if (prior >= 0) records.splice(prior, 1);
  records.push({ name, route, source: path.split('/').at(-1), trimFromEndSeconds: 12, durationSeconds: 12, playbackRate: 1, ...(name === 'boost' ? { response: JSON.parse(await readFile('.build/boost-response.json', 'utf8')) } : {}) });
  await writeFile('public/capture.json', JSON.stringify({ revision: 'dbb00c3', viewport: [1280, 720], renderer: 'software WebGL', clips: records }, null, 2) + '\n');
  console.log(`Captured ${name}: actual product, 12 seconds, no page errors`);
}
async function command(page: Page, operation: string, fields: Record<string, unknown> = {}) {
  await page.evaluate(({ operation, fields }) => new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(`${location.origin.replace('http', 'ws')}/race/socket`);
    const id = `capture-${operation}`;
    const timer = setTimeout(() => { socket.close(); reject(new Error('Command timed out')); }, 20000);
    socket.onopen = () => socket.send(JSON.stringify({ id, operation, ...fields }));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== id) return;
      clearTimeout(timer);
      socket.close();
      if (message.type === 'error') reject(new Error(message.message));
      else resolve();
    };
  }), { operation, fields });
}
async function race(page: Page) {
  await expect(page.getByRole('application', { name: '3D camera controls' })).toHaveAttribute('data-rendered-frames', /[1-9]/, { timeout: 90000 });
}
try {
  await capture('setup', '/race', async (page) => {
    await race(page);
    const pause = page.getByRole('button', { name: 'Pause race', exact: true });
    if (await pause.count()) await pause.click();
    await page.getByRole('button', { name: 'Race controls', exact: true }).click();
    await page.getByText('Configure a race', { exact: true }).scrollIntoViewIfNeeded();
  }, async (page) => { await page.waitForTimeout(2000); await page.getByRole('button', { name: 'Start race', exact: true }).click(); });
  await capture('overview', '/race', async (page) => { await race(page); await page.getByRole('button', { name: 'Full circuit', exact: true }).click(); });
  await capture('chase', '/race', race);
  await capture('energy', '/tel/car-01', async (page) => { await expect(page.locator('[data-connected="true"]')).toBeVisible({ timeout: 60000 }); });
  await capture('telemetry', '/tel/car-02', async (page) => { await expect(page.locator('[data-connected="true"]')).toBeVisible({ timeout: 60000 }); });
  await capture('decision', '/race', async (page) => {
    await race(page);
    await page.getByRole('button', { name: 'Race controls', exact: true }).click();
    await page.getByText('Energy decision engine', { exact: true }).scrollIntoViewIfNeeded();
  });
  await capture('boost', '/tel/car-01', async (page) => {
    await expect(page.locator('[data-connected="true"]')).toBeVisible({ timeout: 60000 });
    await command(page, 'reset', { settings: { circuit: 'monza', cars: 3, seed: 42 } });
    await command(page, 'speed', { speed: 0.25 });
    await command(page, 'start');
  }, async (page) => {
    const button = page.getByRole('button', { name: 'Apply boost to car-01', exact: true });
    await expect(button).toBeEnabled({ timeout: 90000 });
    const response = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/race/boost'));
    await button.click();
    const result = await response;
    await writeFile('.build/boost-response.json', JSON.stringify({ status: result.status(), body: await result.json() }, null, 2));
    expect(result.ok()).toBe(true);
  });
  await capture('engineer', '/race/engineer', async (page) => { await expect(page.getByText('SCENARIO MOCK', { exact: true })).toBeVisible({ timeout: 90000 }); await command(page, 'start'); await expect.poll(() => page.getByLabel('Live camera wall').locator('[data-rendered-frames]').evaluateAll((nodes) => nodes.length === 6 && nodes.every((node) => Number(node.getAttribute('data-rendered-frames')) >= 3)), { timeout: 180000 }).toBe(true); });
  await capture('cockpit', '/race', async (page) => { await race(page); await page.getByRole('button', { name: 'First person', exact: true }).click(); });
} finally { await browser.close(); }
