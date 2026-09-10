import { QueryClient } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';

import { ApiClient } from '@/api/client';
import { Providers } from '@/shell/Providers';
import { LabClient } from '../lab/controlPlane';
import { paramsFromRoute, setTestPath, testNav } from '@/test/navigation';

export interface RecordedRequest {
  readonly url: string;
  readonly method: string;
  readonly headers: Record<string, string>;
  readonly body: unknown;
}

export interface FetchStub {
  readonly fetchImpl: typeof fetch;
  readonly requests: RecordedRequest[];
  
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


export function hrefOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

export function makeFetch(handlers: readonly [string, RouteHandler][]): FetchStub {
  const requests: RecordedRequest[] = [];

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = hrefOf(input);
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


export function noSocket(): (url: string) => EventSource {
  return (url) => socketFactory()(url);
}


export function socketFactory(collect?: FakeSocket[]): (url: string) => EventSource {
  return (url: string) => {
    const socket = new FakeSocket(url);
    collect?.push(socket);
    setTimeout(() => {
      if (!socket.closed) {
        socket.onopen?.({} as Event);
      }
    }, 0);
    return socket as unknown as EventSource;
  };
}


export class FakeSocket {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
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
    this.onmessage?.({
      data: typeof raw === 'string' ? raw : JSON.stringify(raw),
    } as MessageEvent<string>);
  }
}

export interface RenderOptions {
  readonly path: string;
  readonly route: string;
}

export function renderRoute(element: ReactElement, options: RenderOptions): RenderResult {
  testNav.pathname = options.path;
  testNav.params = paramsFromRoute(options.route, options.path);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <Providers queryClient={queryClient}>
      {element}
    </Providers>,
  );
}

export { setTestPath };
