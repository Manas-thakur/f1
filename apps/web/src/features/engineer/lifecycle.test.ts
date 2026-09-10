import { describe, expect, it } from 'vitest';

import { deriveConsoleStatus, ruleCoverageUnknown, type ConsoleStatusInput } from './lifecycle';
import {
  ESTIMATE,
  RECOMMENDATION_FIXTURE,
  RULES,
  estimateWithoutEnergy,
  qualitySummary,
  recommendation,
  ruleContext,
} from '@/test/testFixtures';

function input(overrides: Partial<ConsoleStatusInput> = {}): ConsoleStatusInput {
  return {
    connection: 'open',
    resyncRequired: false,
    hasSnapshot: true,
    quality: qualitySummary(),
    estimate: ESTIMATE,
    recommendation: RECOMMENDATION_FIXTURE,
    ruleContext: RULES,
    capabilities: { own_energy: 'available', solver: 'available' },
    sessionTimeS: 12.5,
    actionPending: false,
    ...overrides,
  };
}

describe('every state the specification names is reachable', () => {
  it('disconnected: the socket is closed', () => {
    expect(deriveConsoleStatus(input({ connection: 'closed' })).headline).toBe('disconnected');
  });

  it('connecting: the socket is opening', () => {
    expect(deriveConsoleStatus(input({ connection: 'connecting' })).headline).toBe('connecting');
  });

  it('connecting: a resync is outstanding even though the socket is open', () => {
    const status = deriveConsoleStatus(input({ resyncRequired: true }));
    expect(status.headline).toBe('connecting');
    expect(status.detail).toContain('sequence gap');
  });

  it('connecting: a reconnect does not claim it is still waiting for the first snapshot', () => {
    const first = deriveConsoleStatus(
      input({ connection: 'connecting', hasSnapshot: false, recommendation: null, estimate: null }),
    );
    expect(first.detail).toContain('first snapshot');

    const again = deriveConsoleStatus(input({ connection: 'reconnecting' }));
    expect(again.headline).toBe('connecting');
    expect(again.detail).not.toContain('first snapshot');
    expect(again.detail).toContain('reconnecting');
  });

  it('healthy: sources valid and a live proposal', () => {
    expect(deriveConsoleStatus(input()).headline).toBe('healthy');
  });

  it('degraded: overall quality degraded but not blocking', () => {
    const status = deriveConsoleStatus(
      input({ quality: qualitySummary({ overall: 'degraded', reason: 'gap channel degraded' }) }),
    );
    expect(status.headline).toBe('degraded');
    expect(status.selectable).toBe(true);
  });

  it('stale: a blocking quality, independent of the connection being open', () => {
    const status = deriveConsoleStatus(
      input({
        quality: qualitySummary({
          overall: 'stale',
          blocking: true,
          reason: 'Channel battery_energy_j is stale.',
        }),
      }),
    );
    expect(status.feed).toBe('stale');
    expect(status.headline).toBe('stale');
    expect(status.selectable).toBe(false);
    expect(status.blockedReason).toContain('stale');
  });

  it('missing-energy: no own battery_energy_j sample', () => {
    const status = deriveConsoleStatus(
      input({ estimate: estimateWithoutEnergy(), recommendation: null }),
    );
    expect(status.headline).toBe('missing-energy');
    expect(status.missingArtefact).toBe('own battery_energy_j samples');
  });

  it('solver-timeout: a withdrawal carrying the solver_timeout reason code', () => {
    const status = deriveConsoleStatus(
      input({
        recommendation: recommendation({
          action_code: 'withdraw_advice',
          reason_codes: ['solver_timeout'],
        }),
      }),
    );
    expect(status.headline).toBe('solver-timeout');
    expect(status.selectable).toBe(false);
  });

  it('no-feasible-plan: a withdrawal with no diagnostic reason code', () => {
    const status = deriveConsoleStatus(
      input({
        recommendation: recommendation({ action_code: 'withdraw_advice', reason_codes: [] }),
      }),
    );
    expect(status.headline).toBe('no-feasible-plan');
    expect(status.missingArtefact).toBe('a feasible candidate plan');
  });

  it('rule-unknown: eligibility unknown, which is A08’s first ~21 s', () => {
    const status = deriveConsoleStatus(
      input({
        recommendation: recommendation({
          action_code: 'withdraw_advice',
          reason_codes: ['eligibility_unknown'],
        }),
        ruleContext: ruleContext({ eligibility: 'unknown' }),
      }),
    );
    expect(status.headline).toBe('rule-unknown');
    expect(status.detail).toContain('detection line');
    expect(status.missingArtefact).toBe('resolved rule conditions for this progress point');
  });

  it('rule-unknown: an unresolved pack condition with no recommendation at all', () => {
    const status = deriveConsoleStatus(
      input({
        recommendation: null,
        ruleContext: ruleContext({ unknown_conditions: ['overtake_gap_threshold_s'] }),
      }),
    );
    expect(status.headline).toBe('rule-unknown');
    expect(status.detail).toContain('overtake_gap_threshold_s');
  });

  it('no-recommendation: nothing published and nothing wrong', () => {
    const status = deriveConsoleStatus(input({ recommendation: null }));
    expect(status.headline).toBe('no-recommendation');
    expect(status.missingArtefact).toBe('recommendation');
  });

  it('selected-pending: a command is in flight', () => {
    const status = deriveConsoleStatus(input({ actionPending: true }));
    expect(status.headline).toBe('selected-pending');
    expect(status.selectable).toBe(false);
    expect(status.blockedReason).toContain('already in flight');
  });

  it('executing: the server moved the status', () => {
    expect(
      deriveConsoleStatus(input({ recommendation: recommendation({ status: 'executing' }) }))
        .headline,
    ).toBe('executing');
  });

  it('completed: the end condition was reached', () => {
    expect(
      deriveConsoleStatus(input({ recommendation: recommendation({ status: 'completed' }) }))
        .headline,
    ).toBe('completed');
  });

  it('expired: the server status is terminal', () => {
    const status = deriveConsoleStatus(
      input({ recommendation: recommendation({ status: 'expired' }) }),
    );
    expect(status.headline).toBe('expired');
    expect(status.selectable).toBe(false);
  });
});

