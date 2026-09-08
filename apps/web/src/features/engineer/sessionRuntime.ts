
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError } from '@contracts';

import { apiClient, type ApiClient } from '@/api/client';
import { toApiError } from '@/api/errors';
import { SessionStream, type StreamStoreBridge } from '@/api/stream';
import { useSessionStore } from '@/state/sessionStore';

export interface SessionRuntimeOptions {
  
  readonly client?: ApiClient;
  
  readonly socketFactory?: (url: string) => WebSocket;
  
  readonly connect?: boolean;
}

export interface SessionRuntime {
  
  readonly refresh: () => Promise<void>;
  readonly snapshotError: ApiError | null;
  readonly loading: boolean;
}


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
