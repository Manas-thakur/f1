import type {
  CentrelineResponse,
  ConditionsListResponse,
  ScenarioListResponse,
  TrackListResponse,
} from '@contracts';

import { API_BASE, type RequestOptions } from '@/api/client';
import { ApiRequestError, isApiErrorResponse, toApiError } from '@/api/errors';
import { validateAs } from '@/api/validate';


export class ShapeMismatchError extends Error {
  constructor(problem: string) {
    super(problem);
    this.name = 'ShapeMismatchError';
  }
}

function centrelineProblem(body: CentrelineResponse): string | null {
  const x = body.x_m ?? [];
  const y = body.y_m ?? [];
  if (x.length !== y.length) {
    return `the centreline arrays disagree in length (x_m ${x.length}, y_m ${y.length})`;
  }
  if (x.length < 4) {
    return `the centreline response carries ${x.length} points; a closed circuit needs at least four`;
  }
  return null;
}

type FetchLike = typeof fetch;

export interface TrackCatalogueClientOptions {
  readonly base?: string;
  readonly fetchImpl?: FetchLike;
}

export class TrackCatalogueClient {
  private readonly base: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: TrackCatalogueClientOptions = {}) {
    this.base = options.base ?? API_BASE;
    this.fetchImpl = options.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  private async read<T>(
    path: string,
    modelName: string,
    options: RequestOptions,
    check?: (value: T) => string | null,
  ): Promise<T> {
    const headers = new Headers({ Accept: 'application/json' });
    const init: RequestInit = { method: 'GET', headers };
    if (options.signal !== undefined) {
      init.signal = options.signal;
    }

    const response = await this.fetchImpl(`${this.base}${path}`, init);
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

    const validated = validateAs<T>(modelName, await response.json());
    if (!validated.ok) {
      throw new ShapeMismatchError(`${modelName}: ${validated.message}`);
    }
    const problem = check === undefined ? null : check(validated.value);
    if (problem !== null) {
      throw new ShapeMismatchError(problem);
    }
    return validated.value;
  }

  listTracks(options: RequestOptions = {}) {
    return this.read<TrackListResponse>('/tracks', 'TrackListResponse', options);
  }

  getCentreline(trackId: string, strideM: number, options: RequestOptions = {}) {
    const search = new URLSearchParams({ stride_m: String(strideM) });
    return this.read<CentrelineResponse>(
      `/tracks/${encodeURIComponent(trackId)}/centreline?${search.toString()}`,
      'CentrelineResponse',
      options,
      centrelineProblem,
    );
  }

  listConditions(options: RequestOptions = {}) {
    return this.read<ConditionsListResponse>('/conditions', 'ConditionsListResponse', options);
  }

  listScenarios(options: RequestOptions = {}) {
    return this.read<ScenarioListResponse>('/scenarios', 'ScenarioListResponse', options);
  }
}

export const trackCatalogueClient = new TrackCatalogueClient();

export function catalogueFailureText(route: string, error: unknown): string {
  if (error instanceof ShapeMismatchError) {
    return `${route} answered with a body this view could not read: ${error.message}.`;
  }
  if (error instanceof ApiRequestError) {
    if (error.code === 'not_found' || error.status === 404) {
      return `${route} answered ${error.status} ${error.code}: ${error.apiError.message} Nothing is substituted for it.`;
    }
    return `${route} failed: ${error.apiError.message} (${error.code}, request ${error.requestId}).`;
  }
  if (error instanceof Error) {
    return `${route} could not be reached: ${error.message}.`;
  }
  return `${route} could not be reached and reported no reason.`;
}
