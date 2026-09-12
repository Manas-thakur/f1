import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'race.spec.ts',
  workers: 1,
  timeout: 120000,
  use: { baseURL: 'http://127.0.0.1:18760', viewport: { width: 1440, height: 1100 } },
  webServer: {
    command: 'uv run python scripts/race_stack.py',
    cwd: '../..',
    url: 'http://127.0.0.1:18760/race',
    reuseExistingServer: true,
    timeout: 120000,
  },
});
