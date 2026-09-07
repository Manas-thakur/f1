import { defineConfig, devices } from '@playwright/test';

const PORT = 4173;
const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * End-to-end configuration.
 *
 * The suite runs against the *built* application served by `vite preview`, not
 * the dev server, so what is tested is what would be shipped. Headless
 * Chromium only: this is a check on the product, not a browser matrix.
 *
 * The API is mocked with route interception inside the tests. There is no
 * backend dependency here yet; A08 lands it later.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: process.env['CI'] === 'true',
  retries: 0,
  ...(process.env['CI'] === 'true' ? { workers: 1 } : {}),
  reporter: [['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `pnpm exec vite preview --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: process.env['CI'] !== 'true',
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
