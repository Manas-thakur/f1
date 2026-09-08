import { describe, expect, it } from 'vitest';

import { useSessionStore } from '../state/sessionStore';
import { snapshotEnvelope, estimateEnvelope } from '../test/envelopes';
import { SESSION_SNAPSHOT } from '../test/contractFixtures';
import { SessionStream } from './stream';
import { validateAs, validateEnvelope, bundleSchemaVersion, schemaNames } from './validate';

describe('generated schema bundle', () => {
  it('is the contract revision the types were generated from', () => {
    expect(bundleSchemaVersion()).toBe('1.0');
    expect(schemaNames()).toContain('StreamEnvelope');
    expect(schemaNames()).toContain('SessionSnapshot');
  });
});

describe('validateEnvelope', () => {
  it('accepts a well-formed envelope', () => {
    const result = validateEnvelope(snapshotEnvelope());
    expect(result.ok).toBe(true);
  });

  it('accepts the JSON text form', () => {
    const result = validateEnvelope(JSON.stringify(estimateEnvelope(101, 5)));
    expect(result.ok).toBe(true);
  });

  it('rejects text that is not JSON', () => {
    const result = validateEnvelope('{not json');
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe('not_json');
    }
  });

  it('rejects an envelope missing a required field', () => {
    const { session_id: _dropped, ...rest } = snapshotEnvelope();
    void _dropped;
    const result = validateEnvelope(rest);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe('schema_violation');
      expect(result.message).toContain('session_id');
    }
  });

  it('rejects an envelope whose event type is not in the union', () => {
    const result = validateEnvelope({ ...snapshotEnvelope(), event_type: 'made_up_event' });
    expect(result.ok).toBe(false);
  });

  it('rejects a payload that does not match its event type', () => {
    const result = validateEnvelope({
      ...snapshotEnvelope(),
      event_type: 'heartbeat',
      payload: { event_type: 'heartbeat', server_uptime_s: 'not a number' },
    });
    expect(result.ok).toBe(false);
  });

  it('rejects a negative sequence', () => {
    const result = validateEnvelope({ ...snapshotEnvelope(), sequence: -1 });
    expect(result.ok).toBe(false);
  });

  it('validates other generated models too', () => {
    expect(validateAs('SessionSnapshot', SESSION_SNAPSHOT).ok).toBe(true);
    expect(validateAs('SessionSnapshot', { session_id: 'x' }).ok).toBe(false);
  });
});

describe('an invalid envelope never reaches the reducer', () => {
  it('is counted as rejected and changes no server state', () => {
    const store = useSessionStore.getState();
    store.reset();

    const bridge = {
      applyEnvelope: useSessionStore.getState().applyEnvelope,
      applyRestSnapshot: useSessionStore.getState().applyRestSnapshot,
      recordInvalidEnvelope: useSessionStore.getState().recordInvalidEnvelope,
      setConnection: useSessionStore.getState().setConnection,
      getLastSequence: () => useSessionStore.getState().server.lastSequence,
      isResyncRequired: () => useSessionStore.getState().stream.resyncRequired,
    };
    const stream = new SessionStream({ sessionId: SESSION_SNAPSHOT.session_id, store: bridge });


    stream.handleFrame(
      JSON.stringify({ ...snapshotEnvelope(), session_time_s: 'twelve o clock' }),
    );

    const after = useSessionStore.getState();
    expect(after.server.sessionId).toBeNull();
    expect(after.server.lastSequence).toBe(-1);
    expect(after.stream.rejectedEnvelopes).toBe(1);
    expect(after.stream.rejections.at(-1)?.reason).toBe('schema_invalid');


    stream.handleFrame(JSON.stringify(snapshotEnvelope()));
    expect(useSessionStore.getState().server.sessionId).toBe(SESSION_SNAPSHOT.session_id);
  });
});
