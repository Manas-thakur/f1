/**
 * The one shared session store.
 *
 * Three slices that never bleed into each other:
 *   server  — authoritative, written only by the reducer or a snapshot fetch
 *   view    — local presentation choices; changing them changes no truth
 *   request — commands in flight, their idempotency keys and expected revisions
 *
 * A09/A10/A11 build on the selectors exported from `selectors.ts`. They should
 * not reach into `useSessionStore.getState().server` and mutate it.
 */
import { create } from 'zustand';
import type { ApiError, SessionSnapshot, StreamEnvelope } from '@contracts';

import { applySnapshot, reduceStream } from './streamReducer';
import {
  INITIAL_REQUEST_STATE,
  INITIAL_SERVER_STATE,
  INITIAL_STREAM_STATE,
  INITIAL_VIEW_STATE,
  type ConnectionStatus,
  type CursorAxis,
  type Density,
  type EnvelopeRejection,
  type InspectorState,
  type MotionPreference,
  type SessionStoreState,
  type StreamSlice,
} from './types';

export interface SessionStoreActions {
  /** Bind the store to a session id and clear everything else. */
  attachSession: (sessionId: string) => void;
  detachSession: () => void;

  /** Feed one already-validated envelope through the reducer. */
  applyEnvelope: (envelope: StreamEnvelope) => void;
  /** Apply a snapshot fetched over REST (the end of a resync). */
  applyRestSnapshot: (snapshot: SessionSnapshot) => void;
  /** Record an envelope that failed Ajv validation. It is never applied. */
  recordInvalidEnvelope: (detail: string, eventType?: string | null) => void;
  setConnection: (connection: ConnectionStatus) => void;

  setSelectedChannels: (channels: readonly string[]) => void;
  toggleChannel: (channel: string) => void;
  setCursor: (value: number | null) => void;
  setCursorAxis: (axis: CursorAxis) => void;
  setReferenceSeries: (seriesId: string | null) => void;
  openInspector: (kind: NonNullable<InspectorState['kind']>, subjectId: string, invokerId: string | null) => void;
  closeInspector: () => void;
  setDensity: (density: Density) => void;
  setMotion: (motion: MotionPreference) => void;

  /**
   * Register a command as in flight.
   * Returns false when a command with the same key is already pending, which
   * is how duplicate submission is prevented.
   */
  beginRequest: (input: {
    key: string;
    kind: string;
    idempotencyKey: string;
    expectedRevision: number;
  }) => boolean;
  settleRequest: (key: string) => void;
  failRequest: (key: string, error: ApiError, conflict: boolean) => void;
  clearRequestError: () => void;
  reset: () => void;
}

export type SessionStore = SessionStoreState & SessionStoreActions;

function initialState(): SessionStoreState {
  return {
    server: INITIAL_SERVER_STATE,
    stream: INITIAL_STREAM_STATE,
    view: INITIAL_VIEW_STATE,
    request: INITIAL_REQUEST_STATE,
  };
}

export const createSessionStore = () =>
  create<SessionStore>()((set, get) => ({
    ...initialState(),

    attachSession: (sessionId) =>
      set(() => ({
        server: { ...INITIAL_SERVER_STATE, sessionId },
        stream: { ...INITIAL_STREAM_STATE, connection: 'connecting' },
      })),

    detachSession: () =>
      set(() => ({ server: INITIAL_SERVER_STATE, stream: INITIAL_STREAM_STATE })),

    applyEnvelope: (envelope) =>
      set((state) => {
        const slice: StreamSlice = { server: state.server, stream: state.stream };
        const next = reduceStream(slice, envelope);
        return next === slice ? {} : { server: next.server, stream: next.stream };
      }),

    applyRestSnapshot: (snapshot) =>
      set((state) => {
        const slice: StreamSlice = { server: state.server, stream: state.stream };
        const next = applySnapshot(slice, snapshot);
        return { server: next.server, stream: { ...next.stream, connection: 'open' } };
      }),

    recordInvalidEnvelope: (detail, eventType = null) =>
      set((state) => {
        const rejection: EnvelopeRejection = {
          reason: 'schema_invalid',
          eventType,
          sequence: null,
          detail,
        };
        return {
          stream: {
            ...state.stream,
            rejectedEnvelopes: state.stream.rejectedEnvelopes + 1,
            rejections: [...state.stream.rejections, rejection].slice(-25),
          },
        };
      }),

    setConnection: (connection) => set((state) => ({ stream: { ...state.stream, connection } })),

    setSelectedChannels: (channels) =>
      set((state) => ({ view: { ...state.view, selectedChannels: [...channels] } })),

    toggleChannel: (channelName) =>
      set((state) => {
        const selected = state.view.selectedChannels;
        const next = selected.includes(channelName)
          ? selected.filter((c) => c !== channelName)
          : [...selected, channelName];
        return { view: { ...state.view, selectedChannels: next } };
      }),

    setCursor: (value) => set((state) => ({ view: { ...state.view, cursorValue: value } })),

    setCursorAxis: (axis) =>
      set((state) => ({ view: { ...state.view, cursorAxis: axis, cursorValue: null } })),

    setReferenceSeries: (seriesId) =>
      set((state) => ({ view: { ...state.view, referenceSeriesId: seriesId } })),

    openInspector: (kind, subjectId, invokerId) =>
      set((state) => ({
        view: { ...state.view, inspector: { open: true, kind, subjectId, invokerId } },
      })),

    closeInspector: () =>
      set((state) => ({
        view: {
          ...state.view,
          inspector: { open: false, kind: null, subjectId: null, invokerId: null },
        },
      })),

    setDensity: (density) => set((state) => ({ view: { ...state.view, density } })),
    setMotion: (motion) => set((state) => ({ view: { ...state.view, motion } })),

    beginRequest: ({ key, kind, idempotencyKey, expectedRevision }) => {
      if (get().request.inFlight[key] !== undefined) {
        return false;
      }
      set((state) => ({
        request: {
          ...state.request,
          inFlight: {
            ...state.request.inFlight,
            [key]: { key, kind, idempotencyKey, expectedRevision, startedAtMs: Date.now() },
          },
          conflictedKeys: state.request.conflictedKeys.filter((k) => k !== key),
        },
      }));
      return true;
    },

    settleRequest: (key) =>
      set((state) => {
        const { [key]: _removed, ...rest } = state.request.inFlight;
        void _removed;
        return { request: { ...state.request, inFlight: rest } };
      }),

    failRequest: (key, error, conflict) =>
      set((state) => {
        const { [key]: _removed, ...rest } = state.request.inFlight;
        void _removed;
        return {
          request: {
            inFlight: rest,
            lastError: { ...error, key },
            conflictedKeys: conflict
              ? [...new Set([...state.request.conflictedKeys, key])]
              : state.request.conflictedKeys,
          },
        };
      }),

    clearRequestError: () => set((state) => ({ request: { ...state.request, lastError: null } })),

    reset: () => set(() => initialState()),
  }));

/** The application-wide store instance. */
export const useSessionStore = createSessionStore();
