
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
  
  readonly send: (idempotencyKey: string) => Promise<T>;
  
  readonly onConflict?: (error: ApiError) => void | Promise<void>;
}


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


export const commandKeys = {
  sessionCommand: (sessionId: string, kind: string) => `session:${sessionId}:command:${kind}`,
  recommendationAction: (recommendationId: string, action: string) =>
    `recommendation:${recommendationId}:${action}`,
  driverAction: (sessionId: string) => `session:${sessionId}:driver-action`,
  lease: (sessionId: string) => `session:${sessionId}:lease`,
} as const;
