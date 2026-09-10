import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router';
import type { ApiError, DeploymentProfile } from '@contracts';

import { apiClient, type ApiClient } from '@/api/client';
import { commandKeys, runCommand } from '@/api/commands';
import { guidanceFor } from '@/api/errors';
import { useSessionRuntime, type SessionRuntimeOptions } from '@/api/sessionRuntime';
import { CONSOLE_OPERATOR_ID } from '@/app/operator';
import { Button, DriverCircuitContext, Notice } from '@/components';
import { CORRIDOR_UNKNOWN_REASON } from '@/contracts/readiness';
import { formatAge, formatChannelValue } from '@/contracts/units';
import { selectQualitySummary } from '@/state/selectors';
import { useSessionStore } from '@/state/sessionStore';
import { deriveDriverView, energyTarget } from './precedence';
import styles from './driver.module.css';


export const DEFAULT_WATCHDOG_MS = 5_000;

export interface DriverDisplayProps {
  readonly runtimeOptions?: SessionRuntimeOptions;
  readonly client?: ApiClient;

  readonly watchdogMs?: number;
}

interface BigNumberProps {
  readonly label: string;
  readonly channel: string;
  readonly value: number | null;
  readonly unavailableText?: string;
}

function BigNumber({ label, channel, value, unavailableText }: BigNumberProps) {
  const formatted = formatChannelValue(channel, value);
  return (
    <div className={styles.number}>
      <span className={styles.numberLabel}>{label}</span>
      <span className={styles.numberValue} data-available={formatted.available ? 'true' : 'false'}>
        {formatted.available ? (
          <>
            {formatted.value}
            {formatted.unit === null ? null : (
              <span className={styles.numberUnit}>{formatted.unit}</span>
            )}
          </>
        ) : (
          (unavailableText ?? formatted.text)
        )}
      </span>
    </div>
  );
}


