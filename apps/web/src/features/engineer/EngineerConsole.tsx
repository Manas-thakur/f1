import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router';

import { apiClient, type ApiClient } from '@/api/client';
import { guidanceFor } from '@/api/errors';
import { queryKeys } from '@/api/queries';
import {
  ChartFrame,
  Notice,
  Panel,
  ProvenanceLabel,
  QualityIndicator,
  StatusBadge,
} from '@/components';
import { formatAge } from '@/contracts/units';
import { useSessionStore } from '@/state/sessionStore';
import {
  selectCursor,
  selectDataAgeS,
  selectQualitySummary,
  selectTimeSensitiveDisabledReason,
} from '@/state/selectors';
import {
  SessionCircuitPanel,
  SessionCircuitStrip,
} from '../tracks/SessionCircuitIdentity';
import { BattleView } from './BattleView';
import { DecisionHistory } from './DecisionHistory';
import { EnergyTimeline } from './EnergyTimeline';
import { EvidenceInspector } from './EvidenceInspector';
import { RecommendationPanel } from './RecommendationPanel';
import { deriveConsoleStatus } from './lifecycle';
import { useDecision } from './decisionQuery';
import { OPERATOR_IDENTITY_NOTE, useNarrowViewport } from './operator';
import { compact, decisionMarkers, seriesFor } from './series';
import { useSessionRuntime, type SessionRuntimeOptions } from './sessionRuntime';
import { useRecommendationActions } from './useRecommendationActions';
import styles from './workspace.module.css';

const EVIDENCE_BUTTON_ID = 'engineer-open-evidence';
const DECISION_STEPS = ['Observe', 'Review', 'Select', 'Communicate', 'Verify'] as const;

function decisionStep(status: string | null | undefined): number {
  if (status === 'completed' || status === 'executing') return 4;
  if (status === 'communicated') return 3;
  if (status === 'selected') return 2;
  if (status === 'proposed') return 1;
  return 0;
}

export interface EngineerConsoleProps {

  readonly runtimeOptions?: SessionRuntimeOptions;
  readonly client?: ApiClient;
}

function SourcePanel() {
  const capabilities = useSessionStore((s) => s.server.capabilities);
  const channelQuality = useSessionStore((s) => s.server.channelQuality);
  const dataAge = useSessionStore(selectDataAgeS);
  const quality = useSessionStore(selectQualitySummary);
  const manifest = useSessionStore((s) => s.server.manifest);
  const telemetryFreshAtS = useSessionStore((s) => s.server.telemetryFreshAtS);

  const entries = Object.entries(capabilities ?? {}).filter(
    ([key, value]) => key !== 'notes' && typeof value === 'string',
  ) as readonly (readonly [string, string])[];

  return (
    <Panel id="sources" title="Sources">
      <dl className={styles.definitionList}>
        <dt>Data age</dt>
        <dd>{formatAge(dataAge)}</dd>
        <dt>Last telemetry at</dt>
        <dd>
          {telemetryFreshAtS === null
            ? 'no telemetry view received'
            : `${telemetryFreshAtS.toFixed(2)} s session time`}
        </dd>
        <dt>Overall quality</dt>
        <dd>
          <QualityIndicator quality={quality.overall} detail={quality.reason} />
        </dd>
        <dt>Manifest</dt>
        <dd>
          {manifest === null || manifest === undefined ? (
            'no session manifest'
          ) : (
            <>
              {manifest.mode ?? 'mode not recorded'} · seed {manifest.seed ?? 'not recorded'} ·{' '}
              {manifest.synthetic === false ? 'recorded' : 'synthetic'}
            </>
          )}
        </dd>
      </dl>

      <h3>Capabilities</h3>
      {entries.length === 0 ? (
        <p className="afterlap-small afterlap-muted">
          The snapshot declares no runtime capabilities, so no capability can be assumed available.
        </p>
      ) : (
        <ul className={styles.inlineList}>
          {entries.map(([name, state]) => (
            <li key={name}>
              <span className="afterlap-mono">{name}</span>:{' '}
              <StatusBadge
                label="Capability state"
                tone={
                  state === 'available'
                    ? 'verified'
                    : state === 'degraded'
                      ? 'attention'
                      : 'failure'
                }
              >
                {state}
              </StatusBadge>
            </li>
          ))}
        </ul>
      )}

      <h3>Channel quality</h3>
      {channelQuality.length === 0 ? (
        <p className="afterlap-small afterlap-muted">
          No per-channel quality has been published for this session.
        </p>
      ) : (
        <ul className={styles.inlineList}>
          {channelQuality.map((entry) => (
            <li key={`${entry.channel}:${entry.car_id ?? 'own'}`}>
              <span className="afterlap-mono">{entry.channel}</span>{' '}
              <QualityIndicator quality={entry.quality} detail={entry.reason ?? null} />{' '}
              <span className="afterlap-small afterlap-muted">{formatAge(entry.age_s ?? null)}</span>
            </li>
          ))}
        </ul>
      )}

      <Notice tone="attention">{OPERATOR_IDENTITY_NOTE}</Notice>
    </Panel>
  );
}


