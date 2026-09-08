
import type { ModelManifest, RuleManifest, SessionMode } from '@contracts';

export interface ScenarioDraft {
  readonly mode: SessionMode;
  readonly scenarioId: string;
  readonly rulesetId: string;

  readonly seed: string;
  readonly modelBundleId: string;
  readonly label: string;
  readonly acknowledgedSynthetic: boolean;
}

export const EMPTY_DRAFT: ScenarioDraft = {
  mode: 'simulation',
  scenarioId: '',
  rulesetId: '',
  seed: '42',
  modelBundleId: '',
  label: '',
  acknowledgedSynthetic: false,
};

export const SHIPPED_RULESET_IDS: readonly string[] = [
  'synthetic-pack-v1',
  'synthetic-pack-v2-strict',
  'synthetic-pack-unknown',
];

export type IssueSeverity = 'error' | 'warning';

export interface ValidationIssue {
  readonly field: keyof ScenarioDraft | 'ruleset_manifest';
  readonly severity: IssueSeverity;
  readonly message: string;
}

export interface ValidationContext {

  readonly ruleManifest: RuleManifest | null;

  readonly rulesetError: string | null;
  readonly rulesetLoading: boolean;
  readonly models: readonly ModelManifest[];
  readonly scenarioIds?: readonly string[] | null;
  readonly scenarioCatalogueError?: string | null;
  readonly scenarioUnavailableReason?: string | null;
}

export interface ValidationResult {
  readonly issues: readonly ValidationIssue[];
  readonly canStart: boolean;

  readonly synthetic: boolean;
}

const ID_PATTERN = /^[a-z0-9][a-z0-9._-]*$/;

export function validateScenario(
  draft: ScenarioDraft,
  context: ValidationContext,
): ValidationResult {
  const issues: ValidationIssue[] = [];

  if (draft.mode !== 'simulation') {
    issues.push({
      field: 'mode',
      severity: 'error',
      message:
        'The laboratory creates simulation sessions only. A replay or live-team session is not created from here, and the control plane would refuse simulator commands on one.',
    });
  }

  if (draft.scenarioId.trim() === '') {
    issues.push({
      field: 'scenarioId',
      severity: 'error',
      message: 'A scenario id is required; the control plane resolves the scenario document by id.',
    });
  } else if (!ID_PATTERN.test(draft.scenarioId.trim())) {
    issues.push({
      field: 'scenarioId',
      severity: 'error',
      message: 'Scenario ids are lower-case identifiers, for example two-straight-counterattack.',
    });
  } else if (context.scenarioIds === undefined || context.scenarioIds === null) {
    issues.push({
      field: 'scenarioId',
      severity: 'warning',
      message:
        context.scenarioCatalogueError === undefined || context.scenarioCatalogueError === null
          ? 'The scenario catalogue has not been read, so this id cannot be checked here. The control plane will reject it if it does not resolve.'
          : `The scenario catalogue could not be read (${context.scenarioCatalogueError}), so this id cannot be checked here. No shipped list is used in its place, and the control plane will reject the id if it does not resolve.`,
    });
  } else if (!context.scenarioIds.includes(draft.scenarioId.trim())) {
    issues.push({
      field: 'scenarioId',
      severity: 'warning',
      message:
        'This id is not one the control plane listed at GET /api/v1/scenarios. It will be rejected if it does not resolve.',
    });
  } else if (
    context.scenarioUnavailableReason !== undefined &&
    context.scenarioUnavailableReason !== null
  ) {
    issues.push({
      field: 'scenarioId',
      severity: 'error',
      message: `The control plane reports this scenario as unrunnable: ${context.scenarioUnavailableReason}`,
    });
  }

  if (draft.rulesetId.trim() === '') {
    issues.push({
      field: 'rulesetId',
      severity: 'error',
      message: 'A rule pack id is required. Constraints are checked against the pack, not the planner.',
    });
  } else if (context.rulesetError !== null) {
    issues.push({
      field: 'ruleset_manifest',
      severity: 'error',
      message: `The rule pack could not be read: ${context.rulesetError}`,
    });
  } else if (context.rulesetLoading) {
    issues.push({
      field: 'ruleset_manifest',
      severity: 'error',
      message: 'Waiting for the rule pack manifest. Validation is not complete until it arrives.',
    });
  }

  const manifest = context.ruleManifest;
  if (manifest !== null) {
    if (manifest.reviewed !== true) {
      issues.push({
        field: 'ruleset_manifest',
        severity: 'warning',
        message: `Rule pack ${manifest.ruleset_id} declares reviewed: false. Nothing produced with it is compliance evidence.`,
      });
    }
    if ((manifest.unknown_conditions ?? []).length > 0) {
      issues.push({
        field: 'ruleset_manifest',
        severity: 'warning',
        message: `The pack declares unresolved conditions (${(manifest.unknown_conditions ?? []).join(', ')}). Advice will be suppressed while they remain unresolved.`,
      });
    }
  }

  const seed = Number(draft.seed);
  if (draft.seed.trim() === '' || !Number.isInteger(seed) || seed < 0) {
    issues.push({
      field: 'seed',
      severity: 'error',
      message: 'Seed must be a non-negative integer. Reproducibility depends on it being recorded exactly.',
    });
  }

  const bundle = draft.modelBundleId.trim();
  if (bundle !== '') {
    const model = context.models.find((candidate) => candidate.id === bundle) ?? null;
    if (model === null) {
      issues.push({
        field: 'modelBundleId',
        severity: 'error',
        message: 'No model manifest with this id is listed by the control plane.',
      });
    } else if (model.approval_status !== 'approved') {
      issues.push({
        field: 'modelBundleId',
        severity: 'warning',
        message: `Model ${model.id} is ${model.approval_status ?? 'unevaluated'}, not approved. Its output is a candidate result only.`,
      });
    }
  }

  const warnings = issues.filter((issue) => issue.severity === 'warning');
  if (warnings.length > 0 && !draft.acknowledgedSynthetic) {
    issues.push({
      field: 'acknowledgedSynthetic',
      severity: 'error',
      message:
        'Acknowledge the synthetic and unreviewed inputs above before starting. This is recorded on screen, not sent to the server.',
    });
  }

  return {
    issues,
    canStart: issues.every((issue) => issue.severity !== 'error'),
    synthetic: manifest === null ? true : manifest.synthetic,
  };
}

export function issuesFor(
  result: ValidationResult,
  field: ValidationIssue['field'],
): readonly ValidationIssue[] {
  return result.issues.filter((issue) => issue.field === field);
}
