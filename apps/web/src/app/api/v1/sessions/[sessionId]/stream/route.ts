import { spawn } from 'node:child_process';

import type { NextRequest } from 'next/server';

import { ensurePythonRuntime, pythonCli, repoRoot } from '@/server/python';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

interface RouteContext {
  readonly params: Promise<{ sessionId: string }>;
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  await ensurePythonRuntime();
  const { sessionId } = await context.params;
  const after = request.nextUrl.searchParams.get('after_sequence') ?? '0';
  const { command, prefix } = pythonCli();
  const child = spawn(
    command,
    [...prefix, 'stream', sessionId, '--after-sequence', after],
    { cwd: repoRoot(), env: process.env, stdio: ['ignore', 'pipe', 'pipe'] },
  );

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (line: string): void => {
        controller.enqueue(encoder.encode(`data: ${line}\n\n`));
      };
      let buffer = '';
      child.stdout.on('data', (chunk: Buffer) => {
        buffer += chunk.toString('utf8');
        const parts = buffer.split('\n');
        buffer = parts.pop() ?? '';
        for (const part of parts) {
          const line = part.trim();
          if (line !== '') {
            send(line);
          }
        }
      });
      child.stderr.on('data', (chunk: Buffer) => {
        const text = chunk.toString('utf8').trim();
        if (text !== '') {
          send(text);
        }
      });
      child.on('close', () => {
        controller.close();
      });
      child.on('error', (error) => {
        controller.error(error);
      });
    },
    cancel() {
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
