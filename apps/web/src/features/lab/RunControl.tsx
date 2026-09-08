import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError, SessionCommandKind, SessionMode } from '@contracts';

import { apiClient, type ApiClient } from '@/api/client';
import { commandKeys, runCommand } from '@/api/commands';
import { guidanceFor } from '@/api/errors';
import { Button, Field, Notice, Panel, StatusBadge } from '@/components';
import { useSessionStore } from '@/state/sessionStore';
import { CONSOLE_OPERATOR_ID } from '../engineer/operator';
import styles from '../engineer/workspace.module.css';


export const PACING_OPTIONS = [0.25, 0.5, 1, 2, 4] as const;
export type Pacing = (typeof PACING_OPTIONS)[number];

const BASE_INTERVAL_MS = 1_000;

export function pacingIntervalMs(pacing: Pacing): number {
  return Math.round(BASE_INTERVAL_MS / pacing);
}

export interface RunControlProps {
  readonly sessionId: string;
  readonly mode: SessionMode | null;
  readonly client?: ApiClient;
  readonly refresh: () => Promise<void> | void;
}

const COMMANDS: readonly { kind: SessionCommandKind; label: string }[] = [
  { kind: 'start', label: 'Start' },
  { kind: 'pause', label: 'Pause' },
  { kind: 'resume', label: 'Resume' },
  { kind: 'step', label: 'Step' },
  { kind: 'stop', label: 'Stop' },
];


export function RunControl({ sessionId, mode, client = apiClient, refresh }: RunControlProps) {
  const status = useSessionStore((s) => s.server.status);
  const revision = useSessionStore((s) => s.server.revision);
  const [pending, setPending] = useState<SessionCommandKind | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [stepDuration, setStepDuration] = useState('1');
  const [pacing, setPacing] = useState<Pacing>(1);
  const [autoAdvance, setAutoAdvance] = useState(false);

  const simulation = mode === 'simulation';
  const stepSeconds = Number(stepDuration);
  const stepValid = Number.isFinite(stepSeconds) && stepSeconds > 0;

  const send = useCallback(
    async (kind: SessionCommandKind) => {
      setPending(kind);
      setError(null);
      const result = await runCommand(useSessionStore.getState(), {
        key: commandKeys.sessionCommand(sessionId, kind),
        kind: `session:${kind}`,
        expectedRevision: useSessionStore.getState().server.revision,
        send: (idempotencyKey) =>
          client.sendSessionCommand(
            sessionId,
            {
              kind,
              expected_revision: useSessionStore.getState().server.revision,
              operator_id: CONSOLE_OPERATOR_ID,
              ...(kind === 'step' && stepValid ? { step_duration_s: stepSeconds } : {}),
            },
            { idempotencyKey },
          ),
        onConflict: async () => {
          await refresh();
        },
      });
      setPending(null);
      if (result.status === 'ok') {
        await refresh();
        return;
      }
      if (result.status === 'duplicate_suppressed') {
        return;
      }
      setError(result.error);
    },
    [client, refresh, sessionId, stepSeconds, stepValid],
  );


  const sendRef = useRef(send);
  sendRef.current = send;
  useEffect(() => {
    if (!autoAdvance || !simulation || !stepValid) {
      return;
    }
    const timer = setInterval(() => {
      void sendRef.current('step');
    }, pacingIntervalMs(pacing));
    return () => clearInterval(timer);
  }, [autoAdvance, pacing, simulation, stepValid]);

  const disabledReason = simulation
    ? null
    : 'Run control is offered for simulation sessions only. Pausing a live-team session would pause acquisition, which this product does not do.';

  return (
    <Panel id="run-control" title="Run control">
      <div className={styles.badgeRow}>
        <StatusBadge label="Session status" tone={status === 'running' ? 'selection' : 'neutral'}>
          {status}
        </StatusBadge>
        <StatusBadge label="Session revision">revision {revision}</StatusBadge>
        <StatusBadge label="Session mode">{mode ?? 'unknown'}</StatusBadge>
      </div>

      <div className={styles.controlRow}>
        {COMMANDS.map(({ kind, label }) => (
          <Button
            key={kind}
            variant={kind === 'start' ? 'primary' : kind === 'stop' ? 'danger' : 'default'}
            state={pending === kind ? 'pending' : simulation ? 'default' : 'disabled'}
            pendingLabel="Sending…"
            {...(simulation || pending === kind
              ? {}
              : { disabledReason: disabledReason ?? 'unavailable' })}
            onClick={() => void send(kind)}
          >
            {label}
          </Button>
        ))}
      </div>

      <div className={styles.formGrid}>
        <Field
          label="Simulated step duration"
          hint="Seconds of simulated time consumed by one step command."
          state={stepValid ? 'default' : 'error'}
          errorMessage="Step duration must be a positive number of seconds."
        >
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={stepDuration}
            onChange={(event) => setStepDuration(event.target.value)}
          />
        </Field>

        <Field
          label="Wall-clock pacing"
          hint="How often the client asks for a step. It does not change simulated time per step and it does not change physics."
        >
          <select
            value={String(pacing)}
            onChange={(event) => setPacing(Number(event.target.value) as Pacing)}
          >
            {PACING_OPTIONS.map((option) => (
              <option key={option} value={String(option)}>
                {option}× ({pacingIntervalMs(option)} ms between steps)
              </option>
            ))}
          </select>
        </Field>

        <Field label="Auto-advance" hint="Issues one step command per wall-clock interval.">
          <input
            type="checkbox"
            checked={autoAdvance}
            disabled={!simulation || !stepValid}
            onChange={(event) => setAutoAdvance(event.target.checked)}
          />
        </Field>
      </div>

      {error === null ? null : (
        <Notice tone="failure" live testId="run-control-error">
          {error.message} {guidanceFor(error) ?? ''} (request {error.request_id})
        </Notice>
      )}
    </Panel>
  );
}
