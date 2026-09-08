/**
 * TanStack Query bindings for the real-circuit catalogue.
 *
 * A compiled track package is hash-pinned and immutable, so its centreline is
 * cached with the immutable options already used for rulesets and models. The
 * catalogue listings are slow-moving rather than immutable: a package can be
 * recompiled and revalidated between requests, and a stale readiness rung must
 * not be shown as current.
 *
 * Retries follow the shared client's rule: a typed, non-retryable error (an
 * uncompiled circuit, a body that failed to decode) is a decision, not a
 * transient fault, and the views render it.
 */
import { useQuery } from '@tanstack/react-query';

import { IMMUTABLE_QUERY_OPTIONS } from './queries';
import { trackCatalogueClient, type TrackCatalogueClient } from './trackCatalogue';

/**
 * Requested centreline stride in metres.
 *
 * The compiled packages are stored at 1 m spacing, so 5 m returns roughly
 * 1150 points for Monza and 1400 for Spa: enough for a faithful plan view
 * without shipping the dense array to the browser. The server decides what it
 * actually returns and reports the stride it used.
 */
export const MAP_STRIDE_M = 5;

export const trackQueryKeys = {
  tracks: () => ['tracks'] as const,
  centreline: (trackId: string, strideM: number) =>
    ['tracks', trackId, 'centreline', strideM] as const,
  conditions: () => ['conditions'] as const,
  scenarios: () => ['scenarios'] as const,
} as const;

const CATALOGUE_OPTIONS = {
  staleTime: 60_000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

export function useTrackCatalogue(client: TrackCatalogueClient = trackCatalogueClient) {
  return useQuery({
    queryKey: trackQueryKeys.tracks(),
    queryFn: ({ signal }) => client.listTracks({ signal }),
    ...CATALOGUE_OPTIONS,
  });
}

export function useTrackCentreline(
  trackId: string | null,
  client: TrackCatalogueClient = trackCatalogueClient,
  strideM: number = MAP_STRIDE_M,
) {
  return useQuery({
    queryKey: trackQueryKeys.centreline(trackId ?? 'none', strideM),
    queryFn: ({ signal }) => client.getCentreline(trackId as string, strideM, { signal }),
    enabled: trackId !== null && trackId !== '',
    ...IMMUTABLE_QUERY_OPTIONS,
  });
}

/**
 * The conditions catalogue.
 *
 * `enabled` is gated on a circuit being chosen, because a tape carries the
 * venue's altitude and an absolute wind heading and is only meaningful bound
 * to one circuit. The route itself takes no circuit filter, so none is sent.
 */
export function useConditionsCatalogue(
  trackId: string | null,
  client: TrackCatalogueClient = trackCatalogueClient,
) {
  return useQuery({
    queryKey: trackQueryKeys.conditions(),
    queryFn: ({ signal }) => client.listConditions({ signal }),
    enabled: trackId !== null && trackId !== '',
    ...CATALOGUE_OPTIONS,
  });
}

export function useScenarioCatalogue(client: TrackCatalogueClient = trackCatalogueClient) {
  return useQuery({
    queryKey: trackQueryKeys.scenarios(),
    queryFn: ({ signal }) => client.listScenarios({ signal }),
    ...CATALOGUE_OPTIONS,
  });
}
