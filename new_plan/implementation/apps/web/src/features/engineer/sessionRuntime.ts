/**
 * Session attach / snapshot / stream lifecycle.
 *
 * Shared by the engineer console, the lab, replay and the driver display. It
 * lives under `features/engineer/` because that is the only directory this
 * agent was granted that all four routes can import from; nothing in here is
 * engineer-specific. See `handoffs/A09-A11.md`.
 *
 * Order of operations on mount, and it matters:
 *   1. bind the store to the session id, so any envelope for another session
 *      is rejected rather than blended in;
 *   2. read the REST snapshot, which carries the authoritative revision and
 *      `last_sequence`;
 *   3. open the WebSocket, which resumes from that sequence.
 *
 * Opening the socket first would leave the client applying deltas against a
 * revision it has never seen.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError } from '@contracts';

import { apiClient, type ApiClient } from '@/api/client';
import { toApiError } from '@/api/errors';
import { SessionStream, type StreamStoreBridge } from '@/api/stream';
import { useSessionStore } from '@/state/sessionStore';

export interface SessionRuntimeOptions {
  /** Injectable for tests; defaults to the shared client. */
  readonly client?: ApiClient;
  /** Injectable for tests; defaults to the global WebSocket. */
  readonly socketFactory?: (url: string) => WebSocket;
  /**
   * When false the snapshot is still read but no socket is opened. Used by
   * views that only need a one-shot read, and by tests.
   */
  readonly connect?: boolean;
}

export interface SessionRuntime {
  /** Re-read the REST snapshot and hand it to the store. */
  readonly refresh: () => Promise<void>;
  readonly snapshotError: ApiError | null;
  readonly loading: boolean;
}

/** A bridge that always reads the live store, never a captured snapshot. */
function storeBridge(): StreamStoreBridge {
  return {
    applyEnvelope: (envelope) => useSessionStore.getState().applyEnvelope(envelope),
    applyRestSnapshot: (snapshot) => useSessionStore.getState().applyRestSnapshot(snapshot),
    recordInvalidEnvelope: (detail, eventType) =>
      useSessionStore.getState().recordInvalidEnvelope(detail, eventType ?? null),
    setConnection: (connection) => useSessionStore.getState().setConnection(connection),
    getLastSequence: () => useSessionStore.getState().server.lastSequence,
    isResyncRequired: () => useSessionStore.getState().stream.resyncRequired,
  };
}

export function useSessionRuntime(
  sessionId: string | undefined,
  options: SessionRuntimeOptions = {},
): SessionRuntime {
  const [loading, setLoading] = useState(sessionId !== undefined);
  const [snapshotError, setSnapshotError] = useState<ApiError | null>(null);

  // Options are read through refs so a caller re-rendering with an inline
  // object does not tear the socket down and rebuild it every render.
  const clientRef = useRef<ApiClient>(options.client ?? apiClient);
  clientRef.current = options.client ?? apiClient;
  const socketFactoryRef = useRef<SessionRuntimeOptions['socketFactory']>(options.socketFactory);
  socketFactoryRef.current = options.socketFactory;

  const connect = options.connect ?? true;

  const refresh = useCallback(async () => {
    if (sessionId === undefined) {
      return;
    }
    try {
      const snapshot = await clientRef.current.getSnapshot(sessionId);
      useSessionStore.getState().applyRestSnapshot(snapshot);
      setSnapshotError(null);
    } catch (caught: unknown) {
      setSnapshotError(toApiError(caught, 'session snapshot unavailable'));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (sessionId === undefined) {
      return;
    }
    let cancelled = false;
    let stream: SessionStream | null = null;

    useSessionStore.getState().attachSession(sessionId);
    setLoading(true);

    void (async () => {
      await refresh();
      if (cancelled || !connect) {
        return;
      }
      const factory = socketFactoryRef.current;
      stream = new SessionStream({
        sessionId,
        store: storeBridge(),
        client: clientRef.current,
        ...(factory === undefined ? {} : { socketFactory: factory }),
      });
      stream.connect();
    })();

    return () => {
      cancelled = true;
      stream?.close();
      useSessionStore.getState().detachSession();
    };
  }, [sessionId, connect, refresh]);

  return { refresh, snapshotError, loading };
}
