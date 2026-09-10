
import type {
  CancelExperimentRequest,
  CreateExperimentRequest,
  CreateExperimentResponse,
  CreateExportRequest,
  CreateSessionRequest,
  CreateSessionResponse,
  CreateSnapshotRequest,
  CreateSnapshotResponse,
  ExperimentStatusResponse,
  ExportJobResponse,
  JobStatus,
} from '@contracts';

import { API_BASE, type RequestOptions } from '@/api/client';
import { ApiRequestError, isApiErrorResponse, toApiError } from '@/api/errors';

type FetchLike = typeof fetch;

export interface LabClientOptions {
  readonly base?: string;
  readonly fetchImpl?: FetchLike;
}

export class LabClient {
  private readonly base: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: LabClientOptions = {}) {
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

  createSession(body: CreateSessionRequest, options: RequestOptions) {
    return this.request<CreateSessionResponse>(
      '/sessions',
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createSnapshot(sessionId: string, body: CreateSnapshotRequest, options: RequestOptions) {
    return this.request<CreateSnapshotResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/snapshots`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createExperiment(body: CreateExperimentRequest, options: RequestOptions) {
    return this.request<CreateExperimentResponse>(
      '/experiments',
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  listExperiments(
    params: { status?: JobStatus; limit?: number } = {},
    options?: RequestOptions,
  ) {
    const search = new URLSearchParams();
    if (params.status !== undefined) {search.set('status', params.status);}
    if (params.limit !== undefined) {search.set('limit', String(params.limit));}
    const qs = search.toString();
    return this.request<readonly ExperimentStatusResponse[]>(
      `/experiments${qs === '' ? '' : `?${qs}`}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  cancelExperiment(
    experimentId: string,
    body: CancelExperimentRequest,
    options: RequestOptions,
  ) {
    return this.request<ExperimentStatusResponse>(
      `/experiments/${encodeURIComponent(experimentId)}/cancel`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createExport(body: CreateExportRequest, options: RequestOptions) {
    return this.request<ExportJobResponse>(
      '/exports',
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  
  getExperimentReport(experimentId: string, options?: RequestOptions) {
    return this.request<unknown>(
      `/experiments/${encodeURIComponent(experimentId)}/report`,
      { method: 'GET' },
      options ?? {},
    );
  }
}

export const labClient = new LabClient();
