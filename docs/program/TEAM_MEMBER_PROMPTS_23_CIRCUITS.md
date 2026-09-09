# AFTERLAP team assignments — 23-circuit completion

Prepared against remote `origin/main` at `ec5733f` on 2026-09-09.

These prompts deliberately keep learning and evaluation under Manas's ownership.
Each teammate works from a fresh branch based on `origin/main`, writes to
disjoint paths, and produces a separate handoff. PR #23
(`chore/root-layout-and-ci`) is excluded because it relocates the repository
and conflicts with all current A16 paths.

## Prompt for Member 1 — 23-circuit data and package pipeline

```text
You own the circuit-source, geometry-package, event-source and conditions-data
completion for AFTERLAP. Work in the repository https://github.com/Manas-thakur/f1
from a fresh branch named feat/all-23-circuit-packages based on origin/main.
At assignment time origin/main is ec5733f. Fetch and verify the current remote
before starting. Do not work from an old local checkout, do not merge or rebase
PR #23 (chore/root-layout-and-ci), and keep all production work under
new_plan/implementation.

Read these before editing:
- new_plan/17_real_tracks_conditions/README.md
- TRACK_REGISTRY_2026.md
- TRACK_DATA_PIPELINE.md
- RACE_CONDITION_MODEL.md
- FACTOR_AND_INFLUENCE.md
- VALIDATION.md
- new_plan/implementation/handoffs/A16-1.md
- A16-2.md, A16-3.md, A16-4.md and decisions.md
- packages/core/afterlap_core/tracks/
- packages/core/afterlap_core/conditions/

Do not believe completion claims in handoffs. Re-run the relevant commands and
inspect the generated packages yourself.

Current verified remote state:
- The registry contains 23 circuits.
- Source manifests exist for only Monza, Monaco, Spa, Suzuka, Singapore and
  Mexico City.
- Monza and Spa are geometry_validated.
- Monaco, Mexico City and Singapore remain discovered because their compiled
  driven-line lengths exceed the currently earned tolerance.
- Suzuka is rejected because z-channel outliers create impossible grades.
- The other 17 registry circuits do not have compiled packages.
- The catalogue API and UI already list all 23, including unavailable states.
- Compiled artifacts are git-ignored and must be reproducible from committed
  source manifests and commands.

Your exclusive write paths:
- new_plan/implementation/packages/core/afterlap_core/tracks/
- new_plan/implementation/packages/core/afterlap_core/conditions/
- new_plan/implementation/configs/tracks/
- new_plan/implementation/configs/conditions/
- new_plan/implementation/tests/tracks/
- new_plan/implementation/tests/conditions/
- new_plan/implementation/scripts/ only for a clearly named all-track build or
  validation command
- new_plan/implementation/handoffs/M23-CIRCUITS.md

Do not edit:
- packages/core/afterlap_core/learning/ or evaluation/
- configs/learning/ or configs/benchmarks/
- apps/api/
- apps/web/
- packages/contracts/
- migrations, generated schemas, root workspace files or presentation files
- simulation/engine.py, policies.py, wake.py or overtake.py; an unmerged A16-6
  implementation exists outside remote main and is owned by the coordinator

The required circuit set is exactly:
melbourne, shanghai, suzuka, miami, montreal, monaco, catalunya, spielberg,
silverstone, spa, hungaroring, zandvoort, monza, madring, baku, sepang,
singapore, austin, mexico-city, interlagos, las-vegas, lusail and yas-marina.

Required work:
1. Refresh the 2026 registry against the current official Formula 1 calendar
   and applicable FIA event documents. Preserve event identity separately from
   physical circuit identity. Record retrieval time, source URL and content
   hash. Resolve suspicious or changed venues explicitly; never copy an old
   circuit identity into a new event.
2. Create a source manifest for every one of the 23 circuits. Each manifest
   must identify usable telemetry sessions/laps, licence, retrieval metadata,
   official-length evidence and known limitations.
3. Use the existing OpenF1 ingestion and compiler. Do not hand-draw centrelines,
   trace map images or insert arrays that merely look correct.
4. Repair the Suzuka elevation channel through a general, tested outlier rule.
   Do not special-case the circuit id and do not flatten genuine elevation.
5. Diagnose length failures for Monaco, Mexico City and Singapore. Improve lap
   selection, timing-line alignment, registration or smoothing where evidence
   supports it. Never relax a tolerance merely to advance readiness.
6. Acquire and compile the remaining 17 circuits. Use multiple clean laps where
   possible. A missing public source must remain a typed source_unavailable
   result with its reason; it must not become a synthetic loop.
7. Add a deterministic batch command that can fetch from an empty cache,
   compile all 23, run independent validation and emit a machine-readable
   readiness matrix. It must support offline reruns from the raw source cache.
8. Ensure each package contains metric centreline coordinates, cumulative
   distance, curvature, grade/elevation, direction, timing line, sector/corner
   metadata where sourced, corridor quality, source records, licence and
   package hash.
9. Add event overlays only from traceable event documents. Unknown FIA power
   curves and unreviewed values remain unknown. Never infer a regulatory number
   from the shape of a chart.
10. Add a coherent condition package for every circuit. Distinguish actual
    historical observations from climatology and synthetic stress tapes.
    A static synthetic tape is allowed only when labelled synthetic and must
    never be described as observed event weather.
11. Make tests use temporary artifact roots. Running tests must never demote or
    mutate the shared artifacts/tracks packages used by another developer.
12. Produce a 23-row completion matrix with registry status, source status,
    package hash, readiness, official-length error, closure error, maximum
    grade, condition tapes and exact refusal reason.

Readiness rules:
- A circuit name in the registry is not implementation completion.
- A compiled map is not geometry validation.
- geometry_validated requires the independent validator to pass.
- Unknown corridor width must remain unknown and disables lateral/contact
  claims.
- Real geometry with synthetic car and battery values must retain the label
  real_circuit_synthetic_energy.
- If source evidence cannot support a circuit, report it as unavailable. Do not
  fabricate completion to reach 23/23.

Acceptance:
- Run ruff check and ruff format --check on owned Python files.
- Run mypy on tracks and conditions.
- Run pytest tests/tracks tests/conditions.
- Run the all-23 batch pipeline once from an empty temporary artifact root and
  once offline from its cache.
- Verify identical inputs produce identical package hashes.
- Verify corrupted cache content, wrong event/circuit pairing, impossible grade,
  open centreline and excessive length error are refused.
- Verify no test writes to the shared real artifact root.

Handoff:
Write new_plan/implementation/handoffs/M23-CIRCUITS.md with changed paths,
source/licence table, commands actually run, exact test results, the complete
23-row readiness matrix, hashes, unresolved source gaps and reproduction
commands. Commit only your owned files, push the branch and open a PR against
main. Do not claim all 23 simulation-ready unless the evidence actually says so.
```

