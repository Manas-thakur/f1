/**
 * Command submission.
 *
 * Three properties this module exists to guarantee:
 *   1. A command in flight blocks a duplicate submission of the same key.
 *   2. Every command carries an `Idempotency-Key` and an `expected_revision`.
 *   3. A 409 refreshes the evidence. It never silently retries a stale
 *      decision, and it never optimistically marks a recommendation selected.
 */
import type { ApiError } from '@contracts';

import { newIdempotencyKey } from './client';
import { ApiRequestError, toApiError } from './errors';

export interface CommandStoreBridge {
  beginRequest: (input: {
    key: string;
    kind: string;
    idempotencyKey: string;
    expectedRevision: number;
  }) => boolean;
  settleRequest: (key: string) => void;
  failRequest: (key: string, error: ApiError, conflict: boolean) => void;
}

export type CommandOutcome<T> =
  | { readonly status: 'ok'; readonly value: T }
  | { readonly status: 'duplicate_suppressed' }
  | { readonly status: 'conflict'; readonly error: ApiError }
  | { readonly status: 'error'; readonly error: ApiError };

export interface RunCommandInput<T> {
  readonly key: string;
  readonly kind: string;
  readonly expectedRevision: number;
  readonly idempotencyKey?: string;
  /** Performs the HTTP call. Called at most once per `runCommand`. */
  readonly send: (idempotencyKey: string) => Promise<T>;
  /**
   * Invoked on a 409 so the caller can refetch the snapshot / evidence.
   * It is the only reaction to a conflict: there is no retry path here.
   */
  readonly onConflict?: (error: ApiError) => void | Promise<void>;
}

/**
 * Submit one command. Never throws: the outcome is returned so that callers
 * cannot accidentally turn a conflict into an unhandled rejection and a retry.
 */
export async function runCommand<T>(
  store: CommandStoreBridge,
  input: RunCommandInput<T>,
): Promise<CommandOutcome<T>> {
  const idempotencyKey = input.idempotencyKey ?? newIdempotencyKey();
  const admitted = store.beginRequest({
    key: input.key,
    kind: input.kind,
    idempotencyKey,
    expectedRevision: input.expectedRevision,
  });
  if (!admitted) {
    return { status: 'duplicate_suppressed' };
  }

  try {
    const value = await input.send(idempotencyKey);
    store.settleRequest(input.key);
    return { status: 'ok', value };
  } catch (caught: unknown) {
    const conflict = caught instanceof ApiRequestError && caught.isConflict;
    const error = toApiError(caught, 'command failed');
    store.failRequest(input.key, error, conflict);
    if (conflict) {
      await input.onConflict?.(error);
      return { status: 'conflict', error };
    }
    return { status: 'error', error };
  }
}

/** Stable request keys, so two panels acting on the same object collide. */
export const commandKeys = {
  sessionCommand: (sessionId: string, kind: string) => `session:${sessionId}:command:${kind}`,
  recommendationAction: (recommendationId: string, action: string) =>
    `recommendation:${recommendationId}:${action}`,
  driverAction: (sessionId: string) => `session:${sessionId}:driver-action`,
  lease: (sessionId: string) => `session:${sessionId}:lease`,
} as const;
