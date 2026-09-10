import type { NextRequest } from 'next/server';

import { forwardToPython } from '@/server/python';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest): Promise<Response> {
  return forwardToPython(request, 'GET', '/metrics');
}
