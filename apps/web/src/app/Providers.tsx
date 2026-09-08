import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, type ReactNode } from 'react';
import { BrowserRouter } from 'react-router';

import { createQueryClient } from '../api/queries';
import { useSessionStore } from '../state/sessionStore';


function PreferenceEffects() {
  const density = useSessionStore((s) => s.view.density);
  const motion = useSessionStore((s) => s.view.motion);

  useEffect(() => {
    document.documentElement.dataset['density'] = density;
  }, [density]);

  useEffect(() => {
    if (motion === 'reduce') {
      document.documentElement.dataset['motion'] = 'reduce';
    } else {
      delete document.documentElement.dataset['motion'];
    }
  }, [motion]);

  return null;
}

export interface ProvidersProps {
  readonly children: ReactNode;
  readonly queryClient?: QueryClient;
  
  readonly withRouter?: boolean;
}

export function Providers({ children, queryClient, withRouter = true }: ProvidersProps) {
  const client = useMemo(() => queryClient ?? createQueryClient(), [queryClient]);
  const inner = (
    <QueryClientProvider client={client}>
      <PreferenceEffects />
      {children}
    </QueryClientProvider>
  );
  return withRouter ? <BrowserRouter>{inner}</BrowserRouter> : inner;
}
