# A09/A10/A11 — proposed patches to A12-owned shared code

Nothing under `apps/web/src/components/`, `src/state/`, `src/api/` or
`src/styles/` was modified. Two changes belong there and are proposed here
instead, with the exact patch.

One A12-owned **test** file was edited, out of necessity, and is recorded in
§3 rather than proposed: it asserted that the seven feature routes were
placeholders.

---

## 1. Fold the laboratory routes into `ApiClient`

`src/api/client.ts` covers the routes the shell needed. Six control-plane
routes that A10 and A09 use are missing, so they currently live in
`apps/web/src/features/lab/controlPlane.ts` as a `LabClient` that uses the
**same** `API_BASE`, the same `Idempotency-Key` header contract and the same
`ApiRequestError` / `toApiError` decoding. It is not a second API format; it is
the same one, waiting to be merged.

Apply this and delete `features/lab/controlPlane.ts`, changing the two imports
in `SimulationLab.tsx`, `BranchCompare.tsx`, `ExperimentJobs.tsx` and
`ExperimentReport.tsx`.

```diff
--- a/apps/web/src/api/client.ts
+++ b/apps/web/src/api/client.ts
@@
 import type {
   AcquireLeaseRequest,
   AcquireLeaseResponse,
+  CreateExperimentRequest,
+  CreateSessionResponse,
   DecisionEvidenceResponse,
   DriverActionRequest,
   DriverActionResponse,
+  ExperimentJob,
   ExperimentStatusResponse,
+  ExportJobResponse,
+  JobStatus,
   ModelListResponse,
   RecommendationActionRequest,
   RecommendationActionResponse,
   RulesetResponse,
   SessionCommandRequest,
   SessionCommandResponse,
   SessionListResponse,
+  SessionMode,
   SessionSnapshot,
+  SnapshotReference,
 } from '@contracts';
@@
 export class ApiClient {
+  createSession(
+    body: {
+      mode: SessionMode;
+      scenario_id: string;
+      ruleset_id: string;
+      seed: number;
+      model_bundle_id?: string | null;
+      label?: string | null;
+    },
+    options: RequestOptions,
+  ) {
+    return this.request<CreateSessionResponse>(
+      '/sessions',
+      { method: 'POST', body: JSON.stringify(body) },
+      options,
+    );
+  }
+
+  createSnapshot(
+    sessionId: string,
+    body: { label?: string | null },
+    options: RequestOptions,
+  ) {
+    return this.request<{ snapshot: SnapshotReference }>(
+      `/sessions/${encodeURIComponent(sessionId)}/snapshots`,
+      { method: 'POST', body: JSON.stringify(body) },
+      options,
+    );
+  }
+
+  createExperiment(body: CreateExperimentRequest, options: RequestOptions) {
+    return this.request<{ job: ExperimentJob }>(
+      '/experiments',
+      { method: 'POST', body: JSON.stringify(body) },
+      options,
+    );
+  }
+
+  listExperiments(
+    params: { status?: JobStatus; limit?: number } = {},
+    options?: RequestOptions,
+  ) {
+    const search = new URLSearchParams();
+    if (params.status !== undefined) search.set('status', params.status);
+    if (params.limit !== undefined) search.set('limit', String(params.limit));
+    const qs = search.toString();
+    return this.request<readonly ExperimentStatusResponse[]>(
+      `/experiments${qs === '' ? '' : `?${qs}`}`,
+      { method: 'GET' },
+      options ?? {},
+    );
+  }
+
+  cancelExperiment(
+    experimentId: string,
+    body: { reason: string },
+    options: RequestOptions,
+  ) {
+    return this.request<ExperimentStatusResponse>(
+      `/experiments/${encodeURIComponent(experimentId)}/cancel`,
+      { method: 'POST', body: JSON.stringify(body) },
+      options,
+    );
+  }
+
+  createExport(
+    body: {
+      session_id: string;
+      format: 'json' | 'csv' | 'parquet';
+      start_session_time_s?: number | null;
+      end_session_time_s?: number | null;
+    },
+    options: RequestOptions,
+  ) {
+    return this.request<ExportJobResponse>(
+      '/exports',
+      { method: 'POST', body: JSON.stringify(body) },
+      options,
+    );
+  }
```

