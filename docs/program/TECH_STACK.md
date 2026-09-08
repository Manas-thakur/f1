# Selected technology stack

This is the implementation decision, not a list of alternatives. All production paths are at the repository root. A01 owns dependency selection and locks. Numeric major lines below are compatibility targets, not claims of latest versions; freeze released compatible patch versions only after the G0 installation spike.

## Components

| Layer | Choice | Purpose |
|---|---|---|
| Python | CPython 3.12, uv workspace | One scientific runtime and frozen dependency graph. |
| Web tooling | Bun 1.3 | Build tooling only; no second application backend. |
| Interface | React 19, strict TypeScript, Vite, React Router | Client-rendered operational routes and static product pages with deep links. |
| Server state | TanStack Query | REST snapshots, mutation status and cache invalidation. |
| Live view state | Zustand | Bounded telemetry buffers, cursor, selected channels and connection sequence. |
| Styling | CSS Modules, semantic HTML; Radix Dialog/Popover | Custom instruments with accessible complex controls. No imported dashboard theme. |
| Charts | uPlot; SVG track view | Linked numeric traces and circuit position. Provide accessible numeric summaries. |
| API | FastAPI, Pydantic 2, Uvicorn | Typed HTTP/WebSocket control plane. |
| Contracts | Pydantic → JSON Schema/OpenAPI → openapi-typescript; Ajv | One schema authority, generated types and runtime event validation. |
| Numerics | NumPy, SciPy, float64 physics | Dynamics, filters, likelihoods and reference checks. |
| Planner | CasADi, acados | Symbolic dynamics and compiled continuous optimal-control subproblems. Discrete tactics stay in the outer enumerator. |
| ML/RL | PyTorch 2, Gymnasium, Stable-Baselines3 SAC | Continuous policy training and separate ordinary-return estimator. |
| Calibration | scikit-learn | Calibration/regression diagnostics and frozen calibrators. |
| Database | PostgreSQL 17, SQLAlchemy 2, Alembic, psycopg 3 | Transactional events, commands, leases, outbox and manifests. |
| Trajectories | PyArrow Parquet, DuckDB | Columnar recordings and offline interrogation. |
| Model artifacts | Local content-addressed filesystem | Weights/reports keyed by SHA-256; database holds references. |
| Tests | pytest, Hypothesis, Vitest, Testing Library, Playwright, axe-core | Numerical invariants, contracts, component state and connected browser workflows. |
| Static checks | Ruff, mypy, ESLint, TypeScript compiler | Authored-code quality and type correctness. |
| Packaging | Docker Compose, Linux numerical image, nginx | Reproducible local product with same-origin API/WebSocket routing. |
| Diagnostics | JSON logging, Prometheus client, TensorBoard | Correlated operational metrics and offline training traces; no cloud account required. |

## Canonical source paths

Use uv members `packages/contracts`, `packages/core`, `apps/api`, each with a pyproject. Root owns dev tools and workspace configuration. Use direct Python package layout:

```text
packages/contracts/afterlap_contracts/   # authoritative Pydantic models
packages/contracts/generated/           # JSON schemas and TypeScript output
packages/core/afterlap_core/
  data/ simulation/ rules/ estimation/ planning/ learning/
apps/api/afterlap_api/                   # routes and persistence adapters
workers/                                # thin process launchers importing packages
apps/web/src/
  app/                                  # shell/router/providers
  features/                             # owned feature routes
  components/ state/ api/ styles/
configs/ infra/ tests/ artifacts/ docs/handoffs/
```

Older briefs' `packages/core/<module>/` names are logical scopes. Their canonical importable path is `packages/core/afterlap_core/<module>/`. A01 includes this mapping in assignments. Do not create both trees. A01 owns locks, migrations, schemas and shared router; workers own isolated features and tests.

## Process model

Start with one API process supervising one session process per active operational simulation, using multiprocessing spawn and bounded typed queues. Commands carry ID, session revision, deadline and immutable payload; results repeat the correlation fields. No physics or solver work inside the asyncio event loop. Use only project-created processes; expose no network pickle endpoint.

The session process serialises observed state and driver inputs. It accepts a solver result only while its state/rule revisions remain current. The API atomically checks operator authority and appends committed lifecycle events plus transactional outbox records. Delivery is at least once; consumers deduplicate sequence/event ID. The database owns durable operator actions; the session worker owns current dynamics. Reconcile the last applied sequence after restart. Test crash-after-commit-before-delivery explicitly.

Batch workers claim jobs through database leases and `FOR UPDATE SKIP LOCKED`. They never consume session queues or occupy reserved runtime cores. Polling control-plane jobs is acceptable; polling the database at physics frequency is not. No Redis, Kafka, Celery or Kubernetes in this release. Add infrastructure only after measuring a limitation and revising the architecture.

## Solver and hardware build

Build acados from a pinned commit; record compiler, CMake, flags and CasADi version. Hash generated solver code against dynamics, horizon and configuration. G0 must solve a small constrained OCP with a known answer inside the packaged Linux image. Do this before planner agents assume native availability.

On Windows, use Docker Desktop's Linux backend for the canonical numerical runtime. Native Python may run contracts and lightweight tests; it is not a second certified solver target. GPU training has a separate image with a compatible PyTorch/CUDA build. CPU training/evaluation must also work. Never silently replace the specified solver with a stub to pass startup; expose unavailable and fix the build.

## Frontend data handling

REST loads metadata and snapshots. WebSocket events resume from last sequence; a gap triggers a fresh snapshot. Ajv validates envelopes before state updates. Keep a bounded visible telemetry window; decimate numeric traces while preserving extrema and event annotations. Exact inspection uses original samples. Do not push every telemetry sample through the REST query cache.

One shared replay cursor identifies either distance or session time; changing alignment is explicit. Channel registry defines name, unit, colour, scale and provenance. Commands carry expected revision and idempotency key. Pending submission disables duplicates. A conflict refreshes evidence; it does not silently retry a stale decision. Do not optimistically mark execution as observed.

## Storage and local deployment

Compose supplies db, api, web and batch services plus a migration job. API supervises session processes. nginx serves built web assets and proxies `/api` and `/ws` on the same origin. Development Vite uses matching proxies. Separate volumes store database, trajectories and models. Private source credentials never enter exports.

Use role-scoped session credentials and a single operator lease. Development bootstrap works only in local development mode; no default production secret. Debug truth is a separate restricted endpoint. Driver communication works only in simulator mode. Load only locally produced, hash-verified approved model bundles; do not accept arbitrary pickle uploads.

## Dependency freeze and commands

A01 writes `infra/dependency-baseline.md` with versions, official compatibility requirements and spike evidence. Generate `uv.lock` and `bun.lock`; thereafter install frozen. Do not install prereleases merely because an official documentation page tracks master. Regenerate schemas in CI and fail on drift.

A01 implements these command contracts:

```text
uv sync --frozen --all-packages
bun install --frozen-lockfile
uv run python -m afterlap_core.cli doctor
uv run pytest tests/contracts tests/numerics
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

Doctor checks manifests, writable artifact storage and numerical solver availability without printing secrets. Compose acceptance requires a working closed-loop synthetic session, not just healthy containers. CI runs CPU correctness and UI checks; long training and held-out benchmarks are separately reproducible jobs.

## Official references

[uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/), [Vite setup](https://vite.dev/guide/), [React state](https://react.dev/learn/managing-state), [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/), [Pydantic schema](https://docs.pydantic.dev/latest/concepts/json_schema/), [acados installation](https://docs.acados.org/installation/index.html). Reviewed 8 September 2026. The choices above are project architecture decisions, not claims of a tested installation.
