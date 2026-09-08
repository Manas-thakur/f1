/**
 * The engineer console's state machine, as a pure function.
 *
 * `09_engineer_console/TECHNICAL_SPEC.md` names fourteen states the console
 * must implement. They are not one axis: "the feed is stale" and "the planner
 * timed out" can be true at once, and a stale-source warning is explicitly
 * independent of the connection state. So the derivation produces two axes
 * plus the single headline the banner shows, and every one of the fourteen
 * names is reachable and asserted in `lifecycle.test.ts`.
 *
 * Nothing here writes to the store. Local expiry is a *display* judgement: it
 * removes the selectable action immediately, and says the server has not yet
 * moved the status. It never rewrites `recommendation.status`.
 */
import type {
  Quality,
  Recommendation,
  RuleContext,
  RuntimeCapabilities,
  StateEstimate,
} from '@contracts';

import { isBlockingQuality } from '@/contracts/units';
import type { ConnectionStatus, QualitySummary } from '@/state/types';

export type FeedState = 'disconnected' | 'connecting' | 'healthy' | 'degraded' | 'stale';

export type AdviceState =
  | 'missing-energy'
  | 'solver-timeout'
  | 'no-feasible-plan'
  | 'rule-unknown'
  | 'no-recommendation'
  | 'selected-pending'
  | 'executing'
  | 'completed'
  | 'expired'
  | 'active';

/** The fourteen names the specification lists. */
export type ConsoleState = FeedState | Exclude<AdviceState, 'active'>;

export interface ConsoleStatusInput {
  readonly connection: ConnectionStatus;
  readonly resyncRequired: boolean;
  readonly hasSnapshot: boolean;
  readonly quality: QualitySummary;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly capabilities: RuntimeCapabilities | null;
  readonly sessionTimeS: number;
  /** A select/communicate/reject command for this recommendation is in flight. */
  readonly actionPending: boolean;
}

export interface ConsoleStatus {
  readonly feed: FeedState;
  readonly advice: AdviceState;
  readonly headline: ConsoleState;
  /** True when the recommendation may be selected right now. */
  readonly selectable: boolean;
  /** Why not, when `selectable` is false. Always set in that case. */
  readonly blockedReason: string | null;
  /** The artefact a useful empty state should name, when one is missing. */
  readonly missingArtefact: string | null;
  readonly heading: string;
  readonly detail: string;
  /** True once the recommendation's own expiry has passed in session time. */
  readonly expiredLocally: boolean;
}

const TERMINAL_STATUSES = new Set(['expired', 'invalidated', 'rejected']);

function ownEnergyUnavailable(
  estimate: StateEstimate | null,
  capabilities: RuntimeCapabilities | null,
): boolean {
  if (capabilities?.own_energy === 'unavailable') {
    return true;
  }
  if (estimate === null) {
    return false;
  }
  if (estimate.quality.own_energy_capability === false) {
    return true;
  }
  return estimate.own_car.battery_energy_j.value === null;
}

/**
 * A rule condition the pack could not resolve, an unknown eligibility, or an
 * empty admissible-profile set. Any of the three means the console cannot say
 * which actions are legal, which is not the same as saying none are.
 */
export function ruleCoverageUnknown(ruleContext: RuleContext | null): boolean {
  if (ruleContext === null) {
    return false;
  }
  if ((ruleContext.unknown_conditions ?? []).length > 0) {
    return true;
  }
  if (ruleContext.eligibility === 'unknown') {
    return true;
  }
  return (ruleContext.admissible_profiles ?? []).length === 0;
}

function withdrawalAdvice(
  recommendation: Recommendation,
  ruleContext: RuleContext | null,
  capabilities: RuntimeCapabilities | null,
  estimate: StateEstimate | null,
): AdviceState {
  const reasons = new Set(recommendation.reason_codes ?? []);
  if (reasons.has('solver_timeout') || capabilities?.solver === 'unavailable') {
    return 'solver-timeout';
  }
  if (reasons.has('own_energy_unavailable') || ownEnergyUnavailable(estimate, capabilities)) {
    return 'missing-energy';
  }
  if (reasons.has('eligibility_unknown') || ruleCoverageUnknown(ruleContext)) {
    return 'rule-unknown';
  }
  return 'no-feasible-plan';
}

