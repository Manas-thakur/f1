import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

export function repoRoot(): string {
  const fromEnv = process.env.AFTERLAP_ROOT;
  if (fromEnv !== undefined && fromEnv !== '') {
    return fromEnv;
  }
  let dir = process.cwd();
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(path.join(dir, 'pyproject.toml')) && existsSync(path.join(dir, 'apps', 'web'))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  return path.resolve(process.cwd(), '..', '..');
}

export interface CliResult {
  readonly stdout: string;
  readonly stderr: string;
  readonly code: number;
}

export function pythonCli(): { command: string; prefix: string[] } {
  const override = process.env.AFTERLAP_PYTHON;
  if (override !== undefined && override !== '') {
    return { command: override, prefix: ['-m', 'afterlap_api.cli'] };
  }
  return { command: 'uv', prefix: ['run', 'python', '-m', 'afterlap_api.cli'] };
}

export function invokeAfterlapApi(
  args: string[],
  options: { stdin?: string; timeoutMs?: number } = {},
): Promise<CliResult> {
  const { command, prefix } = pythonCli();
  const timeoutMs = options.timeoutMs ?? 60_000;
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...prefix, ...args], {
      cwd: repoRoot(),
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error(`afterlap CLI timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    child.stdout.on('data', (chunk: Buffer) => {
      stdout.push(chunk);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr.push(chunk);
    });
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
        code: code ?? 1,
      });
    });
    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin);
    }
    child.stdin.end();
  });
}

interface RuntimeSlot {
  started: boolean;
  starting: Promise<void> | undefined;
}

const runtimeSlot: RuntimeSlot = { started: false, starting: undefined };

async function runtimeIsLive(): Promise<boolean> {
  try {
    const result = await invokeAfterlapApi(['request', 'GET', '/api/v1/health/live'], {
      timeoutMs: 8_000,
    });
    if (result.stdout.trim() === '') {
      return false;
    }
    const parsed = JSON.parse(result.stdout) as { status?: number };
    return parsed.status === 200;
  } catch {
    return false;
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function ensurePythonRuntime(): Promise<void> {
  if (process.env.AFTERLAP_AUTOSTART_RUNTIME === '0') {
    return;
  }
  if (runtimeSlot.started) {
    return;
  }
  if (runtimeSlot.starting !== undefined) {
    await runtimeSlot.starting;
    return;
  }
  runtimeSlot.starting = (async () => {
    if (await runtimeIsLive()) {
      runtimeSlot.started = true;
      return;
    }
    const { command, prefix } = pythonCli();
    const child = spawn(command, [...prefix, 'serve', '--host', '127.0.0.1', '--port', '8000'], {
      cwd: repoRoot(),
      env: process.env,
      stdio: 'ignore',
      detached: false,
    });
    child.unref();
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (await runtimeIsLive()) {
        runtimeSlot.started = true;
        return;
      }
      await wait(250);
    }
    throw new Error('Python control-plane runtime did not become live');
  })();
  try {
    await runtimeSlot.starting;
  } finally {
    runtimeSlot.starting = undefined;
  }
}

export async function forwardToPython(request: Request, method: string, pathname: string): Promise<Response> {
  await ensurePythonRuntime();
  const url = new URL(request.url);
  const args = ['request', method, pathname];
  url.searchParams.forEach((value, name) => {
    args.push('--query', `${name}=${value}`);
  });
  const skip = new Set(['host', 'connection', 'content-length', 'accept-encoding']);
  request.headers.forEach((value, name) => {
    if (skip.has(name.toLowerCase())) {
      return;
    }
    args.push('--header', `${name}: ${value}`);
  });
  if (method !== 'GET' && method !== 'HEAD') {
    const body = await request.text();
    if (body !== '') {
      args.push('--body', body);
    }
  }
  const result = await invokeAfterlapApi(args);
  const raw = result.stdout.trim() || result.stderr.trim();
  let parsed: { status?: number; headers?: Record<string, string>; body?: unknown };
  try {
    parsed = JSON.parse(raw) as { status?: number; headers?: Record<string, string>; body?: unknown };
  } catch {
    return Response.json(
      {
        error: {
          code: 'internal',
          message: 'the Python CLI did not return JSON',
          retryable: true,
          request_id: 'cli-parse',
          details: { stderr: result.stderr.slice(0, 500) },
        },
      },
      { status: 500 },
    );
  }
  const status = parsed.status ?? 500;
  const headers = new Headers();
  headers.set('content-type', 'application/json');
  for (const [key, value] of Object.entries(parsed.headers ?? {})) {
    if (key === 'content-length' || key === 'transfer-encoding') {
      continue;
    }
    headers.set(key, value);
  }
  if (parsed.body === undefined || parsed.body === null) {
    return new Response(null, { status, headers });
  }
  return Response.json(parsed.body, { status, headers });
}
