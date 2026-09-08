
import type {
  FlagState,
  Recommendation,
  RecommendationStatus,
  RuleContext,
  SessionMode,
  StateEstimate,
} from '@contracts';

import type { ConnectionStatus } from '@/state/types';

export type DriverState =
  | 'mode-not-permitted'
  | 'safety'
  | 'withdrawn'
  | 'stale'
  | 'instruction'
  | 'completed'
  | 'neutral';


export const SAFETY_FLAGS: readonly FlagState[] = [
  'red',
  'safety_car',
  'virtual_safety_car',
  'chequered',
];


export const APPROVED_STATUSES: ReadonlySet<RecommendationStatus> = new Set<RecommendationStatus>([
  'selected',
  'communicated',
  'executing',
]);

export interface DriverInput {
  readonly mode: SessionMode | null;
  readonly connection: ConnectionStatus;
  
  readonly watchdogExpired: boolean;
  
  readonly blockingQuality: boolean;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly sessionTimeS: number;
}

export interface DriverView {
  readonly state: DriverState;
  
  readonly primary: string;
  
  readonly mark: '■' | '▲' | '●' | '◆' | '×';
  readonly trigger: string | null;
  readonly endCheckpoint: string | null;
  readonly reason: string;
  
  readonly showsInstruction: boolean;
  
  readonly agedContextOnly: boolean;
}

function flagOf(estimate: StateEstimate | null): FlagState | null {
  const context = estimate?.race_context;
  if (context === undefined || context === null) {
    return null;
  }
  if (context.flag_known === false) {
    return null;
  }
  return context.flag_state ?? null;
}

export function deriveDriverView(input: DriverInput): DriverView {
  const { recommendation, sessionTimeS } = input;

  if (input.mode !== null && input.mode !== 'simulation') {
    return {
      state: 'mode-not-permitted',
      primary: 'NOT A SIMULATOR SESSION',
      mark: '×',
      trigger: null,
      endCheckpoint: null,
      reason:
        'This display is simulator-only. The control plane refuses driver actions for any other mode.',
      showsInstruction: false,
      agedContextOnly: false,
    };
  }

  const flag = flagOf(input.estimate);
  if (flag !== null && SAFETY_FLAGS.includes(flag)) {
    return {
      state: 'safety',
      primary: flag.replace(/_/g, ' ').toUpperCase(),
      mark: '×',
      trigger: null,
      endCheckpoint: null,
      reason: 'Safety state overrides every instruction.',
      showsInstruction: false,
      agedContextOnly: false,
    };
  }

  if (recommendation !== null && recommendation.action_code === 'withdraw_advice') {
    return {
      state: 'withdrawn',
      primary: 'NO INSTRUCTION',
      mark: '×',
      trigger: null,
      endCheckpoint: null,
      reason: 'Advice was withdrawn by the control plane.',
      showsInstruction: false,
      agedContextOnly: false,
    };
  }

  const disconnected =
    input.connection === 'closed' ||
    input.connection === 'idle' ||
    input.connection === 'reconnecting';

  if (input.watchdogExpired || disconnected || input.blockingQuality) {
    return {
      state: 'stale',
      primary: 'NO LIVE DATA',
      mark: '×',
      trigger: null,
      endCheckpoint: null,
      reason: input.watchdogExpired
        ? 'No stream update inside the watchdog window. The instruction was cleared locally.'
        : disconnected
          ? 'The session stream is not connected.'
          : 'A source this instruction depends on is stale, missing or invalid.',
      showsInstruction: false,
      agedContextOnly: true,
    };
  }

  if (recommendation !== null) {
    const expired =
      Number.isFinite(recommendation.expires_at_s) && sessionTimeS > recommendation.expires_at_s;

    if (!expired && APPROVED_STATUSES.has(recommendation.status)) {
      return {
        state: 'instruction',
        primary: recommendation.display_text,
        mark: '▲',
        trigger: recommendation.trigger.description,
        endCheckpoint: recommendation.end_condition,
        reason:
          recommendation.status === 'executing'
            ? 'Execution observed.'
            : `Engineer ${recommendation.status}.`,
        showsInstruction: true,
        agedContextOnly: false,
      };
    }

    if (recommendation.status === 'completed') {
      return {
        state: 'completed',
        primary: 'COMPLETE',
        mark: '●',
        trigger: null,
        endCheckpoint: recommendation.end_condition,
        reason: 'The end condition was reached.',
        showsInstruction: false,
        agedContextOnly: false,
      };
    }

    if (expired) {
      return {
        state: 'neutral',
        primary: 'NO INSTRUCTION',
        mark: '■',
        trigger: null,
        endCheckpoint: null,
        reason: 'The last instruction passed its expiry and was cleared.',
        showsInstruction: false,
        agedContextOnly: false,
      };
    }
  }

  return {
    state: 'neutral',
    primary: 'NO INSTRUCTION',
    mark: '■',
    trigger: null,
    endCheckpoint: null,
    reason:
      recommendation === null
        ? 'Nothing has been published for the current state.'
        : 'Nothing has been approved by the engineer.',
    showsInstruction: false,
    agedContextOnly: false,
  };
}

export type EnergyTargetState = 'above' | 'below' | 'unknown';

export interface EnergyTarget {
  readonly state: EnergyTargetState;
  readonly text: string;
  readonly mark: '▲' | '▼' | '?';
}


export function energyTarget(
  estimate: StateEstimate | null,
  recommendation: Recommendation | null,
  ruleContext: RuleContext | null,
): EnergyTarget {
  const current = estimate?.own_car.battery_energy_j.value ?? null;
  const projected = (recommendation?.outcomes ?? [])[0]?.own_energy_j ?? null;
  const floor = ruleContext?.applicable_limits?.battery_energy_min_j ?? null;
  const target = projected ?? floor;

  if (current === null || target === null) {
    return {
      state: 'unknown',
      text: 'TARGET UNKNOWN',
      mark: '?',
    };
  }
  return current >= target
    ? { state: 'above', text: 'ENERGY ABOVE TARGET', mark: '▲' }
    : { state: 'below', text: 'ENERGY BELOW TARGET', mark: '▼' };
}
