import { defineConfig } from '@playwright/test';

const webPort = process.env['RACE_WEB_PORT'] ?? '18860';
const simulatorPort = process.env['RACE_SIM_PORT'] ?? '18861';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'race.spec.ts',
  workers: 1,
  timeout: 120000,
  use: { baseURL: `http://127.0.0.1:${webPort}`, viewport: { width: 1440, height: 1100 } },
  webServer: {
    command: 'uv run python scripts/race_stack.py',
    cwd: '../..',
    url: `http://127.0.0.1:${webPort}/race`,
    reuseExistingServer: false,
    env: { RACE_WEB_PORT: webPort, RACE_SIM_PORT: simulatorPort },
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15000 },
    timeout: 120000,
  },
});
