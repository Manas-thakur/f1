import { describe, expect, it } from 'vitest';
import type { FlagState } from '@contracts';

import {
  APPROVED_STATUSES,
  SAFETY_FLAGS,
  deriveDriverView,
  energyTarget,
  type DriverInput,
} from './precedence';
import {
  ESTIMATE,
  RECOMMENDATION_FIXTURE,
  RULES,
  estimate,
  estimateWithoutEnergy,
  recommendation,
  ruleContext,
} from '@/test/testFixtures';

function withFlag(flag: FlagState) {
  return estimate({
    race_context: { ...ESTIMATE.race_context, flag_state: flag, flag_known: true },
  });
}

function input(overrides: Partial<DriverInput> = {}): DriverInput {
  return {
    mode: 'simulation',
    connection: 'open',
    watchdogExpired: false,
    blockingQuality: false,
    estimate: ESTIMATE,
    recommendation: recommendation({ status: 'communicated' }),
    ruleContext: RULES,
    sessionTimeS: 12.5,
    ...overrides,
  };
}

describe('precedence: safety and withdrawal come first', () => {
  for (const flag of SAFETY_FLAGS) {
    it(`shows the ${flag} state instead of any instruction`, () => {
      const view = deriveDriverView(input({ estimate: withFlag(flag) }));
      expect(view.state).toBe('safety');
      expect(view.showsInstruction).toBe(false);
      expect(view.primary).toBe(flag.replace(/_/g, ' ').toUpperCase());
    });
  }

  it('beats a live instruction even when everything else is healthy', () => {
    const view = deriveDriverView(
      input({
        estimate: withFlag('safety_car'),
        recommendation: recommendation({ status: 'executing' }),
      }),
    );
    expect(view.state).toBe('safety');
  });

  it('shows a withdrawal rather than the last instruction', () => {
    const view = deriveDriverView(
      input({
        recommendation: recommendation({ action_code: 'withdraw_advice', status: 'communicated' }),
      }),
    );
    expect(view.state).toBe('withdrawn');
    expect(view.primary).toBe('NO INSTRUCTION');
  });

  it('ignores a flag the source says is not known', () => {
    const unknownFlag = estimate({
      race_context: { ...ESTIMATE.race_context, flag_state: 'red', flag_known: false },
    });
    expect(deriveDriverView(input({ estimate: unknownFlag })).state).toBe('instruction');
  });
});

describe('precedence: stale beats an instruction', () => {
  it('clears on the local watchdog', () => {
    const view = deriveDriverView(input({ watchdogExpired: true }));
    expect(view.state).toBe('stale');
    expect(view.showsInstruction).toBe(false);
    expect(view.agedContextOnly).toBe(true);
    expect(view.reason).toContain('watchdog');
  });

  it('clears on a lost connection', () => {
    expect(deriveDriverView(input({ connection: 'reconnecting' })).state).toBe('stale');
    expect(deriveDriverView(input({ connection: 'closed' })).state).toBe('stale');
  });

  it('clears on a blocking source quality', () => {
    const view = deriveDriverView(input({ blockingQuality: true }));
    expect(view.state).toBe('stale');
    expect(view.primary).toBe('NO LIVE DATA');
  });

  it('never shows an imperative action while stale', () => {
    const view = deriveDriverView(input({ watchdogExpired: true }));
    expect(view.primary).not.toBe(RECOMMENDATION_FIXTURE.display_text);
    expect(view.trigger).toBeNull();
    expect(view.endCheckpoint).toBeNull();
  });
});

describe('a pending engineer selection is not approved advice', () => {
  it('shows nothing for a proposed recommendation', () => {
    const view = deriveDriverView(input({ recommendation: recommendation({ status: 'proposed' }) }));
    expect(view.state).toBe('neutral');
    expect(view.showsInstruction).toBe(false);
    expect(view.primary).toBe('NO INSTRUCTION');
    expect(view.reason).toContain('Nothing has been approved by the engineer');
  });

  for (const status of [...APPROVED_STATUSES]) {
    it(`shows the instruction once the server records "${status}"`, () => {
      const view = deriveDriverView(input({ recommendation: recommendation({ status }) }));
      expect(view.state).toBe('instruction');
      expect(view.showsInstruction).toBe(true);
      expect(view.primary).toBe(RECOMMENDATION_FIXTURE.display_text);
      expect(view.trigger).toBe(RECOMMENDATION_FIXTURE.trigger.description);
      expect(view.endCheckpoint).toBe(RECOMMENDATION_FIXTURE.end_condition);
    });
  }

  it('clears once the instruction passes its expiry', () => {
    const view = deriveDriverView(
      input({ sessionTimeS: RECOMMENDATION_FIXTURE.expires_at_s + 0.5 }),
    );
    expect(view.showsInstruction).toBe(false);
    expect(view.reason).toContain('expiry');
  });
});

describe('terminal and empty states', () => {
  it('reports completion without an imperative', () => {
    const view = deriveDriverView(
      input({ recommendation: recommendation({ status: 'completed' }) }),
    );
    expect(view.state).toBe('completed');
    expect(view.primary).toBe('COMPLETE');
  });

  it('says nothing has been published when there is no recommendation', () => {
    const view = deriveDriverView(input({ recommendation: null }));
    expect(view.state).toBe('neutral');
    expect(view.reason).toContain('Nothing has been published');
  });

  it('refuses to act for a session that is not a simulation', () => {
    const view = deriveDriverView(input({ mode: 'live_team' }));
    expect(view.state).toBe('mode-not-permitted');
    expect(view.showsInstruction).toBe(false);
    expect(view.reason).toContain('simulator-only');
  });
});

describe('energy target', () => {
  it('is above target when the sample clears the planner projection', () => {
    expect(energyTarget(ESTIMATE, RECOMMENDATION_FIXTURE, RULES).state).toBe('above');
  });

  it('is below target when it does not', () => {
    const projected = recommendation({
      outcomes: [{ checkpoint_id: 'x', progress_m: 2100, own_energy_j: 3_000_000 }],
    });
    const target = energyTarget(ESTIMATE, projected, RULES);
    expect(target.state).toBe('below');
    expect(target.text).toBe('ENERGY BELOW TARGET');
  });

  it('is unknown, not zero, when the energy sample is missing', () => {
    const target = energyTarget(estimateWithoutEnergy(), RECOMMENDATION_FIXTURE, RULES);
    expect(target.state).toBe('unknown');
    expect(target.text).toBe('TARGET UNKNOWN');
  });

  it('is unknown when neither a projection nor a floor exists', () => {
    const target = energyTarget(
      ESTIMATE,
      recommendation({ outcomes: [] }),
      ruleContext({ applicable_limits: {} }),
    );
    expect(target.state).toBe('unknown');
  });
});
