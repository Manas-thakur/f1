/**
 * What the interface is allowed to claim about a real circuit.
 *
 * The readiness ladder is TRACK_REGISTRY_2026.md; the labelling rules are
 * D-10, D-11 and D-12. Three of them are enforced here rather than left to
 * each view:
 *
 * 1. **A circuit below `geometry_validated` cannot be selected.** Its package
 *    has not passed closure and official-length checks, or there is no
 *    compiled package at all. The control would be a lie, so it is disabled
 *    and the measured reason is shown next to it.
 * 2. **No circuit is ever presented as a validated real-track simulation.**
 *    `simulation_eligible` needs a surveyed corridor and location telemetry
 *    cannot supply one, so a run on a compiled circuit is geometry-real and
 *    energy-synthetic and carries `real_circuit_synthetic_energy` wherever the
 *    circuit is named.
 * 3. **An unknown corridor means unavailable, not zero.** Lateral position,
 *    side-by-side and contact are corridor-derived; with `corridor_quality`
 *    unknown the package returns `nan` for width and the lateral degree of
 *    freedom is disabled in the engine. The views print the reason, never a
 *    number.
 */
import type { BadgeTone } from '@/components';
import {
  READINESS_LADDER,
  type ReadinessRung,
  type TrackCatalogueEntry,
} from '@/api/trackCatalogue';

/** The label a run on a compiled real circuit carries (D-10). */
export const REAL_CIRCUIT_SYNTHETIC_ENERGY = 'real_circuit_synthetic_energy';

export const SYNTHETIC_ENERGY_EXPLANATION =
  'Geometry is compiled from real circuit data; the car, battery, tyre and driver documents are the shipped synthetic ones. The run is geometry-real and energy-synthetic. It is not a measurement of a real car and not evidence of performance.';

/** The rung a circuit must reach before the laboratory will offer it. */
export const MIN_SELECTABLE_RUNG: ReadinessRung = 'geometry_validated';

/** D-11. Shown wherever compiled geometry is displayed. */
export const OPENF1_ATTRIBUTION =
  'Geometry derived from OpenF1 /location telemetry (openf1.org), licensed CC BY-NC-SA 4.0: attribution, non-commercial use, share-alike. It is a driven line — apexes cut, exits run wide — not a surveyed FIA centreline, and openf1.org describes its data as unofficial.';

export const CORRIDOR_UNKNOWN_REASON =
  'The compiled package declares corridor_quality: unknown, so the usable track width is not known at any point. Lateral position, side-by-side state and contact are corridor-derived and are unavailable here — they are not zero.';

/** The specific fields an unknown corridor withdraws. */
export const CORRIDOR_DERIVED_FIELDS: readonly string[] = [
  'lateral position',
  'side-by-side state',
  'contact and wheel-to-wheel claims',
  'usable track width',
];

export const SIMULATION_ELIGIBLE_UNREACHABLE =
  'No circuit reaches simulation_eligible. That rung requires a surveyed corridor, which location telemetry cannot supply, so nothing here is a validated real-track simulation.';

function rank(rung: ReadinessRung | null): number {
  if (rung === null) return -2;
  if (rung === 'rejected') return -1;
  return READINESS_LADDER.indexOf(rung);
}

export function readinessRank(rung: ReadinessRung | null): number {
  return rank(rung);
}

/** Badge tone for a rung. A rung is never `verified`: see rule 2 above. */
export function readinessTone(rung: ReadinessRung | null): BadgeTone {
  if (rung === null) return 'failure';
  if (rung === 'rejected') return 'failure';
  if (rung === 'discovered') return 'neutral';
  return 'attention';
}

export interface Selectability {
  readonly selectable: boolean;
  /** Why not, in the words of the measured evidence. Empty when selectable. */
  readonly reason: string;
}

/** The measured length error, when the validator recorded one. */
function lengthClause(entry: TrackCatalogueEntry): string {
  const measured = entry.length_error_fraction;
  if (measured === null) {
    return '';
  }
  return ` Its recomputed arc length differs from the official length by ${(measured * 100).toFixed(3)} %.`;
}

/**
 * The catalogue's own reason, when it gave one.
 *
 * The validator emits one note per check — fourteen of them for a compiled
 * package — and pasting all of them into a control's reason would bury the
 * one sentence that matters. Only the note the validator writes to explain the
 * derived status (`status <rung>: …`) and the row's own
 * `unavailable_reason` are quoted here; the full list is shown as evidence
 * next to the selected circuit, where there is room for it.
 */
