import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const srcDir = fileURLToPath(new URL('./src', import.meta.url));
const contractsDir = fileURLToPath(new URL('../../packages/contracts/generated', import.meta.url));
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));

// The Python API owns /api and /ws. In development Vite proxies both to the
// local API process; in production nginx serves the built assets and proxies
// the same two prefixes from the same origin, so no absolute API host is ever
// compiled into the bundle.
const API_ORIGIN = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^@contracts$/, replacement: `${contractsDir}/contracts.ts` },
      { find: /^@contracts\//, replacement: `${contractsDir}/` },
      { find: /^@\//, replacement: `${srcDir}/` },
    ],
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: [repoRoot] },
    proxy: {
      '/api': { target: API_ORIGIN, changeOrigin: false },
      '/ws': { target: API_ORIGIN, ws: true, changeOrigin: false },
    },
  },
  preview: {
    // Bind explicitly to the loopback IPv4 address: the default `localhost`
    // resolves to ::1 only on some Windows hosts, and the e2e suite then
    // cannot reach the server it just started.
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
  },
});
