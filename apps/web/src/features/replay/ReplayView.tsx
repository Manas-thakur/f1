import { useMemo } from 'react';
import { useParams } from 'react-router';

import { ChartFrame, EmptyState, Field, Notice, Panel, StatusBadge } from '@/components';
import { CHANNELS } from '@/contracts/channels';
import { selectCursor } from '@/state/selectors';
import { useSessionStore } from '@/state/sessionStore';
import type { CursorAxis } from '@/state/types';
import { ALIGNMENT_LABEL } from '../lab/BranchCompare';
import { compact, decisionMarkers, domainOf, seriesFor } from '../engineer/series';
import { useSessionRuntime, type SessionRuntimeOptions } from '../engineer/sessionRuntime';
import styles from '../engineer/workspace.module.css';

export interface ReplayViewProps {
  readonly runtimeOptions?: SessionRuntimeOptions;
}

const PANELS: readonly { title: string; channels: readonly string[] }[] = [
  { title: 'Energy', channels: ['battery_energy_j', 'recharge_ledger_j'] },
  { title: 'Power', channels: ['electrical_power_w', 'deploy_power_w', 'harvest_power_w'] },
  { title: 'Speed', channels: ['speed_mps', 'acceleration_mps2'] },
  { title: 'Gap', channels: ['gap_ahead_s', 'gap_behind_s'] },
];


export function ReplayView({ runtimeOptions }: ReplayViewProps) {
  const { sessionId } = useParams();
  const runtime = useSessionRuntime(sessionId, runtimeOptions ?? {});

  const telemetry = useSessionStore((s) => s.server.telemetry);
  const estimate = useSessionStore((s) => s.server.estimate);
  const recommendation = useSessionStore((s) => s.server.recommendation);
  const manifest = useSessionStore((s) => s.server.manifest);
  const cursor = useSessionStore(selectCursor);
  const setCursor = useSessionStore((s) => s.setCursor);
  const cursorAxis = useSessionStore((s) => s.view.cursorAxis);
  const setCursorAxis = useSessionStore((s) => s.setCursorAxis);
  const referenceSeriesId = useSessionStore((s) => s.view.referenceSeriesId);
  const setReferenceSeries = useSessionStore((s) => s.setReferenceSeries);

  const markers = decisionMarkers(recommendation);
  const carId = estimate?.own_car.car_id ?? null;

  const panels = useMemo(
    () =>
      PANELS.map((panel) => ({
        title: panel.title,
        channels: panel.channels,
        series: compact(
          panel.channels.map((channel) =>
            seriesFor(telemetry, channel, carId, {
              label: channel,
              role: referenceSeriesId === channel ? 'reference' : 'selected',
              events: markers,
            }),
          ),
        ),
      })),
    [carId, markers, referenceSeriesId, telemetry],
  );

  const allSeries = panels.flatMap((panel) => panel.series);
  const domain = domainOf(allSeries);
  const mismatched = allSeries.filter((series) => series.xCoordinate !== cursorAxis);
  const availableChannels = CHANNELS.filter(
    (spec) => allSeries.some((series) => series.channel === spec.name),
  );

  const liveTeam = manifest?.mode === 'live_team';

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Replay</h1>
          <p>
            Aligned trajectories on one shared cursor. The alignment axis is stated on every panel
            because a lead at a common distance is not a lead at a common elapsed time.
          </p>
        </div>
        <div className={styles.headActions}>
          <StatusBadge label="Alignment" tone="reference">
            {ALIGNMENT_LABEL[cursorAxis]}
          </StatusBadge>
          <StatusBadge label="Session mode">{manifest?.mode ?? 'no session'}</StatusBadge>
        </div>
      </div>

      {runtime.snapshotError === null ? null : (
        <Notice tone="failure" testId="replay-snapshot-error">
          {runtime.snapshotError.message} (request {runtime.snapshotError.request_id})
        </Notice>
      )}

      <Panel id="replay-controls" title="Alignment and cursor">
        <fieldset className={styles.fieldset}>
          <legend>Align branches at</legend>
          <div className={styles.controlRow}>
            {(['progress_m', 'session_time_s'] as const).map((axis: CursorAxis) => (
              <label key={axis}>
                <input
                  type="radio"
                  name="replay-alignment"
                  value={axis}
                  checked={cursorAxis === axis}
                  onChange={() => setCursorAxis(axis)}
                />{' '}
                {ALIGNMENT_LABEL[axis]}
              </label>
            ))}
          </div>
        </fieldset>

        <div className={styles.formGrid}>
          <Field
            label="Reference trace"
            hint="Drawn dashed and in the reference hue, so the distinction survives greyscale."
          >
            <select
              value={referenceSeriesId ?? ''}
              onChange={(event) =>
                setReferenceSeries(event.target.value === '' ? null : event.target.value)
              }
            >
              <option value="">none</option>
              {availableChannels.map((spec) => (
                <option key={spec.name} value={spec.name}>
                  {spec.name} ({spec.displayUnit})
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Restore the snapshot preceding the cursor"
            hint="Seeking restores the preceding snapshot server-side and consumes events forward."
            state="disabled"
          >
            <button type="button">Restore snapshot</button>
          </Field>
        </div>

        <Notice tone="attention" testId="seek-unavailable">
          {liveTeam
            ? 'A live-team session cannot seek its authoritative clock, so no restore is offered.'
            : 'Snapshot restore is disabled because the control plane has no route for it: SessionCommandKind is start, pause, resume, stop and step, there is no seek command, and no route lists or restores a session snapshot. The cursor below is a view position only and changes no server state.'}
        </Notice>

        {domain === null ? (
          <EmptyState
            artefact="telemetry_view series"
            heading="No trace has arrived for this session"
            reason="Replay draws what the stream published. Nothing is drawn until a telemetry_view event arrives; no placeholder trajectory is substituted."
          />
        ) : (
          <p className="afterlap-small afterlap-muted">
            Cursor spans {domain.min.toFixed(1)} to {domain.max.toFixed(1)} in{' '}
            {cursorAxis === 'progress_m' ? 'metres' : 'seconds'}. Current position{' '}
            {cursor.value === null ? 'not set' : cursor.value.toFixed(1)}.
          </p>
        )}

        {mismatched.length === 0 ? null : (
          <Notice tone="attention" testId="axis-mismatch">
            {mismatched.length} published series are indexed by{' '}
            {mismatched[0]?.xCoordinate ?? 'another coordinate'} rather than the selected alignment.
            They are drawn on their own coordinate and are not re-indexed, because re-indexing
            without a mapping would invent samples.
          </Notice>
        )}
      </Panel>

      <div className={styles.rowPair}>
        {panels.map((panel) => (
          <Panel key={panel.title} id={`replay-${panel.title.toLowerCase()}`} title={panel.title}>
            <ChartFrame
              title={`${panel.title} against ${cursorAxis === 'progress_m' ? 'distance' : 'session time'}`}
              subtitle={`Aligned at ${ALIGNMENT_LABEL[cursorAxis]}.`}
              series={panel.series}
              cursor={cursor.value}
              onCursorChange={setCursor}
              height={200}
              emptyArtefact={`${panel.channels[0] ?? 'telemetry'} view`}
            />
          </Panel>
        ))}
      </div>
    </div>
  );
}