describe('local expiry clears the selectable action without rewriting the status', () => {
  it('marks the recommendation expired once session time passes expires_at_s', () => {
    const status = deriveConsoleStatus(
      input({ sessionTimeS: RECOMMENDATION_FIXTURE.expires_at_s + 1.4 }),
    );
    expect(status.expiredLocally).toBe(true);
    expect(status.headline).toBe('expired');
    expect(status.selectable).toBe(false);
    expect(status.detail).toContain('the server has not yet published the new status');
  });

  it('leaves it selectable while the window is still open', () => {
    const status = deriveConsoleStatus(
      input({ sessionTimeS: RECOMMENDATION_FIXTURE.expires_at_s - 0.1 }),
    );
    expect(status.expiredLocally).toBe(false);
    expect(status.selectable).toBe(true);
  });
});

describe('selection is refused for every status that is not proposed', () => {
  for (const status of ['selected', 'communicated', 'executing', 'completed'] as const) {
    it(`refuses to select a ${status} recommendation`, () => {
      const derived = deriveConsoleStatus(input({ recommendation: recommendation({ status }) }));
      expect(derived.selectable).toBe(false);
      expect(derived.blockedReason).not.toBeNull();
    });
  }
});

describe('rule coverage', () => {
  it('is unknown when the pack declares an unresolved condition', () => {
    expect(ruleCoverageUnknown(ruleContext({ unknown_conditions: ['x'] }))).toBe(true);
  });

  it('is unknown when no profile is admissible', () => {
    expect(ruleCoverageUnknown(ruleContext({ admissible_profiles: [] }))).toBe(true);
  });

  it('is known for the shipped resolved context', () => {
    expect(ruleCoverageUnknown(RULES)).toBe(false);
  });

  it('is not asserted when there is no rule context at all', () => {
    expect(ruleCoverageUnknown(null)).toBe(false);
  });
});
