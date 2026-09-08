/**
 * Control-plane routes the shared `ApiClient` does not cover yet.
 *
 * This is **not** a second API client and not a second format. It uses the
 * same base path, the same `Idempotency-Key` header contract and the same
 * typed-error decoding as `src/api/client.ts`; it exists only because the
 * shared client is owned by another agent and does not yet expose the
 * laboratory routes. `handoffs/A09-A11-shared-patch.md` carries the exact
 * patch that folds these five methods into `ApiClient`.
 *
 * Two request/response envelopes below are declared here rather than imported
 * because the generated bundle does not emit them (`CreateSnapshotRequest`,
 * `CreateSnapshotResponse`, `CreateExperimentResponse`, `CancelExperimentRequest`
 * and `CreateExportRequest` exist in `afterlap_contracts.requests` but not in
 * `packages/contracts/generated/contracts.ts`). Every field type is taken from
 * a generated type; nothing here invents a wire shape. That generator gap is a
 * named integration action.
 */
import type {
  CreateExperimentRequest,
  CreateSessionResponse,
  ExperimentJob,
  ExperimentStatusResponse,
  ExportJobResponse,
  JobStatus,
  SessionMode,
  SnapshotReference,
} from '@contracts';

import { API_BASE, type RequestOptions } from '@/api/client';
import { ApiRequestError, isApiErrorResponse, toApiError } from '@/api/errors';

/** `afterlap_contracts.requests.CreateSnapshotRequest`. */
export interface CreateSnapshotRequestBody {
  readonly label?: string | null;
}

/** `afterlap_contracts.requests.CreateSnapshotResponse`. */
export interface CreateSnapshotResponseBody {
  readonly snapshot: SnapshotReference;
}

/** `afterlap_contracts.requests.CreateExperimentResponse`. */
export interface CreateExperimentResponseBody {
  readonly job: ExperimentJob;
}

/** `afterlap_contracts.requests.CancelExperimentRequest`. */
export interface CancelExperimentRequestBody {
  readonly reason: string;
}

/** `afterlap_contracts.requests.CreateExportRequest`. */
export interface CreateExportRequestBody {
  readonly session_id: string;
  readonly format: 'json' | 'csv' | 'parquet';
  readonly start_session_time_s?: number | null;
  readonly end_session_time_s?: number | null;
}

/** `afterlap_contracts.requests.CreateSessionRequest`. */
export interface CreateSessionRequestBody {
  readonly mode: SessionMode;
  readonly scenario_id: string;
  readonly ruleset_id: string;
  readonly seed: number;
  readonly model_bundle_id?: string | null;
  readonly label?: string | null;
}

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

  createSession(body: CreateSessionRequestBody, options: RequestOptions) {
    return this.request<CreateSessionResponse>(
      '/sessions',
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createSnapshot(sessionId: string, body: CreateSnapshotRequestBody, options: RequestOptions) {
    return this.request<CreateSnapshotResponseBody>(
      `/sessions/${encodeURIComponent(sessionId)}/snapshots`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createExperiment(body: CreateExperimentRequest, options: RequestOptions) {
    return this.request<CreateExperimentResponseBody>(
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
    if (params.status !== undefined) search.set('status', params.status);
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    const qs = search.toString();
    return this.request<readonly ExperimentStatusResponse[]>(
      `/experiments${qs === '' ? '' : `?${qs}`}`,
      { method: 'GET' },
      options ?? {},
    );
  }

  cancelExperiment(
    experimentId: string,
    body: CancelExperimentRequestBody,
    options: RequestOptions,
  ) {
    return this.request<ExperimentStatusResponse>(
      `/experiments/${encodeURIComponent(experimentId)}/cancel`,
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  createExport(body: CreateExportRequestBody, options: RequestOptions) {
    return this.request<ExportJobResponse>(
      '/exports',
      { method: 'POST', body: JSON.stringify(body) },
      options,
    );
  }

  /**
   * The benchmark report body.
   *
   * **This route does not exist in the control plane today.** `GET
   * /experiments/{id}` returns a server-side filesystem path
   * (`report_path`), which a browser cannot read, and nothing serves the
   * report JSON. The evidence view calls this, gets a typed `not_found`, and
   * renders the report section as unavailable naming the missing route rather
   * than inventing numbers. See the integration action in
   * `handoffs/A09-A11.md`.
   */
  getExperimentReport(experimentId: string, options?: RequestOptions) {
    return this.request<unknown>(
      `/experiments/${encodeURIComponent(experimentId)}/report`,
      { method: 'GET' },
      options ?? {},
    );
  }
}

export const labClient = new LabClient();
