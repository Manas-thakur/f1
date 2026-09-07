import { Route, Routes } from 'react-router';

import { AppShell } from './AppShell';
import { MarketingLayout } from './MarketingLayout';
import { FeaturePlaceholder } from '../pages/FeaturePlaceholder';
import { LandingPage } from '../pages/LandingPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { SessionsPage } from '../pages/SessionsPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SimulationLabLandingPage } from '../pages/SimulationLabLandingPage';

/**
 * The complete route table from SCREEN_INVENTORY.
 *
 * Routes owned by another agent render `FeaturePlaceholder`, which names the
 * owner and the feature directory. Replacing one of those elements is the only
 * change a feature agent needs to make here.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route index element={<LandingPage />} />
        <Route path="simulation-lab" element={<SimulationLabLandingPage />} />
      </Route>

      <Route element={<AppShell />}>
        <Route path="sessions" element={<SessionsPage />} />

        <Route
          path="sessions/:sessionId/engineer"
          element={
            <FeaturePlaceholder
              title="Engineer console"
              owner="A09"
              ownerScope="engineer console"
              artefact="recommendation panel, battle view, energy timeline, decision history and evidence inspector"
              description="One instruction with its trigger, end condition, channels, rule results and decision history."
              featurePath="apps/web/src/features/engineer/"
            />
          }
        />

        <Route
          path="sessions/:sessionId/lab"
          element={
            <FeaturePlaceholder
              title="Simulation lab"
              owner="A10"
              ownerScope="simulation lab and replay"
              artefact="scenario configuration, snapshot controls and branch comparison"
              description="Configure a scenario, snapshot it, branch treatments from that snapshot and compare them."
              featurePath="apps/web/src/features/lab/"
            />
          }
        />

        <Route
          path="sessions/:sessionId/replay"
          element={
            <FeaturePlaceholder
              title="Replay"
              owner="A10"
              ownerScope="simulation lab and replay"
              artefact="aligned trajectory traces on the shared cursor"
              description="Side-by-side trajectories on one shared cursor, aligned by distance or session time."
              featurePath="apps/web/src/features/replay/"
            />
          }
        />

        <Route
          path="sessions/:sessionId/driver"
          element={
            <FeaturePlaceholder
              title="Driver display"
              owner="A11"
              ownerScope="driver display"
              artefact="simulator instruction lifecycle and withdrawal display"
              description="A dedicated dark, high-contrast screen for the simulator driver. Simulator sessions only."
              featurePath="apps/web/src/features/driver/"
            />
          }
        />

        <Route
          path="experiments/:experimentId/report"
          element={
            <FeaturePlaceholder
              title="Experiment report"
              owner="A09"
              ownerScope="evidence views"
              artefact="benchmark report, missing measurements and audit detail"
              description="The benchmark schema, what was measured, what was not, and the audit trail."
              featurePath="apps/web/src/features/evidence/"
            />
          }
        />

        <Route
          path="rulesets/:rulesetId"
          element={
            <FeaturePlaceholder
              title="Ruleset"
              owner="A09"
              ownerScope="evidence views"
              artefact="source-linked rule coverage rows and unsupported conditions"
              description="Which conditions the loaded ruleset covers, with sources, and which it does not."
              featurePath="apps/web/src/features/evidence/"
            />
          }
        />

        <Route
          path="models"
          element={
            <FeaturePlaceholder
              title="Models"
              owner="A09"
              ownerScope="evidence views"
              artefact="model manifests with measured approval state"
              description="Candidate and approved model bundles, distinguished by measured benchmark results."
              featurePath="apps/web/src/features/evidence/"
            />
          }
        />

        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
