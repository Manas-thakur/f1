import { describe, expect, it, vi } from 'vitest';

import { useSessionStore } from '../state/sessionStore';
import { selectHasConflict, selectIsRequestPending } from '../state/selectors';
import { ApiClient } from './client';
import { ApiRequestError } from './errors';
import { commandKeys, runCommand } from './commands';

function hrefOf(input: string | URL | Request): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function bridge() {
  const store = useSessionStore.getState();
  return {
    beginRequest: store.beginRequest,
    settleRequest: store.settleRequest,
    failRequest: store.failRequest,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const KEY = commandKeys.recommendationAction('rec-001', 'select');

describe('a command in flight blocks duplicate submission', () => {
  it('suppresses the second submission and calls the transport once', async () => {
    const gate = deferred<{ ok: true }>();
    const send = vi.fn(() => gate.promise);

    const first = runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send,
    });

    expect(selectIsRequestPending(useSessionStore.getState(), KEY)).toBe(true);

    const second = await runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send,
    });

    expect(second.status).toBe('duplicate_suppressed');
    expect(send).toHaveBeenCalledTimes(1);

    gate.resolve({ ok: true });
    const firstResult = await first;
    expect(firstResult.status).toBe('ok');
    expect(selectIsRequestPending(useSessionStore.getState(), KEY)).toBe(false);
  });

  it('allows a fresh submission once the first has settled', async () => {
    const send = vi.fn(async () => ({ ok: true }));
    await runCommand(bridge(), { key: KEY, kind: 'select', expectedRevision: 7, send });
    await runCommand(bridge(), { key: KEY, kind: 'select', expectedRevision: 8, send });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('carries a distinct idempotency key per submission', async () => {
    const keys: string[] = [];
    const send = vi.fn(async (idempotencyKey: string) => {
      keys.push(idempotencyKey);
      return { ok: true };
    });
    await runCommand(bridge(), { key: KEY, kind: 'select', expectedRevision: 7, send });
    await runCommand(bridge(), { key: KEY, kind: 'select', expectedRevision: 8, send });
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);
    expect(keys[0]).toBeTruthy();
  });
});

describe('a 409 refreshes evidence and does not retry', () => {
  it('reports a conflict, calls the refresh hook once, and never resends', async () => {
    const conflict = new ApiRequestError(409, {
      code: 'stale_revision',
      message: 'session revision moved from 7 to 9',
      retryable: false,
      request_id: 'req-409',
    });
    const send = vi.fn(async () => {
      throw conflict;
    });
    const onConflict = vi.fn();

    const outcome = await runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send,
      onConflict,
    });

    expect(outcome.status).toBe('conflict');
    expect(send).toHaveBeenCalledTimes(1);
    expect(onConflict).toHaveBeenCalledTimes(1);

    const state = useSessionStore.getState();
    expect(selectIsRequestPending(state, KEY)).toBe(false);
    expect(selectHasConflict(state, KEY)).toBe(true);
    expect(state.request.lastError?.code).toBe('stale_revision');
  });

  it('treats an idempotency conflict as a conflict too', async () => {
    const send = vi.fn(async () => {
      throw new ApiRequestError(409, {
        code: 'idempotency_conflict',
        message: 'same key, different body',
        retryable: false,
        request_id: 'req-409b',
      });
    });
    const outcome = await runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send,
    });
    expect(outcome.status).toBe('conflict');
  });

  it('reports a non-conflict failure as an error without a refresh', async () => {
    const onConflict = vi.fn();
    const send = vi.fn(async () => {
      throw new ApiRequestError(503, {
        code: 'capability_unavailable',
        message: 'rule coverage unavailable',
        retryable: false,
        request_id: 'req-503',
      });
    });
    const outcome = await runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send,
      onConflict,
    });
    expect(outcome.status).toBe('error');
    expect(onConflict).not.toHaveBeenCalled();
    expect(selectHasConflict(useSessionStore.getState(), KEY)).toBe(false);
  });

  it('never optimistically mutates the recommendation status', async () => {
    const before = useSessionStore.getState().server.recommendation;
    await runCommand(bridge(), {
      key: KEY,
      kind: 'select',
      expectedRevision: 7,
      send: async () => ({ ok: true }),
    });
    expect(useSessionStore.getState().server.recommendation).toBe(before);
  });
});

describe('ApiClient error decoding', () => {
  it('turns a typed error body into an ApiRequestError', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: 'recommendation_expired',
              message: 'expired at 128.4 s',
              retryable: false,
              request_id: 'req-1',
            },
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
    );
    const client = new ApiClient({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await expect(client.getSnapshot('s1')).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 422,
    });
  });

  it('sends the Idempotency-Key header on a write', async () => {
    const seen: { url: string; headers: Headers }[] = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      seen.push({ url: hrefOf(url), headers: new Headers(init?.headers) });
      return new Response(JSON.stringify({ accepted: true, revision: 8, sequence: 1, status: 'running' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    const client = new ApiClient({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await client.sendSessionCommand(
      'session-1',
      { kind: 'start', expected_revision: 7, operator_id: 'engineer-1' },
      { idempotencyKey: 'idem-abc' },
    );

    expect(seen[0]?.headers.get('Idempotency-Key')).toBe('idem-abc');
    expect(seen[0]?.url).toBe('/api/v1/sessions/session-1/commands');
  });
});
