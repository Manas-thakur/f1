import { spawn } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';

import type { NextRequest } from 'next/server';

import { ensurePythonRuntime, pythonCli, repoRoot } from '@/server/python';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

interface RouteContext {
  readonly params: Promise<{ sessionId: string }>;
}

const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

function refuse(message: string): Response {
  return Response.json(
    {
      error: {
        code: 'validation_failed',
        message,
        retryable: false,
        request_id: 'stream-bridge',
        details: {},
      },
    },
    { status: 400 },
  );
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  const { sessionId } = await context.params;
  if (!SESSION_ID.test(sessionId)) {
    return refuse('session id must match the identifier contract');
  }
  const after = request.nextUrl.searchParams.get('after_sequence') ?? '0';
  if (!/^\d+$/.test(after) || !Number.isSafeInteger(Number(after))) {
    return refuse('after_sequence must be a non-negative safe integer');
  }
  await ensurePythonRuntime();
  const { command, prefix } = pythonCli();
  const child = spawn(command, [...prefix, 'stream', '--after-sequence', after, '--', sessionId], {
    cwd: repoRoot(),
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  const encoder = new TextEncoder();
  const decoder = new StringDecoder('utf8');
  let closed = false;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(': connected\n\n'));
      const send = (line: string): void => {
        controller.enqueue(encoder.encode(`data: ${line}\n\n`));
      };
      let buffer = '';
      child.stdout.on('data', (chunk: Buffer) => {
        if (closed) {
          return;
        }
        buffer += decoder.write(chunk);
        const parts = buffer.split('\n');
        buffer = parts.pop() ?? '';
        for (const part of parts) {
          const line = part.trim();
          if (line !== '') {
            send(line);
          }
        }
      });
      child.stderr.resume();
      child.on('close', () => {
        if (closed) {
          return;
        }
        closed = true;
        controller.close();
      });
      child.on('error', () => {
        if (closed) {
          return;
        }
        closed = true;
        controller.error(new Error('the Python event stream is unavailable'));
      });
    },
    cancel() {
      closed = true;
      child.kill('SIGTERM');
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
