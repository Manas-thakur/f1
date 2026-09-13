import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  if (request.method === 'POST') {
    return NextResponse.rewrite(new URL('/race/boost', request.url));
  }
  return NextResponse.next();
}

export const config = { matcher: '/race/engineer' };
