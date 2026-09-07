import type {
  ApiError,
  ChannelQuality,
  ControlLease,
  EstimateQuality,
  ExecutionEvent,
  Provenance,
  Quality,
  Recommendation,
  RuleContext,
  RuntimeCapabilities,
  SessionManifest,
  SessionSnapshot,
  StateEstimate,
  TelemetrySeries,
} from '@contracts';

/** Connection lifecycle of the session WebSocket. */
export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'resyncing'
  | 'reconnecting'
  | 'closed';

export type EnvelopeRejectionReason =
  | 'schema_invalid'
  | 'wrong_session'
  | 'sequence_gap'
  | 'duplicate_sequence'
  | 'stale_estimate_revision'
  | 'estimate_revision_skip'
  | 'stale_recommendation'
  | 'deltas_paused';

export interface EnvelopeRejection {
  readonly reason: EnvelopeRejectionReason;
  readonly eventType: string | null;
  readonly sequence: number | null;
  readonly detail: string;
}

/**
 * Authoritative state received from the server. Nothing in here is ever
 * written optimistically by a UI interaction; only the reducer and an explicit
 * REST snapshot fetch may change it.
 */
export interface ServerState {
  /** Session this store is bound to. Envelopes for any other id are ignored. */
  readonly sessionId: string | null;
  readonly manifest: SessionManifest | null;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly quality: EstimateQuality | null;
  /** Latest per-channel quality, from snapshots and `quality_changed`. */
  readonly channelQuality: readonly ChannelQuality[];
  readonly qualityMessage: string | null;
  readonly capabilities: RuntimeCapabilities | null;
  readonly lease: ControlLease | null;
  /** Session revision, from the snapshot; deltas do not invent one. */
  readonly revision: number;
  readonly lastSequence: number;
  readonly serverTime: string | null;
  readonly sessionTimeS: number;
  readonly status: string;
  /** Keyed `channel` or `channel@car_id`. */
  readonly telemetry: Readonly<Record<string, TelemetrySeries>>;
  /**
   * Session time at which telemetry last actually arrived. A heartbeat never
   * touches this: a heartbeat proves a connection exists, not that data is
   * fresh.
   */
  readonly telemetryFreshAtS: number | null;
  readonly executions: readonly ExecutionEvent[];
  readonly experimentProgress: Readonly<
    Record<string, { status: string; progress: number; detail: string | null }>
  >;
  readonly invalidatedRecommendationIds: readonly string[];
}

/** Stream health. Separate from server state so it can be shown honestly. */
export interface StreamState {
  readonly connection: ConnectionStatus;
  /**
   * False while a resync is outstanding. Deltas are dropped, not queued: the
   * snapshot that ends the resync is authoritative.
   */
  readonly applyingDeltas: boolean;
  readonly resyncRequired: boolean;
  readonly resyncReason: string | null;
  readonly earliestAvailableSequence: number | null;
  readonly resyncCount: number;
  readonly lastHeartbeatAtS: number | null;
  readonly acceptedEnvelopes: number;
  readonly rejectedEnvelopes: number;
  readonly rejections: readonly EnvelopeRejection[];
}

export type Density = 'comfortable' | 'compact';
export type MotionPreference = 'system' | 'reduce';
export type CursorAxis = 'progress_m' | 'session_time_s';

export interface InspectorState {
  readonly open: boolean;
  readonly kind: 'decision' | 'evidence' | 'channel' | 'rule' | null;
  readonly subjectId: string | null;
  /** DOM id of the control that opened it, so focus can be restored. */
  readonly invokerId: string | null;
}

/** Purely local view state. Changing it never changes simulation truth. */
export interface ViewState {
  readonly selectedChannels: readonly string[];
  readonly cursorAxis: CursorAxis;
  /** Shared cursor position, broadcast to every chart panel. */
  readonly cursorValue: number | null;
  readonly inspector: InspectorState;
  readonly density: Density;
  readonly motion: MotionPreference;
  readonly referenceSeriesId: string | null;
}

export interface PendingCommand {
  readonly key: string;
  readonly kind: string;
  readonly idempotencyKey: string;
  readonly expectedRevision: number;
  readonly startedAtMs: number;
}

export interface RequestState {
  readonly inFlight: Readonly<Record<string, PendingCommand>>;
  readonly lastError: (ApiError & { readonly key: string }) | null;
  /** Keys whose last attempt returned 409. The UI must refresh, not retry. */
  readonly conflictedKeys: readonly string[];
}

export interface SessionStoreState {
  readonly server: ServerState;
  readonly stream: StreamState;
  readonly view: ViewState;
  readonly request: RequestState;
}

/** The reducer's slice: server state plus stream health. */
export interface StreamSlice {
  readonly server: ServerState;
  readonly stream: StreamState;
}

export const INITIAL_SERVER_STATE: ServerState = {
  sessionId: null,
  manifest: null,
  estimate: null,
  recommendation: null,
  ruleContext: null,
  quality: null,
  channelQuality: [],
  qualityMessage: null,
  capabilities: null,
  lease: null,
  revision: 0,
  lastSequence: -1,
  serverTime: null,
  sessionTimeS: 0,
  status: 'unknown',
  telemetry: {},
  telemetryFreshAtS: null,
  executions: [],
  experimentProgress: {},
  invalidatedRecommendationIds: [],
};

export const INITIAL_STREAM_STATE: StreamState = {
  connection: 'idle',
  applyingDeltas: true,
  resyncRequired: false,
  resyncReason: null,
  earliestAvailableSequence: null,
  resyncCount: 0,
  lastHeartbeatAtS: null,
  acceptedEnvelopes: 0,
  rejectedEnvelopes: 0,
  rejections: [],
};

export const INITIAL_VIEW_STATE: ViewState = {
  selectedChannels: ['electrical_power_w', 'battery_energy_j', 'speed_mps'],
  cursorAxis: 'progress_m',
  cursorValue: null,
  inspector: { open: false, kind: null, subjectId: null, invokerId: null },
  density: 'comfortable',
  motion: 'system',
  referenceSeriesId: null,
};

export const INITIAL_REQUEST_STATE: RequestState = {
  inFlight: {},
  lastError: null,
  conflictedKeys: [],
};

/** Fields the reducer is allowed to derive but must not invent. */
export interface QualitySummary {
  readonly overall: Quality | null;
  readonly worstChannel: ChannelQuality | null;
  readonly blocking: boolean;
  readonly reason: string | null;
}

export type { Provenance, SessionSnapshot };
