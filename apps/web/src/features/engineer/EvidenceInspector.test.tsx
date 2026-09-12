import type { Recommendation } from '@contracts';

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SESSION_SNAPSHOT } from '@/test/contractFixtures';

import { EvidenceInspector } from './EvidenceInspector';

const BASE = SESSION_SNAPSHOT.recommendation as Recommendation;

function inspector(recommendation: Recommendation) {
  return render(
    <EvidenceInspector
      open
      onOpenChange={() => undefined}
      recommendation={recommendation}
      ruleContext={null}
      evidence={null}
      loading={false}
      errorMessage={null}
      returnFocusTo="evidence-trigger"
    />,
  );
}

describe('EvidenceInspector provenance surfaces', () => {
  it('names the planner that produced the decision', () => {
    inspector({ ...BASE, planner_identity: 'afterlap-core-planning' });
    expect(screen.getByText('afterlap-core-planning')).toBeInTheDocument();
  });

  it('records that no planner identity was published rather than inventing one', () => {
    inspector({ ...BASE, planner_identity: null });
    expect(screen.getAllByText('not recorded').length).toBeGreaterThan(0);
  });

  it('says which baseline answered when the learned contribution is disabled', () => {
    inspector({
      ...BASE,
      learned_contribution_enabled: false,
      learned: {
        enabled: false,
        bundle_id: null,
        weights_hash: null,
        in_support: false,
        support_reason: null,
        continuation_value: null,
        disagreement: null,
        member_count: null,
        calibrator_id: null,
        calibration_status: 'unavailable',
        baseline_identity: 'mpc-only/planner-v1',
        reason_codes: [],
      },
    });
    expect(screen.getByText(/disabled — mpc-only\/planner-v1 answered/)).toBeInTheDocument();
  });

  it('publishes the reasons a capability did not contribute', () => {
    inspector({
      ...BASE,
      unavailable_reasons: ['scenario re-simulation is disabled for this session'],
    });
    expect(screen.getByTestId('unavailable-reasons')).toHaveTextContent(
      /scenario re-simulation is disabled/,
    );
  });

  it('states the absence of an outcome range instead of rendering nothing', () => {
    inspector({ ...BASE, outcome_ranges: [] });
    expect(screen.getByText(/No outcome range was published/)).toBeInTheDocument();
  });

  it('labels an outcome range as an observed spread, never a quantile', () => {
    inspector({
      ...BASE,
      outcome_ranges: [
        {
          checkpoint_id: 'attack-exit',
          progress_m: 2100,
          scenario_count: 3,
          weight_covered: 0.75,
          elapsed_time_s: {
            lower: 10,
            upper: 12,
            unit: 's',
            kind: 'physical_bounds',
            coverage: null,
            provenance: 'simulated',
            quality: 'valid',
            observed_at_s: null,
            age_s: null,
          },
          gap_to_reference_s: null,
          own_energy_j: null,
          ahead_of_rival_weight: 0.5,
        },
      ],
    });
    const ranges = screen.getByTestId('outcome-ranges');
    expect(ranges).toHaveTextContent(/observed spread, not a quantile/);
    expect(ranges).toHaveTextContent(/75% of\s+ensemble weight/);
  });

  it('shows the alternatives with the checker verdict and why each was not recommended', () => {
    inspector({
      ...BASE,
      alternatives: [
        {
          plan_id: 'plan-a',
          action_code: 'attack',
          display_text: 'attack: push from 1900 m',
          rank: 1,
          selected: true,
          constraint_status: 'pass',
          final_score: 28.55,
          score_delta_vs_selected: 0,
          expected_utility: 22.66,
          cvar_loss: 22.76,
          terminal_energy_j: 1_200_000,
          switch_count: 2,
          switching_penalty: 0.4,
          rejected_reason: null,
          reason_codes: [],
        },
        {
          plan_id: 'plan-b',
          action_code: 'maintain',
          display_text: 'maintain: neutral from 1900 m',
          rank: 2,
          selected: false,
          constraint_status: 'unknown',
          final_score: 28.65,
          score_delta_vs_selected: 0.1,
          expected_utility: 22.83,
          cvar_loss: 22.88,
          terminal_energy_j: 1_300_000,
          switch_count: 1,
          switching_penalty: 0.2,
          rejected_reason: 'the independent checker did not pass this candidate',
          reason_codes: [],
        },
      ],
    });
    expect(screen.getByText('attack: push from 1900 m (recommended)')).toBeInTheDocument();
    expect(
      screen.getByText('the independent checker did not pass this candidate'),
    ).toBeInTheDocument();
  });

  it('states the absence of alternatives rather than rendering an empty table', () => {
    inspector({ ...BASE, alternatives: [] });
    expect(screen.getByText(/No alternative was recorded/)).toBeInTheDocument();
  });
});
