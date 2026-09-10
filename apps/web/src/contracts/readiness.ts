import type { TrackReadiness, TrackSummary } from '@contracts';

import type { BadgeTone } from '../components/StatusBadge';

export const READINESS_LADDER: readonly TrackReadiness[] = [
  'discovered',
  'geometry_validated',
  'event_rules_validated',
  'condition_calibrated',
  'simulation_eligible',
];

export const REAL_CIRCUIT_SYNTHETIC_ENERGY = 'real_circuit_synthetic_energy';

export const SYNTHETIC_ENERGY_EXPLANATION =
  'Geometry is compiled from real circuit data; the car, battery, tyre and driver documents are the shipped synthetic ones. The run is geometry-real and energy-synthetic. It is not a measurement of a real car and not evidence of performance.';

export const MIN_SELECTABLE_RUNG: TrackReadiness = 'geometry_validated';

export const OPENF1_ATTRIBUTION =
  'Geometry derived from OpenF1 /location telemetry (openf1.org), licensed CC BY-NC-SA 4.0: attribution, non-commercial use, share-alike. It is a driven line — apexes cut, exits run wide — not a surveyed FIA centreline, and openf1.org describes its data as unofficial.';

export const CORRIDOR_UNKNOWN_REASON =
  'The compiled package declares corridor_quality: unknown, so the usable track width is not known at any point. Lateral position, side-by-side state and contact are corridor-derived and are unavailable here — they are not zero.';

export const CORRIDOR_DERIVED_FIELDS: readonly string[] = [
  'lateral position',
  'side-by-side state',
  'contact and wheel-to-wheel claims',
  'usable track width',
];

export const SIMULATION_ELIGIBLE_UNREACHABLE =
  'No circuit reaches simulation_eligible. That rung requires a surveyed corridor, which location telemetry cannot supply, so nothing here is a validated real-track simulation.';

export interface TrackReadinessView {
  readonly reported: TrackReadiness | null;
  readonly fromPackage: TrackReadiness | null;
  readonly fromRegistry: TrackReadiness | null;
}

export function readinessView(track: TrackSummary): TrackReadinessView {
  const fromPackage = track.readiness ?? null;
  const fromRegistry = track.registry_readiness ?? null;
  return { reported: fromPackage ?? fromRegistry, fromPackage, fromRegistry };
}

function rank(rung: TrackReadiness | null): number {
  if (rung === null) {
    return -2;
  }
  if (rung === 'rejected') {
    return -1;
  }
  return READINESS_LADDER.indexOf(rung);
}

export function readinessRank(rung: TrackReadiness | null): number {
  return rank(rung);
}

export function readinessTone(rung: TrackReadiness | null): BadgeTone {
  if (rung === null) {
    return 'failure';
  }
  if (rung === 'rejected') {
    return 'failure';
  }
  if (rung === 'discovered') {
    return 'neutral';
  }
  return 'attention';
}

export interface Selectability {
  readonly selectable: boolean;
  readonly reason: string;
}

function lengthClause(track: TrackSummary): string {
  const measured = track.length_error_fraction ?? null;
  if (measured === null) {
    return '';
  }
  return ` Its recomputed arc length differs from the official length by ${(measured * 100).toFixed(3)} %.`;
}

function serverClause(track: TrackSummary): string {
  const parts = [
    track.unavailable_reason ?? null,
    ...validatorNotes(track).filter((note) => note.startsWith('status ')),
  ].filter((part): part is string => part !== null && part !== '');
  return parts.length === 0 ? '' : ` ${parts.join(' ')}`;
}

export function validatorNotes(track: TrackSummary | null): readonly string[] {
  return track === null ? [] : (track.notes ?? []);
}

export function selectability(track: TrackSummary): Selectability {
  const reported = readinessView(track).reported;
  if (reported === null) {
    return {
      selectable: false,
      reason: `The catalogue reports no readiness rung for this circuit, so it cannot be offered. Readiness is derived from validation evidence and is never assumed.${serverClause(track)}`,
    };
  }
  if (reported === 'rejected') {
    return {
      selectable: false,
      reason: `Rejected by the independent validator; running it would inject geometry the evidence refuses.${serverClause(track)}`,
    };
  }
  if (rank(reported) < rank(MIN_SELECTABLE_RUNG)) {
    return {
      selectable: false,
      reason: (track.package_present ?? false)
        ? `Readiness is ${reported}, below ${MIN_SELECTABLE_RUNG}: the compiled package did not pass every geometry check, so it cannot drive the simulator.${lengthClause(track)}${serverClause(track)}`
        : `Readiness is ${reported}: registry identity only. No compiled package and no hashes exist for this circuit, so there is no geometry to run.${serverClause(track)}`,
    };
  }
  if (!(track.simulation_ready ?? false)) {
    return {
      selectable: false,
      reason: `The catalogue reports readiness ${reported} but does not report this circuit as able to drive the simulator. The two disagree, so it is refused rather than offered on the strength of the rung alone.${serverClause(track)}`,
    };
  }
  return { selectable: true, reason: '' };
}

export function corridorKnown(corridorQuality: string | null): boolean {
  return corridorQuality === 'surveyed' || corridorQuality === 'validated_estimate';
}

export function shortHash(hash: string | null | undefined, digits = 12): string | null {
  if (hash === null || hash === undefined || hash === '') {
    return null;
  }
  const bare = hash.startsWith('sha256:') ? hash.slice('sha256:'.length) : hash;
  return bare.length <= digits ? bare : `${bare.slice(0, digits)}…`;
}

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

export function needsOpenF1Attribution(provenance: string | null): boolean {
  return provenance === 'openf1_location_telemetry';
}

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
