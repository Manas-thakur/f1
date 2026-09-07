import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { AppRoutes } from './app/routes';
import { Providers } from './app/Providers';
import './styles/base.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('missing #root element');
}

createRoot(container).render(
  <StrictMode>
    <Providers>
      <AppRoutes />
    </Providers>
  </StrictMode>,
);
