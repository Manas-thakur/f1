/**
 * Operator actions on a recommendation.
 *
 * Four properties this hook exists to hold:
 *
 *  1. **Selection never actuates.** `select` posts to the recommendation
 *     actions route only. The simulator driver-action endpoint is not called
 *     from here, and an end-to-end test asserts no such request is issued.
 *  2. **Nothing is optimistically marked selected.** On success the hook
 *     re-reads the authoritative snapshot; it never writes a status into the
 *     store. The store has no action that would let it.
 *  3. **A 409 refreshes the evidence.** `runCommand` reports the conflict and
 *     calls `onConflict`, which re-reads the snapshot and reopens the evidence
 *     for the decision. There is no retry path.
 *  4. **`mark_communicated` is a separate action**, and so is the observed
 *     execution, which is not an operator action at all.
 */
import { useCallback, useState } from 'react';
import type { ApiError, OperatorAction, Recommendation } from '@contracts';

import { apiClient, type ApiClient } from '@/api/client';
import { commandKeys, runCommand } from '@/api/commands';
import { guidanceFor } from '@/api/errors';
import { useSessionStore } from '@/state/sessionStore';
import { CONSOLE_OPERATOR_ID } from './operator';

export interface ActionOutcome {
  readonly action: OperatorAction;
  readonly status: 'ok' | 'conflict' | 'error' | 'duplicate_suppressed';
  readonly message: string;
  readonly error: ApiError | null;
  /** The status the server reported after applying the action. */
  readonly resultingStatus: string | null;
}

export interface UseRecommendationActionsOptions {
  readonly sessionId: string;
  readonly recommendation: Recommendation | null;
  readonly expectedRevision: number;
  readonly client?: ApiClient;
  /** Re-read the snapshot. Called after success and after a conflict. */
  readonly refresh: () => Promise<void> | void;
  /** Called on a conflict so the caller can open the evidence inspector. */
  readonly onConflict?: (error: ApiError) => void;
}

export interface RecommendationActions {
  readonly submit: (action: OperatorAction, reason?: string) => Promise<void>;
  readonly pendingAction: OperatorAction | null;
  readonly outcome: ActionOutcome | null;
  readonly clearOutcome: () => void;
}

export function useRecommendationActions({
  sessionId,
  recommendation,
  expectedRevision,
  client = apiClient,
  refresh,
  onConflict,
}: UseRecommendationActionsOptions): RecommendationActions {
  const [pendingAction, setPendingAction] = useState<OperatorAction | null>(null);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(null);

  const submit = useCallback(
    async (action: OperatorAction, reason?: string) => {
      if (recommendation === null) {
        return;
      }
      const recommendationId = recommendation.id;
      setPendingAction(action);
      setOutcome(null);

      const result = await runCommand(useSessionStore.getState(), {
        key: commandKeys.recommendationAction(recommendationId, action),
        kind: `recommendation:${action}`,
        expectedRevision,
        send: (idempotencyKey) =>
          client.sendRecommendationAction(
            sessionId,
            recommendationId,
            {
              action,
              expected_revision: expectedRevision,
              operator_id: CONSOLE_OPERATOR_ID,
              ...(reason === undefined || reason === '' ? {} : { reason }),
            },
            { idempotencyKey },
          ),
        onConflict: async (error) => {
          // The decision the operator was looking at is no longer current.
          // Re-read it; never resubmit.
          await refresh();
          onConflict?.(error);
        },
      });

      setPendingAction(null);

      if (result.status === 'ok') {
        // The server acknowledged. Re-read the authoritative snapshot rather
        // than writing the returned status into the store from here.
        await refresh();
        setOutcome({
          action,
          status: 'ok',
          message: `Server acknowledged ${action.replace('_', ' ')}; status is now "${result.value.recommendation.status}".`,
          error: null,
          resultingStatus: result.value.recommendation.status,
        });
        return;
      }

      if (result.status === 'duplicate_suppressed') {
        setOutcome({
          action,
          status: 'duplicate_suppressed',
          message: 'A command with this key is already in flight. It was not sent twice.',
          error: null,
          resultingStatus: null,
        });
        return;
      }

      setOutcome({
        action,
        status: result.status,
        message: `${result.error.message} ${guidanceFor(result.error) ?? ''} (request ${result.error.request_id})`.trim(),
        error: result.error,
        resultingStatus: null,
      });
    },
    [client, expectedRevision, onConflict, recommendation, refresh, sessionId],
  );

  return { submit, pendingAction, outcome, clearOutcome: () => setOutcome(null) };
}
