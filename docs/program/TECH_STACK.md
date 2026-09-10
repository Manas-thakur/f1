# Selected technology stack

This is the implementation decision, not a list of alternatives. All production paths are at the repository root. A01 owns dependency selection and locks. Numeric major lines below are compatibility targets, not claims of latest versions; freeze released compatible patch versions only after the G0 installation spike.

## Components

| Layer | Choice | Purpose |
|---|---|---|
| Python | CPython 3.12, uv workspace | One scientific runtime and frozen dependency graph. |
| Web tooling | Bun 1.3 | Install and run the Next.js app. |
| Interface | React 19, strict TypeScript, Next.js App Router | Operational routes, static product pages, and `/api/v1` on one origin. |
| Server state | TanStack Query | REST snapshots, mutation status and cache invalidation. |
| Live view state | Zustand | Bounded telemetry buffers, cursor, selected channels and connection sequence. |
| Styling | CSS Modules, semantic HTML; Radix Dialog/Popover | Custom instruments with accessible complex controls. No imported dashboard theme. |
| Charts | uPlot; SVG track view | Linked numeric traces and circuit position. Provide accessible numeric summaries. |
| API | Next.js Route Handlers invoking `python -m afterlap_api.cli` | Public HTTP/SSE control plane. Python owns session runtime, numerics and persistence through the CLI. |
| Contracts | Pydantic → JSON Schema/OpenAPI → openapi-typescript; Ajv | One schema authority, generated types and runtime event validation. |
| Numerics | NumPy, float64 physics | Dynamics, filters, likelihoods and reference checks. SciPy is needed only for track ingestion and ships in the `track-ingestion` group. |
| Planner | CasADi, IPOPT | Symbolic dynamics and continuous optimal-control subproblems. Discrete tactics stay in the outer enumerator. acados is not built on this platform; see `infra/README.md` D-02. |
| ML/RL | PyTorch 2, Gymnasium, Stable-Baselines3 SAC | Continuous policy training and separate ordinary-return estimator. |
| Database | PostgreSQL 17, SQLAlchemy 2, Alembic, psycopg 3 | Transactional events, commands, leases, outbox and manifests. |
| Trajectories | PyArrow Parquet | Columnar recordings, installed by the `data` dependency group. |
| Model artifacts | Local content-addressed filesystem | Weights/reports keyed by SHA-256; database holds references. |
| Tests | pytest, Hypothesis, Vitest, Testing Library, Playwright, axe-core | Numerical invariants, contracts, component state and connected browser workflows. |
| Static checks | Ruff, mypy, ESLint, TypeScript compiler | Authored-code quality and type correctness. |
| Packaging | Compose, Linux numerical image, Next.js | Reproducible local product with same-origin API/SSE routing. |
| Diagnostics | JSON logging, TensorBoard | Correlated operational metrics and offline training traces; no cloud account required. `/metrics` serves JSON, not the Prometheus text format. |

## Canonical source paths

Use uv members `packages/contracts`, `packages/core`, `packages/application`, `packages/infrastructure` and `apps/api`, each with a pyproject. Root owns dev tools and workspace configuration. Use direct Python package layout:

```text
packages/contracts/afterlap_contracts/   # authoritative Pydantic models
packages/contracts/generated/           # JSON schemas and TypeScript output
packages/core/afterlap_core/
  data/ simulation/ rules/ estimation/ planning/ learning/
packages/application/afterlap_application/  # session runtime ports and process spawn
packages/infrastructure/afterlap_infrastructure/  # persistence adapters
apps/api/afterlap_api/                   # CLI and session runtime
workers/                                # thin process launchers importing packages
apps/web/src/
  app/                                  # Next.js layouts, pages and route handlers
  views/                                # route-level screens imported by app/
  features/                             # owned feature views
  components/ state/ api/ styles/ shell/
configs/ infra/ tests/ artifacts/ docs/handoffs/
```

Older briefs' `packages/core/<module>/` names are logical scopes. Their canonical importable path is `packages/core/afterlap_core/<module>/`. A01 includes this mapping in assignments. Do not create both trees. A01 owns locks, migrations, schemas and shared Next.js routes; workers own isolated features and tests.

