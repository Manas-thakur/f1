import { describe, expect, it } from 'vitest';

import { CANDIDATE_MODEL, RULE_MANIFEST } from '../engineer/testFixtures';
import {
  EMPTY_DRAFT,
  issuesFor,
  validateScenario,
  type ScenarioDraft,
  type ValidationContext,
} from './scenario';

function draft(overrides: Partial<ScenarioDraft> = {}): ScenarioDraft {
  return {
    ...EMPTY_DRAFT,
    scenarioId: 'two-straight-counterattack',
    rulesetId: 'synthetic-pack-v1',
    seed: '42',
    ...overrides,
  };
}

function context(overrides: Partial<ValidationContext> = {}): ValidationContext {
  return {
    ruleManifest: { ...RULE_MANIFEST, unknown_conditions: [] },
    rulesetError: null,
    rulesetLoading: false,
    models: [CANDIDATE_MODEL],
    ...overrides,
  };
}

describe('a scenario is validated before anything starts', () => {
  it('refuses a mode the laboratory does not create', () => {
    const result = validateScenario(draft({ mode: 'live_team' }), context());
    expect(result.canStart).toBe(false);
    expect(issuesFor(result, 'mode')[0]?.message).toContain('simulation sessions only');
  });

  it('refuses an empty scenario id', () => {
    const result = validateScenario(draft({ scenarioId: '' }), context());
    expect(result.canStart).toBe(false);
    expect(issuesFor(result, 'scenarioId')[0]?.severity).toBe('error');
  });

  it('refuses an id that is not an identifier', () => {
    const result = validateScenario(draft({ scenarioId: 'Two Straight!' }), context());
    expect(issuesFor(result, 'scenarioId')[0]?.message).toContain('lower-case identifiers');
  });

  it('warns, without refusing, about an id that is not shipped', () => {
    const result = validateScenario(
      draft({ scenarioId: 'not-a-shipped-scenario', acknowledgedSynthetic: true }),
      context(),
    );
    expect(issuesFor(result, 'scenarioId')[0]?.severity).toBe('warning');
    expect(result.canStart).toBe(true);
  });

  it('refuses a seed that is not a non-negative integer', () => {
    for (const seed of ['', 'abc', '-1', '4.5']) {
      const result = validateScenario(draft({ seed }), context());
      expect(result.canStart, `seed ${seed}`).toBe(false);
      expect(issuesFor(result, 'seed')[0]?.message).toContain('non-negative integer');
    }
  });

  it('refuses to start while the rule pack manifest has not been read', () => {
    const result = validateScenario(draft(), context({ ruleManifest: null, rulesetLoading: true }));
    expect(result.canStart).toBe(false);
    expect(issuesFor(result, 'ruleset_manifest')[0]?.message).toContain('Waiting for the rule pack');
  });

  it('refuses a rule pack the control plane could not resolve', () => {
    const result = validateScenario(
      draft(),
      context({ ruleManifest: null, rulesetError: 'not found' }),
    );
    expect(result.canStart).toBe(false);
    expect(issuesFor(result, 'ruleset_manifest')[0]?.message).toContain('could not be read');
  });

  it('refuses a model bundle the control plane does not list', () => {
    const result = validateScenario(draft({ modelBundleId: 'no-such-bundle' }), context());
    expect(result.canStart).toBe(false);
    expect(issuesFor(result, 'modelBundleId')[0]?.severity).toBe('error');
  });

  it('warns that a candidate bundle is not approved', () => {
    const result = validateScenario(
      draft({ modelBundleId: CANDIDATE_MODEL.id, acknowledgedSynthetic: true }),
      context(),
    );
    expect(issuesFor(result, 'modelBundleId')[0]?.message).toContain('not approved');
    expect(result.canStart).toBe(true);
  });
});

describe('unreviewed and unresolved inputs must be acknowledged, never relabelled', () => {
  it('blocks the start until the operator acknowledges an unreviewed pack', () => {
    const unreviewed = context({ ruleManifest: { ...RULE_MANIFEST, unknown_conditions: [] } });
    const blocked = validateScenario(draft(), unreviewed);
    expect(blocked.canStart).toBe(false);
    expect(issuesFor(blocked, 'acknowledgedSynthetic')[0]?.severity).toBe('error');

    const acknowledged = validateScenario(draft({ acknowledgedSynthetic: true }), unreviewed);
    expect(acknowledged.canStart).toBe(true);

    expect(
      acknowledged.issues.some((issue) => issue.message.includes('reviewed: false')),
    ).toBe(true);
  });

  it('names the pack’s unresolved conditions and says advice will be suppressed', () => {
    const result = validateScenario(draft(), context({ ruleManifest: RULE_MANIFEST }));
    const messages = issuesFor(result, 'ruleset_manifest').map((issue) => issue.message);
    expect(messages.join(' ')).toContain('overtake_gap_threshold_s');
    expect(messages.join(' ')).toMatch(/advice will be suppressed/i);
  });

  it('reports the configuration as synthetic', () => {
    expect(validateScenario(draft(), context()).synthetic).toBe(true);
  });
});
