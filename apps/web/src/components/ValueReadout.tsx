import type { Provenance, Quality, ScalarValue } from '@contracts';

import { UNAVAILABLE_TEXT, formatAge, formatChannelValue } from '../contracts/units';
import { ProvenanceLabel } from './ProvenanceLabel';
import { QualityIndicator } from './QualityIndicator';
import styles from './primitives.module.css';


export type ReadoutState =
  | 'valid'
  | 'empty'
  | 'missing'
  | 'estimated'
  | 'stale'
  | 'invalid'
  | 'pending';

export interface ValueReadoutProps {
  readonly label: string;
  
  readonly channel: string;
  
  readonly value?: number | null;
  readonly scalar?: ScalarValue | null;
  readonly provenance?: Provenance | null;
  readonly quality?: Quality | null;
  readonly ageS?: number | null;
  readonly sourceId?: string | null;
  readonly size?: 'default' | 'small';
  readonly decimals?: number;
  
  readonly unavailableText?: string;
  
  readonly unavailableReason?: string;
  readonly showMeta?: boolean;
  readonly state?: ReadoutState;
}

function deriveState(
  quality: Quality | null | undefined,
  provenance: Provenance | null | undefined,
  available: boolean,
): ReadoutState {
  if (!available) {
    if (quality === 'invalid' || quality === 'stale') {
      return quality;
    }
    return 'missing';
  }
  if (quality === 'stale' || quality === 'invalid') {
    return quality;
  }
  if (provenance === 'estimated') {
    return 'estimated';
  }
  return 'valid';
}


export function ValueReadout({
  label,
  channel,
  value,
  scalar,
  provenance,
  quality,
  ageS,
  sourceId,
  size = 'default',
  decimals,
  unavailableText = UNAVAILABLE_TEXT,
  unavailableReason,
  showMeta = true,
  state,
}: ValueReadoutProps) {
  const siValue = scalar !== undefined && scalar !== null ? scalar.value : (value ?? null);
  const effectiveProvenance = provenance ?? scalar?.provenance ?? null;
  const effectiveQuality = quality ?? scalar?.quality ?? null;
  const effectiveAge = ageS ?? scalar?.age_s ?? null;
  const effectiveSource = sourceId ?? scalar?.source_id ?? null;

  const formatted = formatChannelValue(channel, siValue, {
    ...(decimals === undefined ? {} : { decimals }),
    unavailableText,
  });

  const resolvedState =
    state ?? deriveState(effectiveQuality, effectiveProvenance, formatted.available);

  const pending = resolvedState === 'pending';

  return (
    <div className={styles.readout} data-state={resolvedState} data-channel={channel}>
      <span className={styles.readoutLabel}>{label}</span>
      <span
        className={styles.readoutValue}
        data-size={size}
        data-available={formatted.available && !pending ? 'true' : 'false'}
        aria-busy={pending || undefined}
      >
        {pending ? (
          'reading…'
        ) : formatted.available ? (
          <>
            {formatted.value}
            {formatted.unit === null ? null : (
              <span className={styles.readoutUnit}>{formatted.unit}</span>
            )}
          </>
        ) : (
          unavailableText
        )}
      </span>
      {!formatted.available && unavailableReason !== undefined ? (
        <span className={styles.readoutMeta}>{unavailableReason}</span>
      ) : null}
      {showMeta ? (
        <span className={styles.readoutMeta}>
          <ProvenanceLabel
            provenance={effectiveProvenance}
            sourceId={effectiveSource}
          />
          <QualityIndicator quality={effectiveQuality} />
          <span>{formatAge(effectiveAge)}</span>
        </span>
      ) : null}
    </div>
  );
}