## Process model

Start with one Next.js process as the public HTTP server and one Python runtime process supervising one session process per active operational simulation, using multiprocessing spawn and bounded typed queues. Next.js invokes Python through `python -m afterlap_api.cli request` and `python -m afterlap_api.cli stream`. Commands carry ID, session revision, deadline and immutable payload; results repeat the correlation fields. No physics or solver work inside the Next.js process. Use only project-created processes; expose no network pickle endpoint.

The session process serialises observed state and driver inputs. It accepts a solver result only while its state/rule revisions remain current. The API atomically checks operator authority and appends committed lifecycle events plus transactional outbox records. Delivery is at least once; consumers deduplicate sequence/event ID. The database owns durable operator actions; the session worker owns current dynamics. Reconcile the last applied sequence after restart. Test crash-after-commit-before-delivery explicitly.

Batch workers claim jobs through database leases and `FOR UPDATE SKIP LOCKED`. They never consume session queues or occupy reserved runtime cores. Polling control-plane jobs is acceptable; polling the database at physics frequency is not. No Redis, Kafka, Celery or Kubernetes in this release. Add infrastructure only after measuring a limitation and revising the architecture.

## Solver and hardware build

Build acados from a pinned commit; record compiler, CMake, flags and CasADi version. Hash generated solver code against dynamics, horizon and configuration. G0 must solve a small constrained OCP with a known answer inside the packaged Linux image. Do this before planner agents assume native availability.

On Windows, use Docker Desktop's Linux backend for the canonical numerical runtime. Native Python may run contracts and lightweight tests; it is not a second certified solver target. GPU training has a separate image with a compatible PyTorch/CUDA build. CPU training/evaluation must also work. Never silently replace the specified solver with a stub to pass startup; expose unavailable and fix the build.

## Frontend data handling

REST loads metadata and snapshots. SSE events resume from last sequence; a gap triggers a fresh snapshot. Ajv validates envelopes before state updates. Keep a bounded visible telemetry window; decimate numeric traces while preserving extrema and event annotations. Exact inspection uses original samples. Do not push every telemetry sample through the REST query cache.

One shared replay cursor identifies either distance or session time; changing alignment is explicit. Channel registry defines name, unit, colour, scale and provenance. Commands carry expected revision and idempotency key. Pending submission disables duplicates. A conflict refreshes evidence; it does not silently retry a stale decision. Do not optimistically mark execution as observed.

## Storage and local deployment

Compose supplies db, runtime, web and batch services plus a migration job. The Python runtime supervises session processes. Next.js is the public HTTP origin for pages, `/api/v1` and SSE. Separate volumes store database, trajectories and models. Private source credentials never enter exports.

Use role-scoped session credentials and a single operator lease. Development bootstrap works only in local development mode; no default production secret. Debug truth is a separate restricted endpoint. Driver communication works only in simulator mode. Load only locally produced, hash-verified approved model bundles; do not accept arbitrary pickle uploads.

## Dependency freeze and commands

A01 writes `infra/dependency-baseline.md` with versions, official compatibility requirements and spike evidence. Generate `uv.lock` and `bun.lock`; thereafter install frozen. Do not install prereleases merely because an official documentation page tracks master. Regenerate schemas in CI and fail on drift.

A01 implements these command contracts:

```text
uv sync --frozen --all-packages
bun install --frozen-lockfile
uv run python -m afterlap_core.cli doctor
uv run python -m afterlap_api.cli serve
bun run --filter @afterlap/web dev
uv run pytest tests/contracts tests/numerics
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

Doctor checks manifests, writable artifact storage and numerical solver availability without printing secrets. Compose acceptance requires a working closed-loop synthetic session, not just healthy containers. CI runs CPU correctness and UI checks; long training and held-out benchmarks are separately reproducible jobs.

## Official references

[uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/), [Next.js App Router](https://nextjs.org/docs/app), [React state](https://react.dev/learn/managing-state), [Pydantic schema](https://docs.pydantic.dev/latest/concepts/json_schema/), [acados installation](https://docs.acados.org/installation/index.html). Reviewed 10 September 2026. The choices above are project architecture decisions, not claims of a tested installation.