`CreateSnapshotRequest`, `CreateSnapshotResponse`, `CreateExperimentResponse`,
`CancelExperimentRequest` and `CreateExportRequest` exist in
`packages/contracts/afterlap_contracts/requests.py` but are **not emitted** into
`packages/contracts/generated/contracts.ts`. Until the generator covers them,
the shapes above are composed from generated members (`SnapshotReference`,
`ExperimentJob`, `ExportJobResponse`, `JobStatus`, `SessionMode`). Regenerating
with those five models included would remove every hand-declared envelope in
this product.

---

## 2. Split `schemas.json` out of the entry chunk

Measured, on this machine, with `pnpm --filter @afterlap/web build`:

| Build | JS bundle | gzip |
|---|---|---|
| A12's shell, seven placeholder routes | 417.31 kB | 138.24 kB |
| This module, seven real routes | 902.70 kB | 237.06 kB |

The increase is almost entirely `packages/contracts/generated/schemas.json`
(515 kB raw). It was already imported by `src/api/validate.ts`, but nothing in
the shell ever imported `SessionStream`, so the bundler dropped it. Every
feature route opens a session stream, so it is now reachable and included.
A12's known limitation 9 anticipated exactly this.

The validator is only needed once a socket opens, so it can be loaded then:

```diff
--- a/apps/web/src/api/validate.ts
+++ b/apps/web/src/api/validate.ts
-import schemas from '@contracts/schemas.json';
+let schemas: SchemaBundle | null = null;
+
+/** Loads the schema bundle. Call once before the first frame is validated. */
+export async function loadSchemas(): Promise<void> {
+  if (schemas === null) {
+    schemas = (await import('@contracts/schemas.json')).default as SchemaBundle;
+  }
+}
```

with `SessionStream.connect()` awaiting `loadSchemas()` before opening the
socket, and `validateEnvelope` returning a typed failure (never a silent pass)
if it is somehow called first. **This was not applied**: it changes an
A12-owned module and the failure mode of the validator, and it needs its own
test proving that an unvalidated frame is never applied. It is a size
optimisation, not a defect.

---

## 3. `src/app/routes.test.tsx` — edited, not proposed

This file asserted that `/sessions/:id/engineer`, `/lab`, `/replay`, `/driver`,
`/experiments/:id/report`, `/rulesets/:id` and `/models` rendered
`FeaturePlaceholder` and named their owning agent. All seven now render real
components, so those two assertions could not survive. Three edits were made,
all minimal:

1. the `feature route placeholders` describe block was replaced with
   `feature routes render their own view`, which asserts the engineer console
   renders its `Decision` panel, the lab its `Run control`, replay its
   `Alignment and cursor` panel and the driver route its primary readout, and
   that no `owned by` text remains anywhere;
2. the `fetch` stub gained handlers for `/snapshot`, `/models` and
   `/experiments` **before** the `/sessions` handler, because the feature views
   read the snapshot route and answering it with a session list handed them a
   structurally wrong snapshot;
3. `SESSION_SNAPSHOT` is imported from `src/test/contractFixtures.ts` for that
   handler.

The route-per-route "exactly one h1 and the three landmarks" tests were left
exactly as they were, and every route still renders the same `h1` text it did
as a placeholder. That block is what proves the swap did not break the shell.

Item 2 also revealed a real defect in my code, which is fixed and covered:
`SourcePanel` read `manifest.mode` after a `null` check, and a malformed
snapshot delivers `undefined`, not `null`. Both that read and
`ExperimentReport`'s job read are now nullish-safe.