function feedStateOf(input: ConsoleStatusInput): FeedState {
  const { connection, resyncRequired, hasSnapshot, quality } = input;
  if (!hasSnapshot && (connection === 'idle' || connection === 'closed')) {
    return 'disconnected';
  }
  if (connection === 'idle' || connection === 'closed') {
    return 'disconnected';
  }
  if (connection === 'connecting' || connection === 'reconnecting' || connection === 'resyncing') {
    return 'connecting';
  }
  if (resyncRequired) {
    return 'connecting';
  }
  // Independent of the connection: a healthy socket carrying stale samples is
  // still a stale source.
  if (quality.blocking) {
    return 'stale';
  }
  if (quality.overall === 'degraded') {
    return 'degraded';
  }
  return 'healthy';
}

const HEADINGS: Record<ConsoleState, string> = {
  disconnected: 'Stream disconnected',
  connecting: 'Stream connecting',
  healthy: 'Recommendation available',
  degraded: 'Recommendation available on degraded sources',
  stale: 'Source is stale',
  'missing-energy': 'Own stored energy unavailable',
  'solver-timeout': 'Planner did not return in time',
  'no-feasible-plan': 'No feasible plan',
  'rule-unknown': 'Rule coverage unknown',
  'no-recommendation': 'No recommendation',
  'selected-pending': 'Selection awaiting the server',
  executing: 'Execution observed',
  completed: 'Decision completed',
  expired: 'Recommendation no longer actionable',
};

const MISSING_ARTEFACT: Partial<Record<ConsoleState, string>> = {
  disconnected: 'session stream',
  connecting: 'session snapshot',
  stale: 'fresh telemetry samples',
  'missing-energy': 'own battery_energy_j samples',
  'solver-timeout': 'planning result within the decision deadline',
  'no-feasible-plan': 'a feasible candidate plan',
  'rule-unknown': 'resolved rule conditions for this progress point',
  'no-recommendation': 'recommendation',
};

export function deriveConsoleStatus(input: ConsoleStatusInput): ConsoleStatus {
  const feed = feedStateOf(input);
  const { recommendation, ruleContext, capabilities, estimate, sessionTimeS } = input;

  const expiredLocally =
    recommendation !== null && Number.isFinite(recommendation.expires_at_s)
      ? sessionTimeS > recommendation.expires_at_s
      : false;

  let advice: AdviceState;
  if (recommendation === null) {
    if (ownEnergyUnavailable(estimate, capabilities)) {
      advice = 'missing-energy';
    } else if (ruleCoverageUnknown(ruleContext)) {
      advice = 'rule-unknown';
    } else {
      advice = 'no-recommendation';
    }
  } else if (TERMINAL_STATUSES.has(recommendation.status) || expiredLocally) {
    advice = 'expired';
  } else if (recommendation.action_code === 'withdraw_advice') {
    advice = withdrawalAdvice(recommendation, ruleContext, capabilities, estimate);
  } else if (input.actionPending) {
    advice = 'selected-pending';
  } else if (recommendation.status === 'executing') {
    advice = 'executing';
  } else if (recommendation.status === 'completed') {
    advice = 'completed';
  } else {
    advice = 'active';
  }

  let headline: ConsoleState;
  if (feed === 'disconnected' || feed === 'connecting' || feed === 'stale') {
    headline = feed;
  } else if (advice !== 'active') {
    headline = advice;
  } else {
    headline = feed;
  }

  const selectable =
    feed !== 'disconnected' &&
    feed !== 'connecting' &&
    feed !== 'stale' &&
    recommendation !== null &&
    recommendation.status === 'proposed' &&
    recommendation.action_code !== 'withdraw_advice' &&
    !expiredLocally &&
    !input.actionPending;

  let blockedReason: string | null = null;
  if (!selectable) {
    if (feed === 'disconnected') {
      blockedReason = 'The session stream is not connected, so the displayed decision may be old.';
    } else if (feed === 'connecting') {
      blockedReason = 'The stream is still resynchronising with the server.';
    } else if (feed === 'stale') {
      blockedReason = input.quality.reason ?? 'A required source is stale, missing or invalid.';
    } else if (recommendation === null) {
      blockedReason = 'There is no recommendation to select.';
    } else if (recommendation.action_code === 'withdraw_advice') {
      blockedReason = 'Advice is withdrawn; there is no selectable action.';
    } else if (expiredLocally) {
      blockedReason = `This recommendation expired at ${recommendation.expires_at_s.toFixed(1)} s; session time is ${sessionTimeS.toFixed(1)} s.`;
    } else if (input.actionPending) {
      blockedReason = 'A command for this recommendation is already in flight.';
    } else {
      blockedReason = `Status is "${recommendation.status}"; only a proposed recommendation can be selected.`;
    }
  }

  return {
    feed,
    advice,
    headline,
    selectable,
    blockedReason,
    missingArtefact: MISSING_ARTEFACT[headline] ?? null,
    heading: HEADINGS[headline],
    detail: detailFor(headline, input, expiredLocally),
    expiredLocally,
  };
}