## Prompt for Member 2 — backend, contracts and operational integrity

```text
You own the backend and operational completion of AFTERLAP's 23-circuit
catalogue and session lifecycle. Work in
https://github.com/Manas-thakur/f1 from a fresh branch named
feat/23-circuit-platform based on origin/main. At assignment time origin/main
is ec5733f. Fetch and verify remote state before editing. Do not merge or rebase
PR #23 (chore/root-layout-and-ci).

Read:
- new_plan/00_program/ARCHITECTURE.md
- new_plan/01_contracts/API.md
- new_plan/17_real_tracks_conditions/*
- new_plan/implementation/handoffs/A08.md
- A14.md, A16-8.md, decisions.md and RELEASE_REPORT.md
- apps/api/afterlap_api/routes/catalog.py
- apps/api/afterlap_api/session/circuit.py
- apps/api/afterlap_api/session/factory.py
- migrations and persistence repositories

Verify the running behaviour yourself. A16-8 is merged, but its handoff states
that no new tests were added, so its catalogue/session claims require regression
coverage.

Your exclusive write paths:
- new_plan/implementation/apps/api/
- new_plan/implementation/packages/contracts/
- new_plan/implementation/tests/api/
- new_plan/implementation/tests/backend/
- new_plan/implementation/tests/persistence/
- new_plan/implementation/tests/operations/
- new_plan/implementation/infra/
- new_plan/implementation/scripts/demo.py
- new_plan/implementation/handoffs/M23-PLATFORM.md

You are the only teammate allowed to edit shared contracts, generated schemas
and migrations. Preserve JSON compatibility for the already-merged web client.
Any new response field should be additive and optional unless a contract
revision and migration are justified.

Do not edit:
- tracks/, conditions/ or their config/source manifests
- learning/, evaluation/, configs/learning/ or configs/benchmarks/
- simulation physics, policies, wake or overtake modules
- apps/web/, design files or presentation files

Current remote capabilities:
- GET /api/v1/tracks lists the 23 registry entries and joins available packages.
- Detail, centreline, condition and scenario catalogue routes exist.
- Session creation resolves track, event and condition identities and refuses
  packages below geometry_validated.
- Session rows and snapshots persist circuit identity columns.
- Stream snapshots and exports contain circuit identity and provenance.
- Only Monza and Spa currently pass the minimum geometry readiness.

Required work:
1. Add full regression tests for all A16 catalogue routes: 23-entry listing,
   absent package, discovered, rejected, validated, hash mismatch, centreline
   response, conditions, scenario catalogue and malformed artifacts.
2. Add session-creation tests for valid circuit selection, unknown circuit,
   wrong event/circuit pairing, missing conditions, package below readiness,
   tampered package and synthetic-track compatibility.
3. Add persistence/migration tests proving track, event, conditions and package
   hashes survive restart, snapshot, export and replay.
4. Add stream tests proving initial snapshot and resynchronization carry the
   same circuit identity as REST and storage.
5. Promote catalogue response models from route-local models into the shared
   contracts package without changing their JSON shape. Regenerate JSON Schema
   and TypeScript and run drift tests.
6. Add pagination/filtering only if needed for the 23-item catalogue; preserve a
   single authoritative /api/v1 prefix.
7. Ensure the API reads packages produced by Member 1 without hard-coded ids.
   Missing packages remain listed but cannot start a session.
8. Ensure source URLs, licences, hashes and readiness reasons are serialized,
   while local filesystem paths and secrets are not.
9. Connect planner-duration, observation-age and spool-depth metric callers.
10. Make readiness account for storage/database dependencies and report session
    telemetry health without creating a container restart loop for a paused or
    completed session.
11. Add an observable batch-worker health mechanism.
12. Repair spawned session-worker persistence and session-id ownership, or
    explicitly remove the unsupported out-of-process path from the demo.
13. Add a full API runbook that creates a Monza or Spa session, verifies hashes,
    steps the simulator, receives a recommendation, records selection,
    communication and execution, snapshots, branches, exports and verifies
    replay identity.
14. Preserve the baseline safety path. A learned bundle supplied by Manas must
    pass feature-manifest, environment, circuit-split, ruleset and package-hash
    compatibility checks. Failed compatibility leaves the baseline active.

Non-blocking interface rule:
Build against the package layout and loader already on origin/main. Do not wait
for Member 1's 23 packages and do not invent fixture-only production routes.
Use temporary package fixtures representing absent, discovered, rejected and
validated states. When Member 1's packages arrive, the same generic loader and
tests must accept them without code changes.

Acceptance:
- uv run pytest tests/api tests/backend tests/persistence tests/operations
- contract generation and drift checks
- ruff check and ruff format --check on owned Python files
- mypy on apps/api and packages/contracts
- clean-database migration up/down/up
- Docker Compose startup with PostgreSQL, API, batch worker and web healthy
- scripts/demo.py succeeds through nginx
- no route or log exposes credentials or local artifact paths

Handoff:
Write new_plan/implementation/handoffs/M23-PLATFORM.md with changed paths,
contract revision, migration revision, endpoint table, commands and exact
results, remaining operational limitations and one reproducible demo transcript.
Commit only owned files, push the branch and open a PR against main.
```

