/**
 * Driver display state precedence.
 *
 * `11_driver_display/TECHNICAL_SPEC.md`:
 *
 *     safety/withdrawal > stale/unavailable > active instruction > completed/neutral
 *
 * Two rules are enforced here rather than in the component, because they are
 * correctness properties and not styling:
 *
 *   - **A pending engineer selection is not approved advice.** The instruction
 *     is shown only for a recommendation the server has already moved to
 *     `selected`, `communicated` or `executing`. A `proposed` recommendation —
 *     including one with a select command in flight — shows nothing.
 *   - **A dead stream clears the instruction.** The watchdog is local and
 *     independent of any server message; a heartbeat is not evidence that
 *     telemetry is fresh, and neither is an open socket.
 */
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

/** Flags that stop everything, whatever the plan said. */
export const SAFETY_FLAGS: readonly FlagState[] = [
  'red',
  'safety_car',
  'virtual_safety_car',
  'chequered',
];

/** Statuses the engineer has actually put behind the instruction. */
export const APPROVED_STATUSES: ReadonlySet<RecommendationStatus> = new Set<RecommendationStatus>([
  'selected',
  'communicated',
  'executing',
]);

export interface DriverInput {
  readonly mode: SessionMode | null;
  readonly connection: ConnectionStatus;
  /** True when the local watchdog has not seen a stream update in time. */
  readonly watchdogExpired: boolean;
  /** True when a contributing source is stale, missing or invalid. */
  readonly blockingQuality: boolean;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly sessionTimeS: number;
}

export interface DriverView {
  readonly state: DriverState;
  /** The one line the driver reads. Never an imperative when unsafe/stale. */
  readonly primary: string;
  /** Geometric mark, so the state does not depend on colour alone. */
  readonly mark: '■' | '▲' | '●' | '◆' | '×';
  readonly trigger: string | null;
  readonly endCheckpoint: string | null;
  readonly reason: string;
  /** True only when an approved, unexpired instruction should be displayed. */
  readonly showsInstruction: boolean;
  /** True when only aged, static vehicle context may be shown. */
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

/**
 * Whether stored energy is above the target the plan or the rule pack sets.
 *
 * Unknown is a first-class answer: a missing floor or a missing sample gives
 * "TARGET UNKNOWN", never a green tick and never a zero.
 */
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
