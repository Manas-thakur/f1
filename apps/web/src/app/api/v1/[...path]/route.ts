import type { NextRequest } from 'next/server';

import { forwardToPython } from '@/server/python';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

interface RouteContext {
  readonly params: Promise<{ path: string[] }>;
}

async function handle(request: NextRequest, context: RouteContext, method: string): Promise<Response> {
  const { path } = await context.params;
  const pathname = `/api/v1/${path.join('/')}`;
  return forwardToPython(request, method, pathname);
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return await handle(request, context, 'GET');
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return await handle(request, context, 'POST');
}

export async function PUT(request: NextRequest, context: RouteContext): Promise<Response> {
  return await handle(request, context, 'PUT');
}

export async function PATCH(request: NextRequest, context: RouteContext): Promise<Response> {
  return await handle(request, context, 'PATCH');
}

export async function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
  return await handle(request, context, 'DELETE');
}
