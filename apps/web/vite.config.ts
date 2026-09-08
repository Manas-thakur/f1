import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const srcDir = fileURLToPath(new URL('./src', import.meta.url));
const contractsDir = fileURLToPath(new URL('../../packages/contracts/generated', import.meta.url));
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));


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


      '/api': { target: API_ORIGIN, ws: true, changeOrigin: false },
      '/ws': { target: API_ORIGIN, ws: true, changeOrigin: false },
    },
  },
  preview: {


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
