/**
 * Session WebSocket client.
 *
 * Responsibilities, in order:
 *   1. Resume from `after_sequence` on every connect and reconnect.
 *   2. Validate every frame with Ajv before it reaches the reducer.
 *   3. Fetch a fresh REST snapshot whenever the reducer asks for a resync
 *      (sequence gap, skipped estimate revision, or an explicit
 *      `resync_required` from the server) and resume from its sequence.
 *
 * It holds no state of its own beyond the socket: everything observable lives
 * in the session store, so the UI shows one connection truth.
 */
import type { SessionSnapshot } from '@contracts';

import { apiClient, type ApiClient } from './client';
import { validateEnvelope } from './validate';
import type { ConnectionStatus } from '../state/types';

export interface StreamStoreBridge {
  applyEnvelope: (envelope: import('@contracts').StreamEnvelope) => void;
  applyRestSnapshot: (snapshot: SessionSnapshot) => void;
  recordInvalidEnvelope: (detail: string, eventType?: string | null) => void;
  setConnection: (connection: ConnectionStatus) => void;
  getLastSequence: () => number;
  isResyncRequired: () => boolean;
}

export interface SessionStreamOptions {
  readonly sessionId: string;
  readonly store: StreamStoreBridge;
  readonly client?: ApiClient;
  /** Injectable for tests; defaults to the global WebSocket. */
  readonly socketFactory?: (url: string) => WebSocket;
  readonly reconnectDelayMs?: number;
  /**
   * Base path for the stream. Same origin, so the existing `/api` proxy covers
   * it in development and nginx covers it in production. Kept a constructor
   * argument rather than a constant so a deployment can move it without
   * forking the client.
   */
  readonly basePath?: string;
}

/**
 * The stream endpoint, settled with A08: `/api/v1/sessions/{id}/stream`, same
 * origin. `/ws` stays reserved and unused.
 */
export const STREAM_BASE_PATH = '/api/v1';

export function streamUrl(sessionId: string, afterSequence: number, basePath: string): string {
  const origin = globalThis.location?.origin ?? 'http://localhost';
  const url = new URL(`${basePath}/sessions/${encodeURIComponent(sessionId)}/stream`, origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('after_sequence', String(afterSequence));
  return url.toString();
}

export class SessionStream {
  private socket: WebSocket | null = null;
  private closedByUs = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private resyncInFlight = false;

  private readonly sessionId: string;
  private readonly store: StreamStoreBridge;
  private readonly client: ApiClient;
  private readonly socketFactory: (url: string) => WebSocket;
  private readonly reconnectDelayMs: number;
  private readonly basePath: string;

  constructor(options: SessionStreamOptions) {
    this.sessionId = options.sessionId;
    this.store = options.store;
    this.client = options.client ?? apiClient;
    this.socketFactory = options.socketFactory ?? ((url) => new WebSocket(url));
    this.reconnectDelayMs = options.reconnectDelayMs ?? 2_000;
    this.basePath = options.basePath ?? STREAM_BASE_PATH;
  }

  connect(): void {
    this.closedByUs = false;
    this.openSocket();
  }

  close(): void {
    this.closedByUs = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
    this.store.setConnection('closed');
  }

  private openSocket(): void {
    const after = this.store.getLastSequence();
    const url = streamUrl(this.sessionId, after, this.basePath);
    this.store.setConnection('connecting');
    const socket = this.socketFactory(url);
    this.socket = socket;

    socket.onopen = () => {
      this.store.setConnection('open');
    };
    socket.onmessage = (event: MessageEvent) => {
      this.handleFrame(event.data);
    };
    socket.onerror = () => {
      // A transport error is not evidence about data quality; only the
      // connection status changes.
      this.store.setConnection('reconnecting');
    };
    socket.onclose = () => {
      this.socket = null;
      if (this.closedByUs) {
        this.store.setConnection('closed');
        return;
      }
      this.store.setConnection('reconnecting');
      this.reconnectTimer = setTimeout(() => this.openSocket(), this.reconnectDelayMs);
    };
  }

  /** Exposed for tests: run one frame through validation and the reducer. */
  handleFrame(raw: unknown): void {
    const result = validateEnvelope(typeof raw === 'string' ? raw : String(raw));
    if (!result.ok) {
      this.store.recordInvalidEnvelope(result.message, null);
      return;
    }
    this.store.applyEnvelope(result.value);
    if (this.store.isResyncRequired()) {
      void this.resync();
    }
  }

  /** Fetch a snapshot and resume the stream from its sequence. */
  async resync(): Promise<void> {
    if (this.resyncInFlight) {
      return;
    }
    this.resyncInFlight = true;
    this.store.setConnection('resyncing');
    try {
      const snapshot = await this.client.getSnapshot(this.sessionId);
      this.store.applyRestSnapshot(snapshot);
      // Reopen from the snapshot's sequence so the server replays only what we
      // are missing.
      if (this.socket !== null) {
        const socket = this.socket;
        this.socket = null;
        socket.onclose = null;
        socket.close();
      }
      if (!this.closedByUs) {
        this.openSocket();
      }
    } catch {
      this.store.setConnection('reconnecting');
      if (!this.closedByUs) {
        this.reconnectTimer = setTimeout(() => void this.resync(), this.reconnectDelayMs);
      }
    } finally {
      this.resyncInFlight = false;
    }
  }
}
