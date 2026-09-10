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
  turbopack: {
    resolveAlias: {
      '@contracts': contractsFile,
    },
  },
};

export default nextConfig;
