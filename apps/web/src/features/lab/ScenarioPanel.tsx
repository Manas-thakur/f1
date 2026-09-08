import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import type { ApiError, SessionManifest, SessionMode } from '@contracts';

import { newIdempotencyKey } from '@/api/client';
import { guidanceFor, toApiError } from '@/api/errors';
import { useModels, useRuleset } from '@/api/queries';
import {
  catalogueFailureText,
  trackCatalogueClient,
  type TrackCatalogueClient,
} from '@/api/trackCatalogue';
import { useScenarioCatalogue } from '@/api/trackQueries';
import { Button, Field, Notice, Panel, StatusBadge } from '@/components';
import { shortHash } from '../tracks/readiness';
import { useCircuitSelection } from './circuitSelection';
import { labClient, type LabClient } from './controlPlane';
import {
  EMPTY_DRAFT,
  SHIPPED_RULESET_IDS,
  issuesFor,
  validateScenario,
  type ScenarioDraft,
} from './scenario';
import styles from '../engineer/workspace.module.css';

export interface ScenarioPanelProps {
  readonly client?: LabClient;
  readonly initialDraft?: ScenarioDraft;
  readonly catalogueClient?: TrackCatalogueClient;
}

export function ScenarioPanel({
  client = labClient,
  initialDraft = EMPTY_DRAFT,
  catalogueClient = trackCatalogueClient,
}: ScenarioPanelProps) {
  const [draft, setDraft] = useState<ScenarioDraft>(initialDraft);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [createdSessionId, setCreatedSessionId] = useState<string | null>(null);
  const [createdManifest, setCreatedManifest] = useState<SessionManifest | null>(null);

  const rulesetQuery = useRuleset(draft.rulesetId.trim() === '' ? undefined : draft.rulesetId.trim());
  const modelsQuery = useModels();
  const scenarioQuery = useScenarioCatalogue(catalogueClient);

  const trackId = useCircuitSelection((s) => s.trackId);
  const conditionsId = useCircuitSelection((s) => s.conditionsId);

  const scenarioCatalogueError = scenarioQuery.isError
    ? catalogueFailureText('GET /api/v1/scenarios', scenarioQuery.error)
    : null;
  const scenarioEntries = scenarioQuery.data?.scenarios ?? null;
  const scenarioIds =
    scenarioEntries === null ? null : scenarioEntries.map((entry) => entry.scenario_id);
  const selectedScenario =
    scenarioEntries === null
      ? null
      : (scenarioEntries.find((entry) => entry.scenario_id === draft.scenarioId.trim()) ?? null);
  const scenarioUnavailableReason = selectedScenario?.unavailable_reason ?? null;

  const validation = validateScenario(draft, {
    ruleManifest: rulesetQuery.data?.manifest ?? null,
    rulesetError: rulesetQuery.isError
      ? 'the control plane returned an error for this rule pack id'
      : null,
    rulesetLoading: draft.rulesetId.trim() !== '' && rulesetQuery.isPending,
    models: modelsQuery.data?.models ?? [],
    scenarioIds,
    scenarioCatalogueError,
    scenarioUnavailableReason,
  });

  const set = useCallback(
    <K extends keyof ScenarioDraft>(key: K, value: ScenarioDraft[K]) => {
      setDraft((current) => ({ ...current, [key]: value }));
    },
    [],
  );

  const create = useCallback(async () => {
    setPending(true);
    setError(null);
    setCreatedSessionId(null);
    setCreatedManifest(null);
    try {
      const response = await client.createSession(
        {
          mode: draft.mode,
          scenario_id: draft.scenarioId.trim(),
          ruleset_id: draft.rulesetId.trim(),
          seed: Number(draft.seed),
          ...(draft.modelBundleId.trim() === ''
            ? {}
            : { model_bundle_id: draft.modelBundleId.trim() }),
          ...(draft.label.trim() === '' ? {} : { label: draft.label.trim() }),
          ...(trackId === null ? {} : { track_id: trackId }),
          ...(conditionsId === null ? {} : { conditions_id: conditionsId }),
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      setCreatedSessionId(response.manifest.id);
      setCreatedManifest(response.manifest);
    } catch (caught: unknown) {
      setError(toApiError(caught, 'the session could not be created'));
    } finally {
      setPending(false);
    }
  }, [client, conditionsId, draft, trackId]);

  const fieldState = (field: Parameters<typeof issuesFor>[1]) =>
    issuesFor(validation, field).some((issue) => issue.severity === 'error') ? 'error' : 'default';
  const fieldMessage = (field: Parameters<typeof issuesFor>[1]) =>
    issuesFor(validation, field)
      .map((issue) => issue.message)
      .join(' ');

  const warnings = validation.issues.filter((issue) => issue.severity === 'warning');

  return (
    <Panel id="scenario" title="Scenario">
      <div className={styles.badgeRow}>
        <StatusBadge label="Data class" tone="attention">
          synthetic configuration
        </StatusBadge>
        <StatusBadge label="Rule pack review state">
          {rulesetQuery.data?.manifest.reviewed === true ? 'reviewed' : 'not reviewed'}
        </StatusBadge>
        <StatusBadge label="Selected circuit" tone={trackId === null ? 'neutral' : 'attention'}>
          {trackId === null ? 'no circuit selected' : `circuit ${trackId}`}
        </StatusBadge>
        <StatusBadge label="Selected conditions" tone="neutral">
          {conditionsId === null ? 'no conditions tape' : `tape ${conditionsId}`}
        </StatusBadge>
      </div>

      <div className={styles.formGrid}>
        <Field label="Mode" hint="The laboratory creates simulation sessions only.">
          <select
            value={draft.mode}
            onChange={(event) => set('mode', event.target.value as SessionMode)}
          >
            <option value="simulation">simulation</option>
            <option value="replay">replay</option>
            <option value="live_team">live_team</option>
          </select>
        </Field>

        <Field
          label="Scenario id"
          hint="Resolved server-side from configs/scenarios."
          state={fieldState('scenarioId')}
          errorMessage={fieldMessage('scenarioId')}
          required
        >
          <input
            type="text"
            list="lab-scenario-ids"
            value={draft.scenarioId}
            onChange={(event) => set('scenarioId', event.target.value)}
          />
        </Field>

        <Field
          label="Rule pack id"
          hint="Constraints are checked against this pack, independently of the planner."
          state={fieldState('rulesetId')}
          errorMessage={fieldMessage('rulesetId')}
          required
        >
          <input
            type="text"
            list="lab-ruleset-ids"
            value={draft.rulesetId}
            onChange={(event) => set('rulesetId', event.target.value)}
          />
        </Field>

        <Field
          label="Seed"
          hint="Recorded in the manifest. Reproducibility depends on it."
          state={fieldState('seed')}
          errorMessage={fieldMessage('seed')}
          required
        >
          <input type="text" value={draft.seed} onChange={(event) => set('seed', event.target.value)} />
        </Field>

        <Field
          label="Model bundle id"
          hint="Optional. Leave empty to run with no learned contribution."
          state={fieldState('modelBundleId')}
          errorMessage={fieldMessage('modelBundleId')}
        >
          <input
            type="text"
            value={draft.modelBundleId}
            onChange={(event) => set('modelBundleId', event.target.value)}
          />
        </Field>

        <Field label="Label" hint="Shown in the session list. Optional.">
          <input type="text" value={draft.label} onChange={(event) => set('label', event.target.value)} />
        </Field>
      </div>

      <datalist id="lab-scenario-ids">
        {(scenarioIds ?? []).map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>
      {scenarioCatalogueError === null ? null : (
        <Notice tone="failure" testId="scenario-catalogue-unavailable">
          The scenario catalogue is unavailable, so no id suggestions are offered and the id below
          cannot be checked before it is sent. {scenarioCatalogueError} No shipped list is used in
          its place.
        </Notice>
      )}

      {selectedScenario === null ? null : (
        <p className="afterlap-small afterlap-muted" data-testid="scenario-resolves-to">
          The control plane resolves this scenario to circuit{' '}
          <span className="afterlap-mono">{selectedScenario.track_id ?? 'unreported'}</span>
          {selectedScenario.real_circuit
            ? ` — a compiled package at readiness ${
                selectedScenario.track_readiness ?? 'unreported'
              }, hash ${shortHash(selectedScenario.track_package_hash) ?? 'unreported'}, run as ${
                selectedScenario.run_label ?? 'an unlabelled run'
              }`
            : ' — a synthetic track document, not a real circuit'}
          , with conditions{' '}
          <span className="afterlap-mono">{selectedScenario.conditions_id ?? 'none'}</span>.
        </p>
      )}
      <datalist id="lab-ruleset-ids">
        {SHIPPED_RULESET_IDS.map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>

      <fieldset className={styles.fieldset} disabled>
        <legend>Initial conditions and observation conditions</legend>
        <p className="afterlap-small afterlap-muted">
          Initial progress, gap and stored energy, opponent policy, channel delay and
          missing-channel injection are not offered here because{' '}
          <span className="afterlap-mono">POST /sessions</span> accepts no such fields: they belong
          to the scenario document the server resolves by id. Two shipped scenarios already
          exercise degraded observation —{' '}
          <span className="afterlap-mono">loop-no-energy-channel</span> and{' '}
          <span className="afterlap-mono">loop-regen-disabled</span>. Extending the create-session
          contract is a named integration action; nothing is collected here that would be silently
          discarded.
        </p>
      </fieldset>

      {warnings.length === 0 ? null : (
        <>
          <ul className={styles.inlineList} data-testid="scenario-warnings">
            {warnings.map((issue) => (
              <li key={`${issue.field}-${issue.message}`}>{issue.message}</li>
            ))}
          </ul>
          <Field
            label="I acknowledge the synthetic and unreviewed inputs listed above"
            state={fieldState('acknowledgedSynthetic')}
            errorMessage={fieldMessage('acknowledgedSynthetic')}
          >
            <input
              type="checkbox"
              checked={draft.acknowledgedSynthetic}
              onChange={(event) => set('acknowledgedSynthetic', event.target.checked)}
            />
          </Field>
        </>
      )}

      <div className={styles.controlRow}>
        <Button
          variant="primary"
          state={pending ? 'pending' : validation.canStart ? 'default' : 'disabled'}
          pendingLabel="Creating…"
          {...(validation.canStart || pending
            ? {}
            : {
                disabledReason: validation.issues
                  .filter((issue) => issue.severity === 'error')
                  .map((issue) => issue.message)
                  .join(' '),
              })}
          onClick={() => void create()}
        >
          Create session
        </Button>
      </div>

      {createdSessionId === null ? null : (
        <Notice live testId="session-created">
          Created session <span className="afterlap-mono">{createdSessionId}</span>.{' '}
          <Link to={`/sessions/${createdSessionId}/lab`}>Open its laboratory</Link> or{' '}
          <Link to={`/sessions/${createdSessionId}/engineer`}>its engineer console</Link>. A new
          configuration is a new session; it never mutates an archived experiment.
          {createdManifest === null ? null : (
            <>
              {' '}
              The control plane resolved circuit{' '}
              <span className="afterlap-mono">
                {createdManifest.track_id ?? 'none (synthetic track document)'}
              </span>{' '}
              at readiness{' '}
              <span className="afterlap-mono">
                {createdManifest.track_readiness ?? 'unavailable'}
              </span>
              , package hash{' '}
              <span className="afterlap-mono">
                {shortHash(createdManifest.track_package_hash) ?? 'unavailable'}
              </span>
              , conditions{' '}
              <span className="afterlap-mono">
                {createdManifest.conditions_id ?? 'none'}
              </span>{' '}
              at tape hash{' '}
              <span className="afterlap-mono">
                {shortHash(createdManifest.conditions_hash) ?? 'unavailable'}
              </span>
              . These are the values the server returned, not the values this panel requested.
            </>
          )}
        </Notice>
      )}

      {error === null ? null : (
        <Notice tone="failure" live testId="scenario-error">
          {error.message} {guidanceFor(error) ?? ''} (request {error.request_id})
        </Notice>
      )}
    </Panel>
  );
}
