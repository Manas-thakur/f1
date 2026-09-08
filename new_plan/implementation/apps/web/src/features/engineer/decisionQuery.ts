/**
 * The decision evidence read.
 *
 * `GET /decisions/{id}` returns the recommendation together with its operator
 * events and observed executions. That record is the immutable timeline; the
 * console never assembles one from what it happened to see on the socket.
 */
import { useQuery } from '@tanstack/react-query';

import { apiClient, type ApiClient } from '@/api/client';
import { queryKeys } from '@/api/queries';

export function useDecision(decisionId: string | null, client: ApiClient = apiClient) {
  return useQuery({
    queryKey: queryKeys.decision(decisionId ?? 'none'),
    queryFn: ({ signal }) => client.getDecision(decisionId as string, { signal }),
    enabled: decisionId !== null,
    staleTime: 2_000,
  });
}
