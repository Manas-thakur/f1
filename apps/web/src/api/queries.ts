
import { QueryClient, useQuery } from '@tanstack/react-query';

import { apiClient, type ApiClient } from './client';
import { ApiRequestError } from './errors';

export const IMMUTABLE_QUERY_OPTIONS = {
  staleTime: Number.POSITIVE_INFINITY,
  gcTime: 60 * 60 * 1000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {

          if (error instanceof ApiRequestError) {
            return error.retryable && failureCount < 2;
          }
          return failureCount < 2;
        },
        refetchOnWindowFocus: false,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  });
}

export const queryKeys = {
  sessions: (mode?: string) => ['sessions', mode ?? 'all'] as const,
  snapshot: (sessionId: string) => ['sessions', sessionId, 'snapshot'] as const,
  decision: (decisionId: string) => ['decisions', decisionId] as const,
  ruleset: (rulesetId: string) => ['rulesets', rulesetId] as const,
  models: () => ['models'] as const,
  experiment: (experimentId: string) => ['experiments', experimentId] as const,
} as const;

export function useSessions(mode?: string, client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.sessions(mode),
    queryFn: ({ signal }) =>
      client.listSessions(mode === undefined ? {} : { mode }, { signal }),
  });
}

export function useSessionSnapshot(sessionId: string | undefined, client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.snapshot(sessionId ?? 'none'),
    queryFn: ({ signal }) => client.getSnapshot(sessionId as string, { signal }),
    enabled: sessionId !== undefined,
  });
}

export function useRuleset(rulesetId: string | undefined, client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.ruleset(rulesetId ?? 'none'),
    queryFn: ({ signal }) => client.getRuleset(rulesetId as string, { signal }),
    enabled: rulesetId !== undefined,
    ...IMMUTABLE_QUERY_OPTIONS,
  });
}

export function useModels(client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.models(),
    queryFn: ({ signal }) => client.listModels({ signal }),
    ...IMMUTABLE_QUERY_OPTIONS,
  });
}

export function useExperiment(experimentId: string | undefined, client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.experiment(experimentId ?? 'none'),
    queryFn: ({ signal }) => client.getExperiment(experimentId as string, { signal }),
    enabled: experimentId !== undefined,
  });
}
