import { defineConfig, devices } from '@playwright/test';

const PORT = 4173;
const BASE_URL = `http://127.0.0.1:${PORT}`;


export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/._*'],
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
    command: `bunx vite preview --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: process.env['CI'] !== 'true',
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
