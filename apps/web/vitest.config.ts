import { fileURLToPath, URL } from 'node:url';

import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config.ts';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: [fileURLToPath(new URL('./src/test/setup.ts', import.meta.url))],
      include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
      exclude: ['e2e/**', 'node_modules/**', 'dist/**', '**/._*'],
      restoreMocks: true,
      css: true,
    },
  }),
);
