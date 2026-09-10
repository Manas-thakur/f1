import type { RivalBelief, ScalarValue, StateEstimate } from '@contracts';

import {
  DataTable,
  Notice,
  Panel,
  ProvenanceLabel,
  QualityIndicator,
  StatusBadge,
  ValueReadout,
  type Column,
} from '@/components';
import {
  UNAVAILABLE_TEXT,
  formatAge,
  formatChannelValue,
  formatInterval,
  formatScalar,
} from '@/contracts/units';
import { RIVAL_ENERGY_QUANTILE_NOTE, describeInterval, intervalKindLine } from './intervals';
import styles from '@/styles/workspace.module.css';

export interface BattleViewProps {
  readonly estimate: StateEstimate | null;
}


function scalarWithSigma(channel: string, scalar: ScalarValue | null | undefined): string {
  const formatted = formatScalar(channel, scalar ?? null);
  if (!formatted.available) {
    return UNAVAILABLE_TEXT;
  }
  const sigma = scalar?.standard_deviation ?? null;
  if (sigma === null) {
    return `${formatted.text} (no dispersion published)`;
  }
  const sigmaText = formatChannelValue(channel, sigma);
  return `${formatted.text} ± ${sigmaText.value ?? UNAVAILABLE_TEXT} (1σ)`;
}

const COLUMNS: readonly Column<RivalBelief>[] = [
  {
    id: 'car',
    header: 'Rival',
    cell: (row) => (
      <>
        <span className="afterlap-mono">{row.car_id}</span>
        <br />
        <span className="afterlap-small afterlap-muted">
          {row.slot} · {row.is_ahead ? 'ahead' : 'behind'}
        </span>
      </>
    ),
  },
  {
    id: 'gap_s',
    header: 'Gap',
    unit: 's',
    numeric: true,
    cell: (row) => scalarWithSigma('gap_ahead_s', row.gap_s),
  },
  {
    id: 'gap_m',
    header: 'Gap',
    unit: 'm',
    numeric: true,
    cell: (row) => formatScalar('progress_m', row.gap_m).text,
  },
  {
    id: 'closing',
    header: 'Relative speed',
    unit: 'km/h',
    numeric: true,
    cell: (row) => formatScalar('speed_mps', row.relative_speed_mps).text,
  },
  {
    id: 'energy',
    header: 'Stored energy belief',
    cell: (row) => {
      const description = describeInterval(row.energy_interval_j ?? null);
      if (description === null) {
        return (
          <>
            {UNAVAILABLE_TEXT}
            <br />
            <span className="afterlap-small afterlap-muted">
              no rival energy belief published for this car
            </span>
          </>
        );
      }
      return (
        <>
          <span className="afterlap-mono">
            {formatInterval('battery_energy_j', row.energy_interval_j ?? null).text}
          </span>
          <br />
          <span className="afterlap-small afterlap-muted">
            {intervalKindLine(row.energy_interval_j ?? null)}
          </span>
          <br />
          <ProvenanceLabel
            provenance={row.energy_interval_j?.provenance ?? null}
            ageS={row.energy_interval_j?.age_s ?? null}
            showAge
          />{' '}
          <QualityIndicator quality={row.energy_interval_j?.quality ?? null} />
        </>
      );
    },
  },
  {
    id: 'intentions',
    header: 'Intention weights',
    cell: (row) => (
      <span className="afterlap-mono afterlap-small">
        conserve {row.intentions.conserve.toFixed(2)} · normal {row.intentions.normal.toFixed(2)} ·
        attack {row.intentions.attack.toFixed(2)} · defend {row.intentions.defend.toFixed(2)}
      </span>
    ),
  },
  {
    id: 'age',
    header: 'Observation age',
    numeric: true,
    cell: (row) => formatAge(row.observation_age_s ?? null),
  },
  {
    id: 'lateral',
    header: 'Lateral geometry',
    cell: (row) =>
      row.lateral_geometry_known === true ? (
        <StatusBadge label="Lateral geometry" tone="verified">
          known
        </StatusBadge>
      ) : (
        <StatusBadge label="Lateral geometry">not known</StatusBadge>
      ),
  },
];


export function BattleView({ estimate }: BattleViewProps) {
  const rivals = estimate?.rival_beliefs ?? [];
  const own = estimate?.own_car ?? null;
  const anyQuantile = rivals.some((r) => (r.energy_interval_j?.kind ?? null) === 'quantile');
  const anyLateralUnknown = rivals.some((r) => r.lateral_geometry_known !== true);

  return (
    <Panel id="battle" title="Battle">
      {own === null ? (
        <Notice tone="attention">
          No state estimate is available, so no own-car position or rival gap can be shown.
        </Notice>
      ) : (
        <div className={styles.readoutRow}>
          <ValueReadout label="Own progress" channel="progress_m" scalar={own.progress_m} />
          <ValueReadout label="Own speed" channel="speed_mps" scalar={own.speed_mps} />
          <ValueReadout
            label="Own stored energy"
            channel="battery_energy_j"
            scalar={own.battery_energy_j}
            unavailableReason="No own battery_energy_j sample has been received."
          />
          <ValueReadout
            label="Own bus power"
            channel="electrical_power_w"
            scalar={own.electrical_power_w}
          />
        </div>
      )}

      <DataTable
        caption="Rival beliefs"
        description="Beliefs held by the estimator about other cars. Every quantity here is inferred, never measured on the rival car."
        columns={COLUMNS}
        rows={rivals}
        rowKey={(row) => `${row.slot}:${row.car_id}`}
        emptyArtefact="rival belief"
        emptyAction={
          <p className="afterlap-small afterlap-muted">
            The estimator publishes a belief once a rival has been observed. Nothing is shown for
            a car that has not been.
          </p>
        }
      />

      {anyQuantile ? (
        <Notice tone="attention" testId="rival-energy-quantile-note">
          {RIVAL_ENERGY_QUANTILE_NOTE}
        </Notice>
      ) : null}

      {anyLateralUnknown ? (
        <Notice tone="attention" testId="lateral-geometry-note">
          Lateral geometry is not available for at least one rival, so no side-by-side or contact
          likelihood is computed or drawn. Gap is a longitudinal quantity only.
        </Notice>
      ) : null}
    </Panel>
  );
}
