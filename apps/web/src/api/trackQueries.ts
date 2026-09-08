import { useQuery } from '@tanstack/react-query';

import { IMMUTABLE_QUERY_OPTIONS } from './queries';
import { trackCatalogueClient, type TrackCatalogueClient } from './trackCatalogue';

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
