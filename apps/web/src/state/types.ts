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


export interface ServerState {
  
  readonly sessionId: string | null;
  readonly manifest: SessionManifest | null;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly quality: EstimateQuality | null;
  
  readonly channelQuality: readonly ChannelQuality[];
  readonly qualityMessage: string | null;
  readonly capabilities: RuntimeCapabilities | null;
  readonly lease: ControlLease | null;
  
  readonly revision: number;
  readonly lastSequence: number;
  readonly serverTime: string | null;
  readonly sessionTimeS: number;
  readonly status: string;
  
  readonly telemetry: Readonly<Record<string, TelemetrySeries>>;
  
  readonly telemetryFreshAtS: number | null;
  readonly executions: readonly ExecutionEvent[];
  readonly experimentProgress: Readonly<
    Record<string, { status: string; progress: number; detail: string | null }>
  >;
  readonly invalidatedRecommendationIds: readonly string[];
}


export interface StreamState {
  readonly connection: ConnectionStatus;
  
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
  
  readonly invokerId: string | null;
}


export interface ViewState {
  readonly selectedChannels: readonly string[];
  readonly cursorAxis: CursorAxis;
  
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
  
  readonly conflictedKeys: readonly string[];
}

export interface SessionStoreState {
  readonly server: ServerState;
  readonly stream: StreamState;
  readonly view: ViewState;
  readonly request: RequestState;
}


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


export interface QualitySummary {
  readonly overall: Quality | null;
  readonly worstChannel: ChannelQuality | null;
  readonly blocking: boolean;
  readonly reason: string | null;
}

export type { Provenance, SessionSnapshot };
