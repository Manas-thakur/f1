import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.AFTERLAP_LIVE_URL;
if (baseURL === undefined) {
  throw new Error('AFTERLAP_LIVE_URL is required; run make audit to start the isolated stack');
}

export default defineConfig({
  testDir: './e2e-live',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 600_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    baseURL,
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: { mode: 'on', size: { width: 1440, height: 1000 } },
  },
});
