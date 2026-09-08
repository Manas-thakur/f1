/**
 * Typed error handling for the generated `ErrorCode` union.
 *
 * The control-plane contract says the UI never sees an exception trace. Every
 * failure that reaches a component is one of these, with a code the UI can
 * branch on and a message it may show.
 */
import type { ApiError, ApiErrorResponse, ErrorCode } from '@contracts';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly apiError: ApiError;

  constructor(status: number, apiError: ApiError) {
    super(apiError.message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.apiError = apiError;
  }

  get code(): ErrorCode {
    return this.apiError.code;
  }

  get retryable(): boolean {
    return this.apiError.retryable;
  }

  get requestId(): string {
    return this.apiError.request_id;
  }

  /**
   * A conflict means the decision the operator saw is no longer the current
   * one. The correct response is to refresh the evidence, never to resubmit.
   */
  get isConflict(): boolean {
    return (
      this.status === 409 ||
      this.code === 'stale_revision' ||
      this.code === 'idempotency_conflict'
    );
  }

  /** The recommendation itself is gone; a new snapshot is required. */
  get isRecommendationGone(): boolean {
    return this.code === 'recommendation_expired' || this.code === 'recommendation_invalidated';
  }
}

/** What the operator should be told, per error code. Never a stack trace. */
export const ERROR_GUIDANCE: Record<ErrorCode, string> = {
  stale_revision:
    'The session moved on while this was open. The evidence has been refreshed; review it before deciding again.',
  idempotency_conflict:
    'A different command was already submitted with this key. Reload the session state before retrying.',
  recommendation_expired:
    'This recommendation expired before it was acted on. A newer one may be available.',
  recommendation_invalidated:
    'A rule change invalidated this recommendation. It cannot be selected.',
  capability_unavailable:
    'Required telemetry or rule coverage is unavailable, so this action is not offered.',
  lease_not_held: 'Another operator holds the control lease for this session.',
  mode_not_permitted: 'This action is not permitted in this session mode.',
  not_found: 'The requested record does not exist.',
  validation_failed: 'The request was rejected as invalid. Check the values and try again.',
  persistence_degraded:
    'The server could not durably record this action. It has not been applied.',
  spool_exhausted: 'The server ran out of buffered history. Reload the session.',
  internal: 'The server failed to process this request. Nothing was changed.',
};

const FALLBACK_CODE: ErrorCode = 'internal';

export function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
  );
}

/** Turn any failure — typed, untyped or thrown — into an `ApiError`. */
export function toApiError(value: unknown, fallbackMessage: string): ApiError {
  if (value instanceof ApiRequestError) {
    return value.apiError;
  }
  if (isApiErrorResponse(value)) {
    return {
      code: value.error.code,
      message: value.error.message,
      retryable: value.error.retryable ?? false,
      request_id: value.error.request_id ?? 'unknown',
      ...(value.error.details !== undefined ? { details: value.error.details } : {}),
    };
  }
  return {
    code: FALLBACK_CODE,
    message: value instanceof Error ? value.message : fallbackMessage,
    retryable: false,
    request_id: 'unknown',
  };
}

export function guidanceFor(error: ApiError | null | undefined): string | null {
  if (!error) {
    return null;
  }
  return ERROR_GUIDANCE[error.code] ?? ERROR_GUIDANCE.internal;
}
