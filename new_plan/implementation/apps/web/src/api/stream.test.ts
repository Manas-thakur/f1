import { describe, expect, it, vi } from 'vitest';

import { useSessionStore } from '../state/sessionStore';
import { SESSION_SNAPSHOT } from '../test/contractFixtures';
import { estimateEnvelope, heartbeatEnvelope, snapshotEnvelope } from '../test/envelopes';
import { ApiClient } from './client';
import { SessionStream, STREAM_BASE_PATH, streamUrl } from './stream';

class FakeSocket {
  static instances: FakeSocket[] = [];
  readonly url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.onclose?.();
  }

  deliver(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

function bridge() {
  return {
    applyEnvelope: (envelope: Parameters<ReturnType<typeof useSessionStore.getState>['applyEnvelope']>[0]) =>
      useSessionStore.getState().applyEnvelope(envelope),
    applyRestSnapshot: (snapshot: Parameters<ReturnType<typeof useSessionStore.getState>['applyRestSnapshot']>[0]) =>
      useSessionStore.getState().applyRestSnapshot(snapshot),
    recordInvalidEnvelope: (detail: string, eventType?: string | null) =>
      useSessionStore.getState().recordInvalidEnvelope(detail, eventType),
    setConnection: (connection: Parameters<ReturnType<typeof useSessionStore.getState>['setConnection']>[0]) =>
      useSessionStore.getState().setConnection(connection),
    getLastSequence: () => useSessionStore.getState().server.lastSequence,
    isResyncRequired: () => useSessionStore.getState().stream.resyncRequired,
  };
}

function makeStream(client: ApiClient) {
  FakeSocket.instances = [];
  return new SessionStream({
    sessionId: SESSION_SNAPSHOT.session_id,
    store: bridge(),
    client,
    socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    reconnectDelayMs: 1,
  });
}

function snapshotClient(getSnapshot = vi.fn(async () => SESSION_SNAPSHOT)): {
  client: ApiClient;
  getSnapshot: typeof getSnapshot;
} {
  const client = new ApiClient();
  // Replace only the one method the stream uses.
  (client as unknown as { getSnapshot: unknown }).getSnapshot = getSnapshot;
  return { client, getSnapshot };
}

describe('streamUrl', () => {
  it('defaults to the settled same-origin control-plane path', () => {
    expect(STREAM_BASE_PATH).toBe('/api/v1');
  });

  it('resumes from the last applied sequence on a ws origin', () => {
    const url = streamUrl('abc def', 128, STREAM_BASE_PATH);
    expect(url).toContain('/api/v1/sessions/abc%20def/stream');
    expect(url).toContain('after_sequence=128');
    expect(url.startsWith('ws://') || url.startsWith('wss://')).toBe(true);
  });

  it('still honours an explicit base path, so a deployment can move it', () => {
    expect(streamUrl('s1', 0, '/ws/v1')).toContain('/ws/v1/sessions/s1/stream');
  });
});

describe('SessionStream', () => {
  it('opens with after_sequence=-1 before any snapshot, and reopens from the snapshot sequence', async () => {
    const { client } = snapshotClient();
    const stream = makeStream(client);
    stream.connect();

    expect(FakeSocket.instances[0]?.url).toContain('after_sequence=-1');
    FakeSocket.instances[0]?.deliver(snapshotEnvelope());
    expect(useSessionStore.getState().server.lastSequence).toBe(100);

    stream.close();
    stream.connect();
    expect(FakeSocket.instances.at(-1)?.url).toContain('after_sequence=100');
  });

  it('fetches a snapshot and resumes when a sequence gap forces a resync', async () => {
    const { client, getSnapshot } = snapshotClient();
    const stream = makeStream(client);
    stream.connect();

    const socket = FakeSocket.instances[0] as FakeSocket;
    socket.deliver(snapshotEnvelope());
    // Snapshot ended at 100; the next delta claims 102.
    socket.deliver(estimateEnvelope(102, 5));

    expect(useSessionStore.getState().stream.resyncRequired).toBe(true);
    await vi.waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(1));
    await vi.waitFor(() =>
      expect(useSessionStore.getState().stream.resyncRequired).toBe(false),
    );
    expect(useSessionStore.getState().stream.applyingDeltas).toBe(true);
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
    expect(FakeSocket.instances.at(-1)?.url).toContain('after_sequence=100');

    stream.close();
  });

  it('counts a schema-invalid frame without touching server state', () => {
    const { client } = snapshotClient();
    const stream = makeStream(client);
    stream.connect();
    const socket = FakeSocket.instances[0] as FakeSocket;

    socket.deliver({ nonsense: true });
    expect(useSessionStore.getState().stream.rejectedEnvelopes).toBe(1);
    expect(useSessionStore.getState().server.sessionId).toBeNull();

    stream.close();
  });

  it('does not resync on a heartbeat, however far out of sequence', async () => {
    const { client, getSnapshot } = snapshotClient();
    const stream = makeStream(client);
    stream.connect();
    const socket = FakeSocket.instances[0] as FakeSocket;
    socket.deliver(snapshotEnvelope());
    socket.deliver(heartbeatEnvelope(50_000));

    expect(useSessionStore.getState().stream.resyncRequired).toBe(false);
    expect(getSnapshot).not.toHaveBeenCalled();
    stream.close();
  });

  it('reports closed after an explicit close', () => {
    const { client } = snapshotClient();
    const stream = makeStream(client);
    stream.connect();
    stream.close();
    expect(useSessionStore.getState().stream.connection).toBe('closed');
  });
});