export function EngineerConsole({ runtimeOptions, client = apiClient }: EngineerConsoleProps) {
  const { sessionId } = useParams();
  const runtime = useSessionRuntime(sessionId, runtimeOptions ?? {});
  const queryClient = useQueryClient();
  const narrow = useNarrowViewport();

  const recommendation = useSessionStore((s) => s.server.recommendation);
  const estimate = useSessionStore((s) => s.server.estimate);
  const ruleContext = useSessionStore((s) => s.server.ruleContext);
  const sessionManifest = useSessionStore((s) => s.server.manifest);
  const capabilities = useSessionStore((s) => s.server.capabilities);
  const telemetry = useSessionStore((s) => s.server.telemetry);
  const executions = useSessionStore((s) => s.server.executions);
  const sessionTimeS = useSessionStore((s) => s.server.sessionTimeS);
  const connection = useSessionStore((s) => s.stream.connection);
  const resyncRequired = useSessionStore((s) => s.stream.resyncRequired);
  const hasSnapshot = useSessionStore((s) => s.server.manifest !== null && s.server.manifest !== undefined);
  const quality = useSessionStore(selectQualitySummary);
  const timeSensitiveDisabledReason = useSessionStore(selectTimeSensitiveDisabledReason);
  const cursor = useSessionStore(selectCursor);
  const setCursor = useSessionStore((s) => s.setCursor);
  const inspector = useSessionStore((s) => s.view.inspector);
  const openInspector = useSessionStore((s) => s.openInspector);
  const closeInspector = useSessionStore((s) => s.closeInspector);

  const recommendationId = recommendation?.id ?? null;
  const actionPending = useSessionStore((s) =>
    recommendationId === null
      ? false
      : Object.keys(s.request.inFlight).some((key) =>
          key.startsWith(`recommendation:${recommendationId}:`),
        ),
  );

  const decisionQuery = useDecision(recommendationId, client);

  const status = useMemo(
    () =>
      deriveConsoleStatus({
        connection,
        resyncRequired,
        hasSnapshot,
        quality,
        estimate,
        recommendation,
        ruleContext,
        capabilities,
        sessionTimeS,
        actionPending,
      }),
    [
      actionPending,
      capabilities,
      connection,
      estimate,
      hasSnapshot,
      quality,
      recommendation,
      resyncRequired,
      ruleContext,
      sessionTimeS,
    ],
  );

  const refresh = useCallback(async () => {
    await runtime.refresh();
    if (recommendationId !== null) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.decision(recommendationId) });
    }
  }, [queryClient, recommendationId, runtime]);

  const openEvidence = useCallback(() => {
    openInspector('decision', recommendationId ?? 'none', EVIDENCE_BUTTON_ID);
  }, [openInspector, recommendationId]);

  const actions = useRecommendationActions({
    sessionId: sessionId ?? '',
    recommendation,


    expectedRevision: recommendation?.revision ?? 0,
    client,
    refresh,
    onConflict: openEvidence,
  });

  const markers = decisionMarkers(recommendation);
  const carId = estimate?.own_car.car_id ?? null;
  const speedSeries = compact([
    seriesFor(telemetry, 'speed_mps', carId, { label: 'own speed', events: markers }),
  ]);
  const gapSeries = compact([
    seriesFor(telemetry, 'gap_ahead_s', carId, { label: 'gap ahead', events: markers }),
    seriesFor(telemetry, 'gap_behind_s', carId, {
      label: 'gap behind',
      role: 'context',
      events: markers,
    }),
  ]);

  const execution =
    recommendationId === null
      ? null
      : (executions.filter((event) => event.recommendation_id === recommendationId).at(-1) ?? null);

  const snapshotErrorMessage =
    runtime.snapshotError === null
      ? null
      : `${runtime.snapshotError.message} ${guidanceFor(runtime.snapshotError) ?? ''} (request ${runtime.snapshotError.request_id})`.trim();

  const decisionErrorMessage = decisionQuery.isError
    ? 'The decision record could not be read from the control plane.'
    : null;
  const activeDecisionStep = decisionStep(recommendation?.status);

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Engineer console</h1>
          <p>
            One instruction with its trigger, end condition, channels, rule results and decision
            history. Selecting advice records a decision; it never actuates the car.
          </p>
          <SessionCircuitStrip manifest={sessionManifest} capabilities={capabilities} />
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Console state" tone={status.feed === 'healthy' ? 'verified' : 'attention'}>
            {status.headline}
          </StatusBadge>
          <ProvenanceLabel provenance={estimate?.own_car.speed_mps.provenance ?? null} />
        </div>
      </div>

      <ol className={styles.decisionFlow} aria-label="Decision workflow">
        {DECISION_STEPS.map((step, index) => (
          <li
            key={step}
            data-state={index < activeDecisionStep ? 'complete' : index === activeDecisionStep ? 'current' : 'pending'}
          >
            <span aria-hidden="true">{index + 1}</span>{step}
          </li>
        ))}
      </ol>

      <Notice
        live
        tone={
          status.headline === 'healthy' || status.headline === 'degraded' ? 'info' : 'attention'
        }
        testId="console-state"
      >
        <strong>{status.heading}.</strong> {status.detail}
      </Notice>

      {snapshotErrorMessage === null ? null : (
        <Notice tone="failure" testId="snapshot-error">
          {snapshotErrorMessage}
        </Notice>
      )}

      <div className={styles.columns}>
        <div className={styles.stack}>
          <RecommendationPanel
            recommendation={recommendation}
            status={status}
            sessionTimeS={sessionTimeS}
            actions={actions}
            execution={execution}
            readOnly={narrow}
            onOpenEvidence={openEvidence}
            evidenceButtonId={EVIDENCE_BUTTON_ID}
            timeSensitiveDisabledReason={timeSensitiveDisabledReason}
          />

          <Panel id="energy" title="Energy">
            <EnergyTimeline
              telemetry={telemetry}
              estimate={estimate}
              recommendation={recommendation}
              ruleContext={ruleContext}
              cursor={cursor.value}
              onCursorChange={setCursor}
            />
          </Panel>

          <div className={styles.rowPair}>
            <Panel id="speed" title="Speed">
              <ChartFrame
                title="Speed over distance"
                series={speedSeries}
                cursor={cursor.value}
                onCursorChange={setCursor}
                height={180}
                emptyArtefact="speed_mps telemetry view"
              />
            </Panel>
            <Panel id="gap" title="Gap">
              <ChartFrame
                title="Gap over distance"
                series={gapSeries}
                cursor={cursor.value}
                onCursorChange={setCursor}
                height={180}
                emptyArtefact="gap_ahead_s telemetry view"
              />
            </Panel>
          </div>

          <BattleView estimate={estimate} />

          <DecisionHistory
            operatorEvents={decisionQuery.data?.operator_events ?? []}
            executionEvents={decisionQuery.data?.execution_events ?? executions}
            loading={decisionQuery.isPending && recommendationId !== null}
            errorMessage={decisionErrorMessage}
            decisionId={recommendationId}
          />
        </div>

        <aside className={`${styles.stack} ${styles.inspectorColumn}`} aria-label="Session sources">
          <SessionCircuitPanel manifest={sessionManifest} capabilities={capabilities} />
          <SourcePanel />
        </aside>
      </div>

      <EvidenceInspector
        open={inspector.open && inspector.kind === 'decision'}
        onOpenChange={(next) => {
          if (!next) {
            closeInspector();
          }
        }}
        recommendation={recommendation}
        ruleContext={ruleContext}
        evidence={decisionQuery.data ?? null}
        loading={decisionQuery.isFetching}
        errorMessage={decisionErrorMessage}
        returnFocusTo={EVIDENCE_BUTTON_ID}
      />
    </div>
  );
}
