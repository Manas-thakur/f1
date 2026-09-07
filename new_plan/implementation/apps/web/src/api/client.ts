/**
 * Typed REST client for the control plane.
 *
 * All paths are same-origin and relative. In development Vite proxies `/api`
 * to the Python process; in production nginx serves the built assets and
 * proxies the same prefix. No API host is ever compiled into the bundle.
 */
import type {
  AcquireLeaseRequest,
  AcquireLeaseResponse,
  DecisionEvidenceResponse,
  DriverActionRequest,
  DriverActionResponse,
  ExperimentStatusResponse,
  ModelListResponse,
  RecommendationActionRequest,
  RecommendationActionResponse,
  RulesetResponse,
  SessionCommandRequest,
  SessionCommandResponse,
  SessionListResponse,
  SessionSnapshot,
} from '@contracts';

import { ApiRequestError, isApiErrorResponse, toApiError } from './errors';

export const API_BASE = '/api/v1';

export interface RequestOptions {
  readonly signal?: AbortSignal;
  readonly idempotencyKey?: string;
}

type FetchLike = typeof fetch;

export interface ApiClientOptions {
  readonly base?: string;
  readonly fetchImpl?: FetchLike;
}

/** Crypto-backed where available; the fallback is still unique per call. */
export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID();
  }
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export class ApiClient {
  private readonly base: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: ApiClientOptions = {}) {
    this.base = options.base ?? API_BASE;
    this.fetchImpl = options.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  private async request<T>(
    path: string,
    init: RequestInit,
    options: RequestOptions = {},
  ): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (init.body !== undefined && init.body !== null) {
      headers.set('Content-Type', 'application/json');
    }
    if (options.idempotencyKey !== undefined) {
      headers.set('Idempotency-Key', options.idempotencyKey);
    }

    const requestInit: RequestInit = { ...init, headers };
    if (options.signal !== undefined) {
      requestInit.signal = options.signal;
    }

    const response = await this.fetchImpl(`${this.base}${path}`, requestInit);

    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      const apiError = isApiErrorResponse(body)
        ? toApiError(body, response.statusText)
        : toApiError(null, `${response.status} ${response.statusText}`);
      throw new ApiRequestError(response.status, apiError);
    }

    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  // ---- reads --------------------------------------------------------------

  listSessions(params: { cursor?: string; mode?: string } = {}, options?: RequestOptions) {
    const search = new URLSearchParams();
    if (params.cursor !== undefined) search.set('cursor', params.cursor);
    if (params.mode !== undefined) search.set('mode', params.mode);
    const qs = search.toString();
    return this.request<SessionListResponse>(
      `/sessions${qs === '' ? '' : `?${qs}`}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  getSnapshot(sessionId: string, options?: RequestOptions) {
    return this.request<SessionSnapshot>(
      `/sessions/${encodeURIComponent(sessionId)}/snapshot`,
      { method: 'GET' },
      options ?? {},
    );
  }

  getDecision(decisionId: string, options?: RequestOptions) {
    return this.request<DecisionEvidenceResponse>(
      `/decisions/${encodeURIComponent(decisionId)}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  getRuleset(rulesetId: string, options?: RequestOptions) {
    return this.request<RulesetResponse>(
      `/rulesets/${encodeURIComponent(rulesetId)}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  listModels(options?: RequestOptions) {
    return this.request<ModelListResponse>('/models', { method: 'GET' }, options ?? {});
  }

  getExperiment(experimentId: string, options?: RequestOptions) {
    return this.request<ExperimentStatusResponse>(
      `/experiments/${encodeURIComponent(experimentId)}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  // ---- writes: every one carries Idempotency-Key and expected_revision -----

  acquireLease(sessionId: string, body: AcquireLeaseRequest, options: RequestOptions) {
    return this.request<AcquireLeaseResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/control-lease`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  sendSessionCommand(sessionId: string, body: SessionCommandRequest, options: RequestOptions) {
    return this.request<SessionCommandResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/commands`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  sendRecommendationAction(
    sessionId: string,
    recommendationId: string,
    body: RecommendationActionRequest,
    options: RequestOptions,
  ) {
    return this.request<RecommendationActionResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/recommendations/${encodeURIComponent(
        recommendationId,
      )}/actions`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  sendDriverAction(sessionId: string, body: DriverActionRequest, options: RequestOptions) {
    return this.request<DriverActionResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/simulator/driver-action`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }
}

export const apiClient = new ApiClient();
