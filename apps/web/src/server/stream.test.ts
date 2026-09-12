import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const spawn = vi.hoisted(() => vi.fn());
vi.mock('node:child_process', () => ({ spawn, default: { spawn } }));
vi.mock('./python', () => ({
  ensurePythonRuntime: vi.fn(),
  pythonCli: () => ({ command: 'python', prefix: [] }),
  repoRoot: () => '.',
}));

import { GET } from '../app/api/v1/sessions/[sessionId]/stream/route';

class Child extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  kill = vi.fn();
}

const context = { params: Promise.resolve({ sessionId: 'test-session' }) };

async function openStream() {
  const child = new Child();
  spawn.mockReturnValue(child);
  const response = await GET(new NextRequest('http://localhost/stream'), context);
  const reader = response.body?.getReader();
  if (reader === undefined) {
    throw new Error('missing event stream');
  }
  await reader.read();
  return { child, reader };
}

describe('event stream bridge lifecycle', () => {
  beforeEach(() => spawn.mockReset());

  it.each(['nan', '-1', '1.5', '9007199254740992'])('rejects invalid cursor %s', async (cursor) => {
    const response = await GET(new NextRequest(`http://localhost/stream?after_sequence=${cursor}`), context);
    expect(response.status).toBe(400);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('closes the child without closing an already cancelled stream', async () => {
    const { child, reader } = await openStream();
    await reader.cancel();
    expect(child.kill).toHaveBeenCalledWith('SIGTERM');
    expect(() => child.emit('close', 0)).not.toThrow();
    expect(() => child.stdout.emit('data', Buffer.from('late\n'))).not.toThrow();
  });

  it('preserves split UTF-8 and never exposes stderr as an event', async () => {
    const { child, reader } = await openStream();
    const frame = Buffer.from('{"label":"\u03b1"}\n');
    const split = frame.indexOf(0xce) + 1;
    child.stderr.write('private diagnostic\n');
    child.stdout.emit('data', frame.subarray(0, split));
    child.stdout.emit('data', frame.subarray(split));
    const event = await reader.read();
    expect(new TextDecoder().decode(event.value)).toBe('data: {"label":"\u03b1"}\n\n');
    child.emit('close', 0);
    expect((await reader.read()).done).toBe(true);
  });

  it('sanitizes process failures and tolerates the subsequent close event', async () => {
    const { child, reader } = await openStream();
    child.emit('error', new Error('private/path/credential'));
    await expect(reader.read()).rejects.toThrow('the Python event stream is unavailable');
    expect(() => child.emit('close', 1)).not.toThrow();
  });
});