function detailFor(
  headline: ConsoleState,
  input: ConsoleStatusInput,
  expiredLocally: boolean,
): string {
  const rec = input.recommendation;
  switch (headline) {
    case 'disconnected':
      return 'No session stream is open. Nothing below is being updated.';
    case 'connecting':
      return input.resyncRequired
        ? 'A sequence gap was detected. Deltas are paused until a fresh snapshot arrives.'
        : 'Waiting for the first snapshot from the control plane.';
    case 'stale':
      return (
        input.quality.reason ??
        'A source this decision depends on stopped updating. Time-sensitive actions are disabled.'
      );
    case 'missing-energy':
      return 'Own stored energy is not available, so no energy-limited plan can be produced or checked.';
    case 'solver-timeout':
      return 'The planner exceeded its decision deadline. No plan was accepted for this state revision.';
    case 'no-feasible-plan':
      return 'Every candidate violated a hard constraint, so advice was withdrawn rather than relaxed.';
    case 'rule-unknown':
      return unknownRuleDetail(input.ruleContext);
    case 'no-recommendation':
      return 'The control plane has not published a recommendation for the current state revision.';
    case 'selected-pending':
      return 'The command has been sent. The status changes only when the server acknowledges it.';
    case 'executing':
      return 'A driver action matching this decision has been observed.';
    case 'completed':
      return 'The end condition was reached and the outcome recorded.';
    case 'expired':
      return expiredLocally && rec !== null && !TERMINAL_STATUSES.has(rec.status)
        ? `Expiry ${rec.expires_at_s.toFixed(1)} s has passed in session time; the server has not yet published the new status.`
        : 'This recommendation can no longer be acted on.';
    case 'degraded':
      return input.quality.reason ?? 'At least one contributing source is degraded.';
    case 'healthy':
    default:
      return 'Sources are within their expected update periods.';
  }
}

function unknownRuleDetail(ruleContext: RuleContext | null): string {
  if (ruleContext === null) {
    return 'No resolved rule context is available for this session.';
  }
  const unknown = ruleContext.unknown_conditions ?? [];
  if (unknown.length > 0) {
    return `The loaded pack could not resolve: ${unknown.join(', ')}.`;
  }
  if (ruleContext.eligibility === 'unknown') {
    return 'Overtake eligibility is unknown until a detection line has been crossed, so advice is suppressed.';
  }
  return 'The resolved rule context admits no deployment profile, so no action can be proposed.';
}

/** Quality of the worst contributing channel, for a compact strip readout. */
export function worstQualityText(quality: Quality | null): string {
  if (quality === null) {
    return 'unknown';
  }
  return isBlockingQuality(quality) ? `${quality} (blocking)` : quality;
}
