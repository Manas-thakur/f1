
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
