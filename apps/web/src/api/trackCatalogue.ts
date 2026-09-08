import { API_BASE, type RequestOptions } from '@/api/client';
import { ApiRequestError, isApiErrorResponse, toApiError } from '@/api/errors';


export type ReadinessRung =
  | 'discovered'
  | 'geometry_validated'
  | 'event_rules_validated'
  | 'condition_calibrated'
  | 'simulation_eligible'
  | 'rejected';

export const READINESS_LADDER: readonly ReadinessRung[] = [
  'discovered',
  'geometry_validated',
  'event_rules_validated',
  'condition_calibrated',
  'simulation_eligible',
];

export function isReadinessRung(value: string): value is ReadinessRung {
  return value === 'rejected' || (READINESS_LADDER as readonly string[]).includes(value);
}


export interface TrackCatalogueEntry {
  readonly track_id: string;
  readonly display_name: string | null;
  readonly country: string | null;

  readonly readiness: ReadinessRung | null;
  readonly readiness_reported: string | null;
  readonly package_readiness: string | null;
  readonly registry_readiness: string | null;

  readonly package_present: boolean;
  readonly package_hash: string | null;
  readonly arrays_sha256: string | null;
  readonly geometry_provenance: string | null;
  readonly corridor_quality: string | null;
  readonly lateral_geometry_surveyed: boolean | null;

  readonly nominal_length_m: number | null;
  readonly official_length_m: number | null;
  readonly official_length_verified: boolean;
  readonly point_count: number | null;
  readonly sample_spacing_m: number | null;
  readonly closure_error_m: number | null;
  readonly length_error_fraction: number | null;

  readonly licence_labels: readonly string[];
  readonly event_ids: readonly string[];
  readonly event_overlay_ids: readonly string[];

  readonly simulation_ready: boolean;
  readonly unavailable_reason: string | null;
  readonly notes: readonly string[];
}

export interface TrackCatalogue {
  readonly tracks: readonly TrackCatalogueEntry[];
  readonly minimum_readiness_to_drive: string | null;
  readonly notice: string | null;
  readonly season: number | null;
  readonly snapshot_date: string | null;
}

export interface CentrelineResponse {
  readonly track_id: string;
  readonly package_hash: string | null;
  readonly arrays_sha256: string | null;
  readonly readiness: string | null;
  readonly geometry_provenance: string | null;
  readonly corridor_quality: string | null;
  readonly length_m: number | null;
  readonly source_point_count: number | null;
  readonly returned_point_count: number | null;
  readonly sample_spacing_m: number | null;
  readonly stride_m: number | null;
  readonly notice: string | null;
  readonly x_m: readonly number[];
  readonly y_m: readonly number[];
}

export interface ConditionsCatalogueEntry {
  readonly conditions_id: string;
  readonly description: string | null;
  readonly source: string | null;
  readonly available: boolean;
  readonly content_hash: string | null;
  readonly rainfall_minutes: number | null;
  readonly sample_count: number | null;
  readonly duration_s: number | null;
  readonly session_key: number | null;
  readonly altitude_m: number | null;
  readonly altitude_source: string | null;
  readonly permission: string | null;
  readonly retrieved_at: string | null;
  readonly gust_enabled: boolean;
  readonly unavailable_reason: string | null;
}

export interface ConditionsCatalogue {
  readonly conditions: readonly ConditionsCatalogueEntry[];
  readonly notice: string | null;
}

export interface ScenarioCatalogueEntry {
  readonly scenario_id: string;
  readonly description: string | null;
  readonly track_id: string | null;
  readonly conditions_id: string | null;
  readonly event_id: string | null;
  readonly synthetic: boolean | null;
  readonly status_note: string | null;
  readonly rule_pack: string | null;
  readonly duration_s: number | null;
  readonly seed: number | null;
  readonly real_circuit: boolean;
  readonly track_readiness: string | null;
  readonly track_package_hash: string | null;
  readonly run_label: string | null;
  readonly unavailable_reason: string | null;
}

