import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';

const here = path.dirname(fileURLToPath(import.meta.url));
const nextConfig: NextConfig = {
  output: 'standalone',
  distDir: process.env['NEXT_DIST_DIR'] ?? '.next',
  outputFileTracingRoot: path.resolve(here, '../..'),
  poweredByHeader: false,
  devIndicators: false,
  reactStrictMode: true,
  allowedDevOrigins: process.env['RACE_ALLOWED_DEV_ORIGINS']?.split(','),
  async rewrites() {
    return [{
      source: '/race/socket',
      destination: `${process.env['AFTERLAP_RACE_UPSTREAM'] ?? 'http://127.0.0.1:18761'}/`,
    }];
  },
};

export default nextConfig;
