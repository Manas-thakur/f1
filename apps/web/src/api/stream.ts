
import type { SessionSnapshot, StreamEnvelope } from '@contracts';

import { apiClient, type ApiClient } from './client';
import { validateEnvelope } from './validate';
import type { ConnectionStatus } from '../state/types';

export interface StreamStoreBridge {
  applyEnvelope: (envelope: StreamEnvelope) => void;
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
  
  readonly socketFactory?: (url: string) => WebSocket;
  readonly reconnectDelayMs?: number;
  
  readonly basePath?: string;
}


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

  private lastResyncSequence: number | null = null;

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
    this.lastResyncSequence = null;
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


  async resync(): Promise<void> {
    if (this.resyncInFlight) {
      return;
    }
    this.resyncInFlight = true;
    this.store.setConnection('resyncing');
    try {
      const snapshot = await this.client.getSnapshot(this.sessionId);
      this.store.applyRestSnapshot(snapshot);


      const stalled = this.lastResyncSequence === snapshot.last_sequence;
      this.lastResyncSequence = snapshot.last_sequence;

      if (this.socket !== null) {
        const socket = this.socket;
        this.socket = null;
        socket.onclose = null;
        socket.close();
      }
      if (!this.closedByUs) {
        if (stalled) {
          this.reconnectTimer = setTimeout(() => this.openSocket(), this.reconnectDelayMs);
        } else {
          this.openSocket();
        }
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
