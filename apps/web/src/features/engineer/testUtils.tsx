/**
 * Test helpers for the feature routes.
 *
 * The clients under test are the **real** `ApiClient` and `LabClient` with a
 * stubbed `fetch`, not hand-written doubles. That way the header contract,
 * the typed-error decoding and the request bodies are all exercised, and a
 * test can assert exactly which requests were issued — including which were
 * not.
 */
import { QueryClient } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';

import { ApiClient } from '@/api/client';
import { Providers } from '@/app/Providers';
import { LabClient } from '../lab/controlPlane';

export interface RecordedRequest {
  readonly url: string;
  readonly method: string;
  readonly headers: Record<string, string>;
  readonly body: unknown;
}

export interface FetchStub {
  readonly fetchImpl: typeof fetch;
  readonly requests: RecordedRequest[];
  /** Requests whose URL contains the fragment. */
  matching: (fragment: string) => readonly RecordedRequest[];
}

export type RouteHandler = (request: RecordedRequest) => {
  status?: number;
  body: unknown;
};

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function apiError(
  code: string,
  message: string,
  status: number,
  requestId = 'req-test',
): { status: number; body: unknown } {
  return {
    status,
    body: { error: { code, message, retryable: false, request_id: requestId } },
  };
}

/**
 * A fetch that answers the first matching handler and records every call.
 *
 * An unmatched request is answered with a typed `not_found`, so a view that
 * calls a route the test did not expect fails loudly instead of hanging.
 */
export function makeFetch(handlers: readonly [string, RouteHandler][]): FetchStub {
  const requests: RecordedRequest[] = [];

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });
    const recorded: RecordedRequest = {
      url,
      method: init?.method ?? 'GET',
      headers,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
    };
    requests.push(recorded);

    for (const [fragment, handler] of handlers) {
      if (url.includes(fragment)) {
        const result = handler(recorded);
        return jsonResponse(result.body, result.status ?? 200);
      }
    }
    return jsonResponse(
      {
        error: {
          code: 'not_found',
          message: `no handler for ${url}`,
          retryable: false,
          request_id: 'req-unmatched',
        },
      },
      404,
    );
  }) as typeof fetch;

  return {
    fetchImpl,
    requests,
    matching: (fragment) => requests.filter((request) => request.url.includes(fragment)),
  };
}

export function apiClientFor(stub: FetchStub): ApiClient {
  return new ApiClient({ fetchImpl: stub.fetchImpl });
}

export function labClientFor(stub: FetchStub): LabClient {
  return new LabClient({ fetchImpl: stub.fetchImpl });
}

/**
 * A socket factory that opens but delivers nothing.
 *
 * It reports `open` on the next macrotask, which is what a real socket does
 * and what the console needs before it will offer a time-sensitive action.
 */
export function noSocket(): (url: string) => WebSocket {
  return (url) => socketFactory()(url);
}

/**
 * A factory producing `FakeSocket`s that open themselves.
 *
 * Pass a `collect` array to capture them and drive frames from a test.
 */
export function socketFactory(collect?: FakeSocket[]): (url: string) => WebSocket {
  return (url: string) => {
    const socket = new FakeSocket(url);
    collect?.push(socket);
    setTimeout(() => {
      if (!socket.closed) {
        socket.onopen?.({});
      }
    }, 0);
    return socket as unknown as WebSocket;
  };
}

/** A fake socket whose handlers a test can drive directly. */
export class FakeSocket {
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  closed = false;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
  }

  close(): void {
    this.closed = true;
  }

  send(): void {}

  emit(raw: unknown): void {
    this.onmessage?.({ data: typeof raw === 'string' ? raw : JSON.stringify(raw) } as MessageEvent);
  }
}

export interface RenderOptions {
  readonly path: string;
  readonly route: string;
}

export function renderRoute(element: ReactElement, options: RenderOptions): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[options.path]}>
      <Providers withRouter={false} queryClient={queryClient}>
        <Routes>
          <Route path={options.route} element={element} />
        </Routes>
      </Providers>
    </MemoryRouter>,
  );
}