function serverClause(entry: TrackCatalogueEntry): string {
  const parts = [
    entry.unavailable_reason,
    ...entry.notes.filter((note) => note.startsWith('status ')),
  ].filter((part): part is string => part !== null && part !== '');
  return parts.length === 0 ? '' : ` ${parts.join(' ')}`;
}

/** Every note the validator recorded, in the order it recorded them. */
export function validatorNotes(entry: TrackCatalogueEntry | null): readonly string[] {
  return entry === null ? [] : entry.notes;
}

/**
 * Whether the laboratory may offer this circuit, and why not when it may not.
 *
 * Fails closed twice over: the rung must be at or above
 * `geometry_validated` **and** the catalogue's own `simulation_ready` flag
 * must be set. If the two ever disagree the circuit is refused, because the
 * disagreement itself means the readiness shown cannot be trusted. The reason
 * always names measured evidence — a rung, a measured length error, the
 * server's own refusal text — never a vague "not ready".
 */
export function selectability(entry: TrackCatalogueEntry): Selectability {
  if (entry.readiness === null) {
    return {
      selectable: false,
      reason:
        entry.readiness_reported === null
          ? `The catalogue reports no readiness rung for this circuit, so it cannot be offered. Readiness is derived from validation evidence and is never assumed.${serverClause(entry)}`
          : `The catalogue reports readiness "${entry.readiness_reported}", which is not a rung of the ladder, so this circuit cannot be offered.`,
    };
  }
  if (entry.readiness === 'rejected') {
    return {
      selectable: false,
      reason: `Rejected by the independent validator; running it would inject geometry the evidence refuses.${serverClause(entry)}`,
    };
  }
  if (rank(entry.readiness) < rank(MIN_SELECTABLE_RUNG)) {
    return {
      selectable: false,
      reason: entry.package_present
        ? `Readiness is ${entry.readiness}, below ${MIN_SELECTABLE_RUNG}: the compiled package did not pass every geometry check, so it cannot drive the simulator.${lengthClause(entry)}${serverClause(entry)}`
        : `Readiness is ${entry.readiness}: registry identity only. No compiled package and no hashes exist for this circuit, so there is no geometry to run.${serverClause(entry)}`,
    };
  }
  if (!entry.simulation_ready) {
    return {
      selectable: false,
      reason: `The catalogue reports readiness ${entry.readiness} but does not report this circuit as able to drive the simulator. The two disagree, so it is refused rather than offered on the strength of the rung alone.${serverClause(entry)}`,
    };
  }
  return { selectable: true, reason: '' };
}

/** Corridor state, and what it withdraws. */
export function corridorKnown(corridorQuality: string | null): boolean {
  return corridorQuality === 'surveyed' || corridorQuality === 'validated_estimate';
}

/**
 * Short form of a content hash, for identity checks by eye.
 *
 * The `sha256:` prefix used by session manifests is stripped so a package hash
 * and a manifest hash are comparable at a glance. Never truncate silently to
 * something that looks complete: the ellipsis is part of the output.
 */
export function shortHash(hash: string | null | undefined, digits = 12): string | null {
  if (hash === null || hash === undefined || hash === '') {
    return null;
  }
  const bare = hash.startsWith('sha256:') ? hash.slice('sha256:'.length) : hash;
  return bare.length <= digits ? bare : `${bare.slice(0, digits)}…`;
}

/** Human text for a provenance enum value, without upgrading its status. */
export function provenanceText(provenance: string | null): string {
  switch (provenance) {
    case 'openf1_location_telemetry':
      return 'OpenF1 /location telemetry (driven line, unofficial)';
    case 'fastf1_position_telemetry':
      return 'FastF1 position telemetry (driven line, unofficial)';
    case 'licensed_survey':
      return 'licensed survey';
    case 'osm_crosscheck_only':
      return 'OpenStreetMap cross-check only';
    case 'synthetic_sketch':
      return 'synthetic sketch (not a real circuit)';
    case null:
      return 'not reported';
    default:
      return provenance;
  }
}

/** True when the attribution line must be visible for this provenance. */
export function needsOpenF1Attribution(provenance: string | null): boolean {
  return provenance === 'openf1_location_telemetry';
}

/** Corridor quality as words, with the consequence attached. */
export function corridorText(corridorQuality: string | null): string {
  switch (corridorQuality) {
    case 'surveyed':
      return 'surveyed';
    case 'validated_estimate':
      return 'validated estimate';
    case 'unknown':
      return 'unknown — no usable width at any point';
    case null:
      return 'not reported';
    default:
      return corridorQuality;
  }
}
