import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const srcDir = fileURLToPath(new URL('./src', import.meta.url));
const contractsDir = fileURLToPath(new URL('../../packages/contracts/generated', import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^@contracts$/, replacement: `${contractsDir}/contracts.ts` },
      { find: /^@contracts\//, replacement: `${contractsDir}/` },
      { find: /^@\//, replacement: `${srcDir}/` },
    ],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [fileURLToPath(new URL('./src/test/setup.ts', import.meta.url))],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    exclude: ['e2e/**', 'node_modules/**', '.next/**', '**/._*'],
    restoreMocks: true,
    css: true,
  },
});
