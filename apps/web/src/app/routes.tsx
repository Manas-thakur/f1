import { Route, Routes } from 'react-router';

import { AppShell } from './AppShell';
import { MarketingLayout } from './MarketingLayout';
import { DriverDisplay } from '../features/driver/DriverDisplay';
import { EngineerConsole } from '../features/engineer/EngineerConsole';
import { ExperimentReport } from '../features/evidence/ExperimentReport';
import { SimulationLab } from '../features/lab/SimulationLab';
import { ModelsView } from '../features/models/ModelsView';
import { ReplayView } from '../features/replay/ReplayView';
import { RulesetView } from '../features/rules/RulesetView';
import { LandingPage } from '../pages/LandingPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { SessionsPage } from '../pages/SessionsPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SimulationLabLandingPage } from '../pages/SimulationLabLandingPage';


export function AppRoutes() {
  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route index element={<LandingPage />} />
        <Route path="simulation-lab" element={<SimulationLabLandingPage />} />
      </Route>

      <Route element={<AppShell />}>
        <Route path="sessions" element={<SessionsPage />} />

        <Route path="sessions/:sessionId/engineer" element={<EngineerConsole />} />

        <Route path="sessions/:sessionId/lab" element={<SimulationLab />} />

        <Route path="sessions/:sessionId/replay" element={<ReplayView />} />

        <Route path="sessions/:sessionId/driver" element={<DriverDisplay />} />

        <Route path="experiments/:experimentId/report" element={<ExperimentReport />} />

        <Route path="rulesets/:rulesetId" element={<RulesetView />} />

        <Route path="models" element={<ModelsView />} />

        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
