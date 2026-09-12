import path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { NextConfig } from 'next';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../..');
const contractsFile = path.join(repoRoot, 'packages/contracts/generated/contracts.ts');

const nextConfig: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: repoRoot,
  poweredByHeader: false,
  reactStrictMode: true,
  typedRoutes: false,
  async rewrites() {
    return [
      {
        source: '/race/socket',
        destination: `${process.env['AFTERLAP_RACE_UPSTREAM'] ?? 'http://127.0.0.1:18761'}/`,
      },
    ];
  },
  turbopack: {
    resolveAlias: {
      '@contracts': contractsFile,
    },
  },
};

export default nextConfig;
