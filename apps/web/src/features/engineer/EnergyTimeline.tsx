import type { Recommendation, RuleContext, StateEstimate, TelemetrySeries } from '@contracts';

import { ChartFrame, Notice, ValueReadout } from '@/components';
import { UNAVAILABLE_TEXT, formatChannelValue } from '@/contracts/units';
import {
  compact,
  decisionMarkers,
  domainOf,
  energyFloorSeries,
  projectedEnergySeries,
  seriesFor,
} from './series';
import styles from './workspace.module.css';

export interface EnergyTimelineProps {
  readonly telemetry: Readonly<Record<string, TelemetrySeries>>;
  readonly estimate: StateEstimate | null;
  readonly recommendation: Recommendation | null;
  readonly ruleContext: RuleContext | null;
  readonly cursor: number | null;
  readonly onCursorChange: (value: number | null) => void;
}


export function EnergyTimeline({
  telemetry,
  estimate,
  recommendation,
  ruleContext,
  cursor,
  onCursorChange,
}: EnergyTimelineProps) {
  const carId = estimate?.own_car.car_id ?? null;
  const markers = decisionMarkers(recommendation);
  const measured = seriesFor(telemetry, 'battery_energy_j', carId, {
    label: 'stored energy',
    role: 'selected',
    events: markers,
  });
  const projected = projectedEnergySeries(recommendation);
  const domain = domainOf(compact([measured, projected]));
  const floor = energyFloorSeries(ruleContext, domain);
  const series = compact([measured, projected, floor]);

  const floorValue = ruleContext?.applicable_limits?.battery_energy_min_j ?? null;
  const allowance = ruleContext?.applicable_limits?.recharge_allowance_remaining_j ?? null;
  const terminalCheckpoint = (recommendation?.outcomes ?? [])[0] ?? null;

  return (
    <div className={styles.stack}>
      <ChartFrame
        title="Energy over distance"
        subtitle="Own stored energy against the configured floor, with the plan's projected checkpoint values."
        series={series}
        cursor={cursor}
        onCursorChange={onCursorChange}
        height={240}
        emptyArtefact="battery_energy_j telemetry view"
        emptyAction={
          <p className="afterlap-small afterlap-muted">
            The stream publishes this series in a `telemetry_view` event. Nothing is drawn until
            one arrives; no placeholder trace is substituted.
          </p>
        }
      />

      <div className={styles.readoutRow}>
        <ValueReadout
          label="Energy floor (rule limit)"
          channel="battery_energy_j"
          value={floorValue}
          provenance="configured"
          showMeta={false}
          unavailableReason="The resolved rule context publishes no energy floor."
        />
        <ValueReadout
          label="Recharge allowance remaining"
          channel="battery_energy_j"
          value={allowance}
          provenance="configured"
          showMeta={false}
          unavailableReason="The rule pack publishes no per-lap recharge allowance."
        />
        <ValueReadout
          label={
            terminalCheckpoint === null
              ? 'Projected at checkpoint'
              : `Projected at ${terminalCheckpoint.checkpoint_id}`
          }
          channel="battery_energy_j"
          value={terminalCheckpoint?.own_energy_j ?? null}
          provenance="estimated"
          showMeta={false}
          unavailableReason="The plan publishes no projected energy for a named checkpoint."
        />
        <ValueReadout
          label="Current stored energy"
          channel="battery_energy_j"
          scalar={estimate?.own_car.battery_energy_j ?? null}
          unavailableReason="No own battery_energy_j sample has been received."
        />
      </div>

      {floorValue === null ||
      terminalCheckpoint?.own_energy_j === null ||
      terminalCheckpoint?.own_energy_j === undefined ? (
        <Notice tone="attention">
          Margin to the energy floor is {UNAVAILABLE_TEXT}: it needs both a configured floor and a
          projected checkpoint value, and at least one is missing.
        </Notice>
      ) : (
        <Notice>
          Projected margin above the floor at {terminalCheckpoint.checkpoint_id}:{' '}
          {formatChannelValue('battery_energy_j', terminalCheckpoint.own_energy_j - floorValue).text}
          . Projection provenance is estimated, from the planner scenario outcomes.
        </Notice>
      )}
    </div>
  );
}
