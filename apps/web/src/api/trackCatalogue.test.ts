import { describe, expect, it } from 'vitest';

import { makeFetch } from '../test/testUtils';
import { ApiRequestError } from './errors';
import {
  ShapeMismatchError,
  TrackCatalogueClient,
  catalogueFailureText,
} from './trackCatalogue';

const TRACK = {
  track_id: 'monza',
  display_name: 'Autodromo Nazionale Monza',
  readiness: 'geometry_validated',
  registry_readiness: 'discovered',
};

function centreline(overrides: Record<string, unknown> = {}) {
  return {
    track_id: 'monza',
    package_hash: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    readiness: 'geometry_validated',
    geometry_provenance: 'openf1_location_telemetry',
    corridor_quality: 'unknown',
    length_m: 5793.0,
    source_point_count: 5793,
    sample_spacing_m: 1.0,
    stride_m: 5.0,
    index_stride: 5,
    point_count: 4,
    x_m: [0, 1, 2, 3],
    y_m: [0, 1, 2, 3],
    ...overrides,
  };
}

function clientFor(body: unknown, status = 200) {
  const stub = makeFetch([['', () => ({ status, body })]]);
  return new TrackCatalogueClient({ fetchImpl: stub.fetchImpl });
}

describe('the catalogue client validates against the generated schemas', () => {
  it('reads a well-formed track list', async () => {
    const client = clientFor({ tracks: [TRACK], season: 2026 });
    const catalogue = await client.listTracks();
    expect(catalogue.tracks?.[0]?.track_id).toBe('monza');
    expect(catalogue.season).toBe(2026);
  });

  it('refuses a readiness rung the contract does not define', async () => {
    const client = clientFor({ tracks: [{ ...TRACK, readiness: 'vibes_validated' }] });
    await expect(client.listTracks()).rejects.toBeInstanceOf(ShapeMismatchError);
  });

  it('refuses a track entry with no display name rather than inventing one', async () => {
    const client = clientFor({ tracks: [{ track_id: 'monza' }] });
    await expect(client.listTracks()).rejects.toBeInstanceOf(ShapeMismatchError);
  });

  it('refuses a body that is not a JSON object', async () => {
    const client = clientFor([TRACK]);
    await expect(client.listTracks()).rejects.toBeInstanceOf(ShapeMismatchError);
  });

  it('keeps the wire name for the returned point count', async () => {
    const client = clientFor(centreline());
    const body = await client.getCentreline('monza', 5);
    expect(body.point_count).toBe(4);
    expect(body.source_point_count).toBe(5793);
  });

  it('refuses a centreline whose coordinate arrays disagree in length', async () => {
    const client = clientFor(centreline({ y_m: [0, 1, 2] }));
    await expect(client.getCentreline('monza', 5)).rejects.toThrow(
      /disagree in length \(x_m 4, y_m 3\)/,
    );
  });

  it('refuses a centreline with too few points to close a circuit', async () => {
    const client = clientFor(centreline({ x_m: [0, 1, 2], y_m: [0, 1, 2], point_count: 3 }));
    await expect(client.getCentreline('monza', 5)).rejects.toThrow(/needs at least four/);
  });

  it('refuses a centreline that carries no coordinates at all', async () => {
    const client = clientFor(centreline({ x_m: undefined, y_m: undefined }));
    await expect(client.getCentreline('monza', 5)).rejects.toBeInstanceOf(ShapeMismatchError);
  });

  it('raises a typed control-plane error rather than a shape error on 404', async () => {
    const client = clientFor(
      { error: { code: 'not_found', message: 'no such track', retryable: false, request_id: 'req-1' } },
      404,
    );
    await expect(client.getCentreline('monza', 5)).rejects.toBeInstanceOf(ApiRequestError);
  });
});

describe('catalogueFailureText', () => {
  it('names the route and the shape problem, and substitutes nothing', async () => {
    const client = clientFor({ tracks: [{ ...TRACK, readiness: 'vibes_validated' }] });
    const caught = await client.listTracks().catch((error: unknown) => error);
    const text = catalogueFailureText('GET /api/v1/tracks', caught);
    expect(text).toContain('GET /api/v1/tracks answered with a body this view could not read');
    expect(text).toContain('TrackListResponse');
  });
});
