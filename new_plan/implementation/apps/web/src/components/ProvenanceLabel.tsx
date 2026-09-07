import type { Provenance } from '@contracts';

import { PROVENANCE_TEXT, formatAge } from '../contracts/units';
import styles from './primitives.module.css';

export interface ProvenanceLabelProps {
  readonly provenance: Provenance | null | undefined;
  readonly sourceId?: string | null;
  readonly ageS?: number | null;
  readonly showAge?: boolean;
}

/**
 * Where a number came from.
 *
 * The point of this label is that a simulated value must never be readable as
 * a measured one. It is deliberately plain text rather than a colour, and it
 * says "provenance unknown" instead of guessing.
 */
export function ProvenanceLabel({
  provenance,
  sourceId,
  ageS,
  showAge = false,
}: ProvenanceLabelProps) {
  const text =
    provenance === null || provenance === undefined
      ? 'provenance unknown'
      : PROVENANCE_TEXT[provenance];
  return (
    <span className={styles.provenance}>
      <span className={styles.provenanceStrong}>{text}</span>
      {sourceId ? <span>· {sourceId}</span> : null}
      {showAge ? <span>· {formatAge(ageS)}</span> : null}
    </span>
  );
}
