import { defineConfig } from '@playwright/test';

const externalUrl = process.env['RACE_TEST_URL'];
const webPort = process.env['RACE_WEB_PORT'] ?? '18860';
const simulatorPort = process.env['RACE_SIM_PORT'] ?? '18861';

export default defineConfig({
  testDir: './e2e',
  testMatch: ['race.spec.ts', 'motion.spec.ts', 'telemetry.spec.ts'],
  workers: 1,
  retries: process.env['CI'] ? 1 : 0,
  timeout: 120000,
  expect: { timeout: 20000 },
  use: {
    baseURL: externalUrl ?? `http://127.0.0.1:${webPort}`,
    viewport: { width: 1440, height: 1100 },
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  webServer: externalUrl ? [] : {
    command: 'uv run python scripts/race_stack.py',
    cwd: '../..',
    url: `http://127.0.0.1:${webPort}/race`,
    reuseExistingServer: false,
    env: { RACE_WEB_PORT: webPort, RACE_SIM_PORT: simulatorPort, RACE_CARS: '1' },
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15000 },
    timeout: 120000,
  },
});