export interface ScenarioCatalogue {
  readonly scenarios: readonly ScenarioCatalogueEntry[];
  readonly notice: string | null;
}


export type DecodeResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly problem: string };

type Obj = Record<string, unknown>;

function asObject(value: unknown): Obj | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Obj)
    : null;
}

function str(source: Obj, key: string): string | null {
  const value = source[key];
  return typeof value === 'string' && value !== '' ? value : null;
}

function num(source: Obj, key: string): number | null {
  const value = source[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function flag(source: Obj, key: string): boolean | null {
  const value = source[key];
  return typeof value === 'boolean' ? value : null;
}

function strList(source: Obj, key: string): readonly string[] {
  const value = source[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === 'string');
}

function numArray(source: Obj, key: string): readonly number[] | null {
  const value = source[key];
  if (!Array.isArray(value)) {
    return null;
  }
  const out: number[] = [];
  for (const entry of value) {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      return null;
    }
    out.push(entry);
  }
  return out;
}

function decodeTrackEntry(raw: unknown, index: number): DecodeResult<TrackCatalogueEntry> {
  const source = asObject(raw);
  if (source === null) {
    return { ok: false, problem: `tracks[${index}] is not a JSON object` };
  }
  const trackId = str(source, 'track_id');
  if (trackId === null) {
    return { ok: false, problem: `tracks[${index}] has no track_id string` };
  }
  const packageReadiness = str(source, 'readiness');
  const registryReadiness = str(source, 'registry_readiness');
  const reported = packageReadiness ?? registryReadiness;
  return {
    ok: true,
    value: {
      track_id: trackId,
      display_name: str(source, 'display_name'),
      country: str(source, 'country'),
      readiness: reported !== null && isReadinessRung(reported) ? reported : null,
      readiness_reported: reported,
      package_readiness: packageReadiness,
      registry_readiness: registryReadiness,
      package_present: flag(source, 'package_present') ?? false,
      package_hash: str(source, 'package_hash'),
      arrays_sha256: str(source, 'arrays_sha256'),
      geometry_provenance: str(source, 'geometry_provenance'),
      corridor_quality: str(source, 'corridor_quality'),
      lateral_geometry_surveyed: flag(source, 'lateral_geometry_surveyed'),
      nominal_length_m: num(source, 'nominal_length_m'),
      official_length_m: num(source, 'official_length_m'),
      official_length_verified: flag(source, 'official_length_verified') ?? false,
      point_count: num(source, 'point_count'),
      sample_spacing_m: num(source, 'sample_spacing_m'),
      closure_error_m: num(source, 'closure_error_m'),
      length_error_fraction: num(source, 'length_error_fraction'),
      licence_labels: strList(source, 'licence_labels'),
      event_ids: strList(source, 'event_ids'),
      event_overlay_ids: strList(source, 'event_overlay_ids'),
      simulation_ready: flag(source, 'simulation_ready') ?? false,
      unavailable_reason: str(source, 'unavailable_reason'),
      notes: strList(source, 'notes'),
    },
  };
}

export function decodeTrackList(raw: unknown): DecodeResult<TrackCatalogue> {
  const body = asObject(raw);
  if (body === null) {
    return { ok: false, problem: 'GET /tracks did not return a JSON object' };
  }
  const list = body['tracks'];
  if (!Array.isArray(list)) {
    return { ok: false, problem: 'GET /tracks returned no `tracks` array' };
  }
  const entries: TrackCatalogueEntry[] = [];
  for (let index = 0; index < list.length; index += 1) {
    const decoded = decodeTrackEntry(list[index], index);
    if (!decoded.ok) {
      return decoded;
    }
    entries.push(decoded.value);
  }
  return {
    ok: true,
    value: {
      tracks: entries,
      minimum_readiness_to_drive: str(body, 'minimum_readiness_to_drive'),
      notice: str(body, 'notice'),
      season: num(body, 'season'),
      snapshot_date: str(body, 'snapshot_date'),
    },
  };
}

export function decodeCentreline(raw: unknown): DecodeResult<CentrelineResponse> {
  const body = asObject(raw);
  if (body === null) {
    return { ok: false, problem: 'the centreline route did not return a JSON object' };
  }
  const trackId = str(body, 'track_id');
  if (trackId === null) {
    return { ok: false, problem: 'the centreline response has no track_id string' };
  }
  const x = numArray(body, 'x_m');
  const y = numArray(body, 'y_m');
  if (x === null || y === null) {
    return {
      ok: false,
      problem: 'the centreline response has no finite `x_m` and `y_m` number arrays',
    };
  }
  if (x.length !== y.length) {
    return {
      ok: false,
      problem: `the centreline arrays disagree in length (x_m ${x.length}, y_m ${y.length})`,
    };
  }
  if (x.length < 4) {
    return {
      ok: false,
      problem: `the centreline response carries ${x.length} points; a closed circuit needs at least four`,
    };
  }
  return {
    ok: true,
    value: {
      track_id: trackId,
      package_hash: str(body, 'package_hash'),
      arrays_sha256: str(body, 'arrays_sha256'),
      readiness: str(body, 'readiness'),
      geometry_provenance: str(body, 'geometry_provenance'),
      corridor_quality: str(body, 'corridor_quality'),
      length_m: num(body, 'length_m'),
      source_point_count: num(body, 'source_point_count'),
      returned_point_count: num(body, 'point_count'),
      sample_spacing_m: num(body, 'sample_spacing_m'),
      stride_m: num(body, 'stride_m'),
      notice: str(body, 'notice'),
      x_m: x,
      y_m: y,
    },
  };
}

export function decodeConditionsList(raw: unknown): DecodeResult<ConditionsCatalogue> {
  const body = asObject(raw);
  if (body === null) {
    return { ok: false, problem: 'GET /conditions did not return a JSON object' };
  }
  const list = body['conditions'];
  if (!Array.isArray(list)) {
    return { ok: false, problem: 'GET /conditions returned no `conditions` array' };
  }
  const entries: ConditionsCatalogueEntry[] = [];
  for (let index = 0; index < list.length; index += 1) {
    const source = asObject(list[index]);
    if (source === null) {
      return { ok: false, problem: `conditions[${index}] is not a JSON object` };
    }
    const id = str(source, 'conditions_id');
    if (id === null) {
      return { ok: false, problem: `conditions[${index}] has no conditions_id string` };
    }
    entries.push({
      conditions_id: id,
      description: str(source, 'description'),
      source: str(source, 'source'),
      available: flag(source, 'available') ?? false,
      content_hash: str(source, 'content_hash'),
      rainfall_minutes: num(source, 'rainfall_minutes'),
      sample_count: num(source, 'sample_count'),
      duration_s: num(source, 'duration_s'),
      session_key: num(source, 'session_key'),
      altitude_m: num(source, 'altitude_m'),
      altitude_source: str(source, 'altitude_source'),
      permission: str(source, 'permission'),
      retrieved_at: str(source, 'retrieved_at'),
      gust_enabled: flag(source, 'gust_enabled') ?? false,
      unavailable_reason: str(source, 'unavailable_reason'),
    });
  }
  return { ok: true, value: { conditions: entries, notice: str(body, 'notice') } };
}

export function decodeScenarioList(raw: unknown): DecodeResult<ScenarioCatalogue> {
  const body = asObject(raw);
  if (body === null) {
    return { ok: false, problem: 'GET /scenarios did not return a JSON object' };
  }
  const list = body['scenarios'];
  if (!Array.isArray(list)) {
    return { ok: false, problem: 'GET /scenarios returned no `scenarios` array' };
  }
  const entries: ScenarioCatalogueEntry[] = [];
  for (let index = 0; index < list.length; index += 1) {
    const source = asObject(list[index]);
    if (source === null) {
      return { ok: false, problem: `scenarios[${index}] is not a JSON object` };
    }
    const id = str(source, 'scenario_id');
    if (id === null) {
      return { ok: false, problem: `scenarios[${index}] has no scenario_id string` };
    }
    entries.push({
      scenario_id: id,
      description: str(source, 'description'),
      track_id: str(source, 'track_id'),
      conditions_id: str(source, 'conditions_id'),
      event_id: str(source, 'event_id'),
      synthetic: flag(source, 'synthetic'),
      status_note: str(source, 'status_note'),
      rule_pack: str(source, 'rule_pack'),
      duration_s: num(source, 'duration_s'),
      seed: num(source, 'seed'),
      real_circuit: flag(source, 'real_circuit') ?? false,
      track_readiness: str(source, 'track_readiness'),
      track_package_hash: str(source, 'track_package_hash'),
      run_label: str(source, 'run_label'),
      unavailable_reason: str(source, 'unavailable_reason'),
    });
  }
  return { ok: true, value: { scenarios: entries, notice: str(body, 'notice') } };
}


export class ShapeMismatchError extends Error {
  constructor(problem: string) {
    super(problem);
    this.name = 'ShapeMismatchError';
  }
}

type FetchLike = typeof fetch;

export interface TrackCatalogueClientOptions {
  readonly base?: string;
  readonly fetchImpl?: FetchLike;
}

export class TrackCatalogueClient {
  private readonly base: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: TrackCatalogueClientOptions = {}) {
    this.base = options.base ?? API_BASE;
    this.fetchImpl = options.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  private async read<T>(
    path: string,
    decode: (raw: unknown) => DecodeResult<T>,
    options: RequestOptions,
  ): Promise<T> {
    const headers = new Headers({ Accept: 'application/json' });
    const init: RequestInit = { method: 'GET', headers };
    if (options.signal !== undefined) {
      init.signal = options.signal;
    }

    const response = await this.fetchImpl(`${this.base}${path}`, init);
    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      const apiError = isApiErrorResponse(body)
        ? toApiError(body, response.statusText)
        : toApiError(null, `${response.status} ${response.statusText}`);
      throw new ApiRequestError(response.status, apiError);
    }

    const decoded = decode(await response.json());
    if (!decoded.ok) {
      throw new ShapeMismatchError(decoded.problem);
    }
    return decoded.value;
  }

  listTracks(options: RequestOptions = {}) {
    return this.read('/tracks', decodeTrackList, options);
  }

  getCentreline(trackId: string, strideM: number, options: RequestOptions = {}) {
    const search = new URLSearchParams({ stride_m: String(strideM) });
    return this.read(
      `/tracks/${encodeURIComponent(trackId)}/centreline?${search.toString()}`,
      decodeCentreline,
      options,
    );
  }

  listConditions(options: RequestOptions = {}) {
    return this.read('/conditions', decodeConditionsList, options);
  }

  listScenarios(options: RequestOptions = {}) {
    return this.read('/scenarios', decodeScenarioList, options);
  }
}

export const trackCatalogueClient = new TrackCatalogueClient();

export function catalogueFailureText(route: string, error: unknown): string {
  if (error instanceof ShapeMismatchError) {
    return `${route} answered with a body this view could not read: ${error.message}.`;
  }
  if (error instanceof ApiRequestError) {
    if (error.code === 'not_found' || error.status === 404) {
      return `${route} answered ${error.status} ${error.code}: ${error.apiError.message} Nothing is substituted for it.`;
    }
    return `${route} failed: ${error.apiError.message} (${error.code}, request ${error.requestId}).`;
  }
  if (error instanceof Error) {
    return `${route} could not be reached: ${error.message}.`;
  }
  return `${route} could not be reached and reported no reason.`;
}