export function DriverDisplay({
  runtimeOptions,
  client = apiClient,
  watchdogMs = DEFAULT_WATCHDOG_MS,
}: DriverDisplayProps) {
  const { sessionId } = useParams();
  useSessionRuntime(sessionId, runtimeOptions ?? {});

  const manifest = useSessionStore((s) => s.server.manifest);
  const estimate = useSessionStore((s) => s.server.estimate);
  const recommendation = useSessionStore((s) => s.server.recommendation);
  const ruleContext = useSessionStore((s) => s.server.ruleContext);
  const sessionTimeS = useSessionStore((s) => s.server.sessionTimeS);
  const connection = useSessionStore((s) => s.stream.connection);
  const accepted = useSessionStore((s) => s.stream.acceptedEnvelopes);
  const lastSequence = useSessionStore((s) => s.server.lastSequence);
  const quality = useSessionStore(selectQualitySummary);
  const capabilities = useSessionStore((s) => s.server.capabilities);

  const [commandError, setCommandError] = useState<ApiError | null>(null);
  const [lastExecution, setLastExecution] = useState<string | null>(null);
  const [pendingProfile, setPendingProfile] = useState<DeploymentProfile | null>(null);


  const lastUpdateRef = useRef<number>(Date.now());
  const [watchdogExpired, setWatchdogExpired] = useState(false);

  useEffect(() => {
    lastUpdateRef.current = Date.now();
    setWatchdogExpired(false);
  }, [accepted, lastSequence]);

  useEffect(() => {
    const timer = setInterval(() => {
      setWatchdogExpired(Date.now() - lastUpdateRef.current > watchdogMs);
    }, Math.max(250, Math.floor(watchdogMs / 4)));
    return () => clearInterval(timer);
  }, [watchdogMs]);

  const view = useMemo(
    () =>
      deriveDriverView({
        mode: manifest?.mode ?? null,
        connection,
        watchdogExpired,
        blockingQuality: quality.blocking,
        estimate,
        recommendation,
        ruleContext,
        sessionTimeS,
      }),
    [
      connection,
      estimate,
      manifest,
      quality.blocking,
      recommendation,
      ruleContext,
      sessionTimeS,
      watchdogExpired,
    ],
  );

  const target = energyTarget(estimate, recommendation, ruleContext);
  const admissible = ruleContext?.admissible_profiles ?? [];
  const simulatorSession = manifest?.mode === 'simulation';

  const sendDriverAction = useCallback(
    async (profile: DeploymentProfile) => {
      if (sessionId === undefined) {
        return;
      }
      setPendingProfile(profile);
      setCommandError(null);
      const result = await runCommand(useSessionStore.getState(), {
        key: commandKeys.driverAction(sessionId),
        kind: 'driver-action',
        expectedRevision: useSessionStore.getState().server.revision,
        send: (idempotencyKey) =>
          client.sendDriverAction(
            sessionId,
            {
              profile_id: profile,
              observed_at_s: useSessionStore.getState().server.sessionTimeS,
              operator_id: CONSOLE_OPERATOR_ID,
              ...(recommendation === null ? {} : { recommendation_id: recommendation.id }),
            },
            { idempotencyKey },
          ),
      });
      setPendingProfile(null);
      if (result.status === 'ok') {
        setLastExecution(
          `${result.value.execution.observed_profile_id} · ${result.value.execution.match_status}`,
        );
        return;
      }
      if (result.status === 'duplicate_suppressed') {
        return;
      }
      setCommandError(result.error);
    },
    [client, recommendation, sessionId],
  );

  const ownCar = estimate?.own_car ?? null;
  const raceContext = estimate?.race_context ?? null;

  return (
    <div className={`afterlap-driver-scope ${styles.scope}`} data-testid="driver-scope">
      <div className={styles.headRow}>
        <h1 className={styles.routeTitle}>Driver display</h1>
        <div className={styles.contextRow}>
          <span>mode {manifest?.mode ?? 'unknown'}</span>
          <span>car {ownCar?.car_id ?? 'unknown'}</span>
          <span>lap {raceContext?.lap ?? 'unknown'}</span>
          <span>
            flag{' '}
            {raceContext === null || raceContext.flag_known === false
              ? 'unknown'
              : (raceContext.flag_state ?? 'unknown')}
          </span>
          <span>eligibility {ruleContext?.eligibility ?? 'unknown'}</span>
          <DriverCircuitContext manifest={manifest} capabilities={capabilities} />
        </div>
      </div>

      <div className={styles.commandGrid}>
      <section
        className={`${styles.primaryBlock} ${styles.instructionBlock}`}
        data-state={view.state}
        aria-label="Primary instruction"
      >
        <p className={styles.markRow}>
          <span className={styles.mark} aria-hidden="true">
            {view.mark}
          </span>
          <span>{view.state.replace(/-/g, ' ')}</span>
        </p>
        <p className={styles.primaryText} data-testid="driver-primary">
          {view.primary}
        </p>
        <div className={styles.commandConditions}>
          {view.trigger === null ? null : <p className={styles.subText}>FROM {view.trigger}</p>}
          {view.endCheckpoint === null ? null : <p className={styles.subText}>UNTIL {view.endCheckpoint}</p>}
        </div>
        <p className={styles.reason}>{view.reason}</p>
      </section>

      <section className={`${styles.primaryBlock} ${styles.targetBlock}`} data-state={view.state} aria-label="Energy target">
        <p className={styles.numberLabel}>Energy target</p>
        <p className={styles.targetText}>
          <span className={styles.mark} aria-hidden="true">
            {target.mark}
          </span>
          <span data-testid="energy-target">{target.text}</span>
        </p>
      </section>
      </div>

      <div className={styles.numberRow}>
        <BigNumber label="Speed" channel="speed_mps" value={ownCar?.speed_mps.value ?? null} />
        <BigNumber
          label="Stored energy"
          channel="battery_energy_j"
          value={ownCar?.battery_energy_j.value ?? null}
        />
        <BigNumber
          label="Bus power"
          channel="electrical_power_w"
          value={ownCar?.electrical_power_w.value ?? null}
        />
        <BigNumber label="Lap distance" channel="progress_m" value={ownCar?.progress_m.value ?? null} />
        <BigNumber
          label="Lateral position"
          channel="lateral_position_m"
          value={null}
          unavailableText="unavailable"
        />
      </div>

      <p className={styles.inputNote} data-testid="driver-corridor-unavailable">
        {CORRIDOR_UNKNOWN_REASON}
      </p>

      {view.agedContextOnly ? (
        <p className={styles.aged} data-testid="aged-context">
          Vehicle context above was last observed{' '}
          {formatAge(ownCar?.speed_mps.age_s ?? null)} and is not being updated. No instruction is
          shown while data is not live.
        </p>
      ) : null}

      <section className={styles.inputs} aria-label="Simulator input">
        <p className={styles.inputNote}>
          Simulator input. Choosing a profile reports an execution; it is not an acknowledgement of
          the instruction.
        </p>
        <div className={styles.inputButtons}>
          {(admissible.length === 0
            ? (['neutral'] as readonly DeploymentProfile[])
            : admissible
          ).map((profile) => (
            <Button
              key={profile}
              variant={profile === 'overtake' ? 'primary' : 'default'}
              state={
                pendingProfile === profile
                  ? 'pending'
                  : !simulatorSession || admissible.length === 0
                    ? 'disabled'
                    : 'default'
              }
              pendingLabel="Sending…"
              {...(simulatorSession && admissible.length > 0
                ? {}
                : {
                    disabledReason: simulatorSession
                      ? 'The resolved rule context admits no deployment profile.'
                      : 'Driver actions are simulator-only; the control plane refuses them for this session mode.',
                  })}
              onClick={() => void sendDriverAction(profile)}
            >
              {profile}
            </Button>
          ))}
        </div>
        {lastExecution === null ? null : (
          <p className={styles.inputNote} data-testid="driver-execution">
            Reported execution: {lastExecution}
          </p>
        )}
        {commandError === null ? null : (
          <Notice tone="failure" testId="driver-command-error">
            {commandError.message} {guidanceFor(commandError) ?? ''}
          </Notice>
        )}
      </section>
    </div>
  );
}