## Prompt for Member 3 — 23-circuit product UI, UX and demo

```text
You own the product experience for the complete 23-circuit catalogue. Work in
https://github.com/Manas-thakur/f1 from a fresh branch named
feat/23-circuit-product-ui based on origin/main. At assignment time origin/main
is ec5733f. Fetch and verify the remote before editing. Do not merge or rebase
PR #23 (chore/root-layout-and-ci).

Read:
- new_plan/12_design/DESIGN_SYSTEM.md
- DESIGN_REVISION_02.md
- SCREEN_INVENTORY.md
- UI_ECOSYSTEM_RESEARCH_03.md if present on remote when you start
- new_plan/17_real_tracks_conditions/*
- new_plan/implementation/handoffs/A09-A11.md
- A12.md and A16-9.md
- apps/web/src/api/trackCatalogue.ts
- features/tracks/, features/lab/, features/engineer/ and features/driver/

Inspect the running application and source before changing it. The current
remote already includes a circuit selector, conditions selector, circuit map,
session circuit identity and readiness logic. Extend and verify these surfaces;
do not replace them with a disconnected mockup.

Your exclusive write paths:
- new_plan/implementation/apps/web/
- new_plan/12_design/
- new_plan/presentation/
- new_plan/implementation/handoffs/M23-PRODUCT.md

Do not edit:
- Python packages or tests
- API routes, contracts, migrations or generated backend schemas
- tracks/conditions source manifests
- learning/evaluation code or model artifacts
- root workspace layout

Required work:
1. Make all 23 circuits discoverable through one searchable, keyboard-operable
   selector. Use a compact list/table rather than 23 decorative cards.
2. Show package readiness beside every circuit: unavailable, discovered,
   rejected, geometry_validated or higher. Disable Start session below the
   backend's minimum readiness and display the exact refusal reason.
3. Render maps only from /api/v1/tracks/{id}/centreline. Never use a circuit
   image as driveable geometry and never substitute a generic circuit when data
   is absent.
4. Show official length, compiled length/error, direction, geometry source,
   package hash, corridor quality, condition tape, event overlay and licence in
   progressive detail.
5. Keep registry identity, physical track identity and event identity visibly
   separate, especially for new or relocated events.
6. Add map layers for timing line, sectors, corners, activation zones and
   strategic checkpoints only when their provenance exists. Unknown layers get
   an explicit unavailable state.
7. In Simulation Lab, create a coherent workflow:
   Choose circuit -> inspect readiness -> choose event/conditions -> configure
   scenario -> create session -> run -> snapshot -> branch -> review.
8. In Race Engineer OS, show circuit and conditions in the persistent context,
   keep the recommendation primary, retain source/evidence adjacency and
   synchronize map position with telemetry cursor where the API provides a
   common distance coordinate.
9. In Driver Display, show only circuit, lap, checkpoint, instruction, trigger,
   end condition and energy target. Do not turn it into a telemetry dashboard.
10. Preserve real_circuit_synthetic_energy everywhere a real centreline is
    combined with synthetic vehicle/battery truth.
11. Build honest states for missing package, rejected geometry, stale
    conditions, unreviewed event overlay, unknown corridor and unavailable
    learned model.
12. Verify long circuit/event names and all 23 rows at 320, 375, 414, 768,
    1024, 1440 and 1920 px. No page-level horizontal overflow and no wrapped
    button/nav labels.
13. Add unit/component tests for catalogue normalization and readiness
    behaviour, plus Playwright tests for selector keyboard operation, route
    loading, disabled session creation, validated session creation, map
    accessibility, driver glance hierarchy and axe serious/critical findings.
14. Add visual regression references for representative states: Monza
    validated, Spa validated/elevation, Suzuka rejected, one circuit without a
    package, unknown corridor and unavailable conditions.
15. Update the landing page to say 23-circuit catalogue only when the catalogue
    is actually connected. Do not claim 23 simulation-ready circuits until the
    readiness matrix supports it.
16. Update PowerPoint screenshots, architecture labels, speaker notes and demo
    sequence after the integrated API is available. Do not invent RL gains,
    win rates or policy-promotion claims; Manas owns those results.

Non-blocking interface rule:
Use the current merged track-catalogue JSON shape. Member 2 may move those
models into shared contracts but must preserve JSON compatibility. Develop all
readiness states with contract-shaped test fixtures while production routes
continue to call the real API. You do not need to wait for Member 1 to finish
all packages; newly available packages must appear automatically from the
catalogue response.

Acceptance:
- pnpm --filter @afterlap/web typecheck
- pnpm --filter @afterlap/web test
- pnpm --filter @afterlap/web build
- pnpm --filter @afterlap/web test:e2e
- axe-core: zero serious and zero critical findings
- every product route checked across the seven supported widths
- keyboard-only circuit selection and session creation
- screenshots from the real built application, not isolated design HTML

Handoff:
Write new_plan/implementation/handoffs/M23-PRODUCT.md with changed paths,
screen/state inventory, commands and exact results, screenshots, remaining API
gaps and the final demo route sequence. Commit only owned files, push the
branch and open a PR against main.
```

## Manas — retained learning ownership

Manas exclusively owns:

- `packages/core/afterlap_core/learning/`
- `packages/core/afterlap_core/evaluation/`
- `configs/learning/`
- `configs/benchmarks/`
- `tests/learning/`
- `tests/evaluation/`
- trained bundles, model cards and promotion evidence

The three teammates must not change these paths. Member 1 supplies immutable
circuit/environment packages, Member 2 supplies compatibility and serving
boundaries, and Member 3 displays only measured model status and results.

## Integration order

1. Keep local uncommitted A16-6 traffic/wake work separate from all three
   branches; review and merge it independently.
2. Merge Member 2's contract-only JSON-preserving changes before any optional
   frontend type regeneration.
3. Member 1, Member 2 and Member 3 otherwise work concurrently.
4. Merge Member 1's package pipeline; regenerate all available local packages.
5. Manas freezes the 23-circuit train/calibration/held-out split from package
   hashes and performs training/evaluation.
6. Merge Member 3's final measured-result and presentation update only after
   Manas publishes the evaluation artifacts.
7. Run the complete Python, web, browser, Compose and demo gates on integrated
   `main`.
