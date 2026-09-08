# M23-PLATFORM: backend, contracts and operational integrity

Branch `feat/23-circuit-platform`, based on `origin/main` at `b316857`.

The assignment named `origin/main` at `ec5733f` and excluded PR #23. PR #23 has
since merged as `b316857`, which relocates product code to the repository root,
so every path in the assignment moves: `new_plan/implementation/apps/api/`
became `apps/api/`, handoffs became `docs/handoffs/`, and so on. Working from
the older commit would have produced a branch that conflicts with all of main.

Scope: the items with no blocker. Item 13 (the full API runbook on a Monza or
Spa session) is blocked and is recorded under **Not done** with the reason.

---

## 1. What changed

| Path | Change |
|---|---|
| `apps/api/afterlap_api/observability.py` | `/metrics` reads the stream hub's resync counter before snapshotting |
| `apps/api/afterlap_api/routes/sessions.py` | records planner duration, observation age and spool depth after every step |
| `apps/api/afterlap_api/stream.py` | counts resync instructions at the point one is built |
| `apps/api/afterlap_api/session/runtime.py` | `persistence`, `paused`, `stopped` accessors; `DecisionHealth` and `decision_health()` |
| `apps/api/afterlap_api/routes/health.py` | readiness from capabilities + a live store probe + session decision health; new `GET /health/workers` |
| `apps/api/afterlap_api/redaction.py` | new: rewrites absolute paths to their artefact-identifying tail |
| `apps/api/afterlap_api/errors.py` | scrubs paths out of every typed error message and detail |
| `apps/api/afterlap_api/routes/catalog.py` | uses the shared contracts; scrubs refusal reasons; `frozen_tape_path` → `frozen_tape_available` |
| `apps/api/afterlap_api/routes/exports.py`, `routes/experiments.py` | serialize artefact-relative paths |
| `apps/api/afterlap_api/session/circuit.py` | `MINIMUM_READINESS` derived from the contract constant |
| `apps/api/afterlap_api/session/degradation.py` | ruleset-content, circuit-split, package-hash and conditions gates on a learned bundle |
| `apps/api/afterlap_api/session/factory.py` | `create(payload, session_id=...)` pins the manifest id |
| `apps/api/afterlap_api/worker_health.py` | new: worker heartbeat write/read and absent/stale/live classification |
| `packages/contracts/afterlap_contracts/catalogue.py` | new: the catalogue payloads, promoted out of the route module |
| `packages/contracts/afterlap_contracts/models.py` | `ModelManifest` gains ruleset hash, circuit split, package hashes, conditions support |
| `packages/contracts/afterlap_contracts/requests.py` | `path` and `report_path` documented as artefact-relative |
| `packages/contracts/afterlap_contracts/schema_export.py` | exports the twelve catalogue models |
| `packages/contracts/generated/` | regenerated |
| `workers/session_worker.py` | durable recorder, pinned session id, `records_durably` |
| `scripts/batch_worker_main.py` | writes a heartbeat per poll; `--healthcheck` |
| `infra/docker-compose.yml` | the batch service probes its own heartbeat instead of nothing |
| `tests/api/`, `tests/backend/`, `tests/persistence/`, `tests/operations/` | the coverage below |

**Contract revision:** unchanged at 1. Every contract change is additive and
optional except two deliberate removals of server-side paths from the wire,
which are covered under item 8 below.

**Migration revision:** unchanged. The identity columns
(`d38b6c1a70f5`) were already on main; this branch adds a test that they are
actually migrated rather than only declared on the ORM models.

---

## 2. Item by item

### 1-4. Regression coverage for A16-8

A16-8's handoff states it added no tests. It now has 37 drills across four
suites, run against the real application with a real artefact tree.

`tests/api/conftest.py` writes synthetic package trees in each of the four
states the catalogue distinguishes (absent, discovered, rejected and
`geometry_validated`), plus one under an id the registry has never heard of.
Every package is a closed analytic loop written under a circuit id so that
registry, event-overlay and readiness resolution are genuinely exercised.
**No package is that circuit's geometry** and the fixtures say so in their
docstrings, their display names and their `synthetic_sketch` provenance.

| File | Drills | Holds |
|---|---|---|
| `tests/api/test_catalogue_routes.py` | 15 | 23-entry listing, absent/discovered/rejected/validated, hash mismatch, malformed document, centreline hashes and stride cap, conditions, scenario catalogue, unregistered circuit, one `/api/v1` prefix |
| `tests/api/test_session_circuit_identity.py` | 15 | valid selection, unknown circuit, wrong event pairing, unknown event, event on a sketch, missing conditions, unknown conditions, below readiness, rejected, tampered package, missing checkpoints, synthetic-sketch compatibility |
| `tests/persistence/test_circuit_identity.py` | 3 | identity survives an application restart, snapshot, export and re-read; nulls stay null for a sketch; the identity columns are migrated |
| `tests/backend/test_stream_circuit_identity.py` | 4 | the streamed announcement equals REST equals the session row; a cursor outside the retained window resyncs to a snapshot with the same circuit; a sketch announces nulls |

### 5. Catalogue payloads promoted into the contracts package

They were route-local Pydantic models, so the generated JSON Schema and
TypeScript did not describe them and `apps/web/src/api/trackCatalogue.ts`
carried a hand-written copy of the shape. All twelve are now in
`afterlap_contracts.catalogue` and in `EXPORTED_MODELS`; the generated files
are regenerated and `tests/contracts/test_schema_generation.py` passes.

`CataloguePayload` is a sibling of `Contract`, not a subclass: a conditions
summary carries the `content_hash` **of the tape it describes**, which would
shadow `Contract.content_hash()`.

`MINIMUM_READINESS_TO_DRIVE` and `REAL_CIRCUIT_LABEL` become contract
constants and `afterlap_api.session.circuit.MINIMUM_READINESS` is derived from
the first, so the rung the catalogue advertises and the rung a session is
refused below cannot diverge.

**Action for Member 3:** `packages/contracts/generated/contracts.ts` now
declares `TrackListResponse`, `TrackDetailResponse`, `CentrelineResponse`,
`ConditionsListResponse`, `ScenarioListResponse` and their members. The
hand-written interfaces in `apps/web/src/api/trackCatalogue.ts` can be replaced
by imports. One field changed shape; see item 8.

### 6. Pagination

Not added. 23 entries is one page, and adding a cursor to a route that never
needs one is a second way for the listing to be incomplete. A drill asserts
every catalogue route sits under the single `/api/v1` prefix.

### 7. No hard-coded circuit ids

`tests/api/test_catalogue_routes.py::test_a_package_outside_the_registry_is_served_the_same_way`
and `test_session_circuit_identity.py::test_a_circuit_outside_the_registry_can_still_start_a_session`
compile a package under `synthetic-oval-fixture`, which is not in the 2026
registry, and drive it through listing, detail, centreline and session
creation. `test_a_circuit_compiled_after_startup_appears_without_a_restart`
compiles one into a running server. Member 1's packages land without a code
change here.

### 8. Evidence on the wire, never a server path

The track and conditions loaders phrase a missing artefact with the absolute
path they tried, and those reasons reach a client through the catalogue and
through every typed error. `/app/artifacts/...` in a container and
`/Users/<name>/...` on a laptop were both on the wire.

`afterlap_api.redaction` rewrites an absolute path to its artefact-identifying
tail (`artifacts/tracks/monza/package.json`) and elides anything outside a
known root. It is applied in the error handlers, so every route is covered,
and at the three catalogue sites that build a reason without raising.

Two deliberate shape changes:

* `ConditionsSummary.frozen_tape_path: str | null` → `frozen_tape_available:
  bool`. Whether a tape is frozen is actionable; where the deployment keeps it
  is not, and a browser cannot read it. No consumer used the old field.
* `ExportJobResponse.path` and `ExperimentStatusResponse.report_path` are now
  relative to the artefact root. `apps/web`'s `ExperimentReport.tsx` displays
  `report_path` as text and needs no change.

Source URLs, licence text, hashes and readiness reasons are untouched.

### 9. Planner duration, observation age and spool depth (defect A14-2)

`RequestMetrics` defined `observe_planner`, `observe_observation_age` and
`spool_depth` with no caller anywhere in the application. They are wired from
the values that already carry the measurement. `websocket_resyncs` was the
same and now comes from a counter on the hub.

The `xfail(strict=True)` marker on
`test_metrics_actually_records_planner_duration_and_observation_age` is gone.

### 10. Readiness (defect A14-4), and the coordinator decision it needed

Readiness now has three terms, reported separately:

* the startup capability report, as before;
* a live probe of the lifecycle store, run in a worker thread;
* whether each attached session could produce a decision now.

A14-4 flagged that the patch as drafted would fail readiness for a paused
session and restart the container. **The decision taken here:** a session that
is `created`, `paused`, `stopped` or `finished` is listed under
`detail.idle_sessions` and never fails readiness. Only a running session that
is withdrawing advice, halted by a degradation finding, or whose newest usable
observation is older than 2 s appears under `detail.sessions` and fails.

This was not theoretical. The first version failed readiness on a session that
had been created and not yet started, which broke step 1 of the demonstration
runbook against a live server; it is fixed and
`test_a_created_or_paused_session_is_idle_and_does_not_fail_readiness` holds
it.

The `xfail(strict=True)` marker on `test_readiness_reflects_stale_telemetry`
is gone.

### 11. Batch-worker health

The batch service runs no HTTP server, so its container healthcheck was
disabled and a wedged worker was indistinguishable from an idle one. It now
writes one heartbeat per poll into the artefact root it already shares with
the API, saying whether it is idle, running a job, or refusing work on quota.

* `GET /api/v1/health/workers` serves it, distinguishing **absent** (no worker
  here: not a fault, and a single-process install looks like this),
  **stale**, and **live**.
* `infra/docker-compose.yml` probes `batch_worker_main.py --healthcheck`.
* A stale batch worker does **not** make the API unready. `ARCHITECTURE.md`
  puts experiment jobs first in line to stop when resources run short; a
  control plane that went away because the queue stalled would invert that.

`tests/operations/test_worker_heartbeat.py` runs the shipped entry point and
reads what it left behind.

### 12. The spawned session worker (defect A14-10)

Both halves repaired. `WorkerConfig` takes a `database_url` and an
`artifact_root`; the child builds a real `SessionRecorder` with a bounded
spool, and pins its manifest id to the id the control plane addresses it by.
Schema and lifecycle rows stay the control plane's: it registers the session
before spawning the worker, and a decision has a foreign key onto that row. A
`WorkerConfig` without a `database_url` still records nothing, but that is now
a declared choice: `SessionWorkerHandle.records_durably` reports it and the
worker logs a warning.

`test_worker_restart.py`'s note that the ids differ is now an assertion that
they match, and
`test_an_out_of_process_session_persists_its_own_decisions` spawns a
configured worker, drives it, and reads 26 decisions back out of the SQLite
file the child itself wrote.

### 14. The baseline safety path

Approval and the feature-manifest hash were already gates (A14-7 and A14-8
have landed). Three more are now reachable and all fail closed:

* **ruleset contents**, not only `rule_family`: a pack whose energy window
  moved keeps its id and is a different environment;
* **circuit split and compiled package hash**: the same circuit id recompiled
  from different telemetry is different geometry;
* **conditions regime**: a session under a tape the bundle was never
  evaluated under.

An undeclared field is unknown, not permission. A bundle that names no circuit
is refused on a compiled circuit; one that names a circuit without recording
which package it trained on is refused too. On a synthetic sketch there is no
compiled circuit to be outside of, so silence there stays silence.

Every refusal leaves the validated baseline in force and names it.
`tests/operations/test_model_regime.py` holds all of it, without torch, so it
runs everywhere.

**Action for Manas:** a bundle needs `ruleset_hash`, `supported_track_ids`,
`track_package_hashes` and `supported_conditions_ids` populated at write time
or it will not contribute on a compiled circuit. All four are additive and
optional on `ModelManifest`.

---

## 3. Endpoints

| Method | Path | Change |
|---|---|---|
| GET | `/api/v1/health/ready` | now also reports `lifecycle_store`, `idle_sessions`, `sessions`, `batch_worker`; 503 on an unreachable store or an obstructed running session |
| GET | `/api/v1/health/workers` | **new**: per-worker absent/stale/live with the last heartbeat |
| GET | `/api/v1/tracks`, `/tracks/{id}`, `/tracks/{id}/centreline`, `/conditions`, `/scenarios` | unchanged shape except `frozen_tape_path` → `frozen_tape_available`; refusal reasons no longer carry server paths |
| POST/GET | `/api/v1/exports`, `/api/v1/experiments/{id}` | `path` and `report_path` are artefact-relative |
| GET | `/metrics` | `planner_duration_ms`, `observation_age_s`, `spool_depth` and `websocket_resyncs` now carry real samples |

---

## 4. Commands actually run, and their results

Toolchain: `uv 0.12.11`, CPython 3.12.14, bun 1.3.14, macOS arm64. The
repository lives on an exFAT volume that creates AppleDouble `._*` siblings;
they are gitignored, but Alembic's version scanner imports them, so they were
deleted locally before the suite would run. Nothing in the repository changed
for that.

```
uv sync --frozen --all-packages --extra solver
uv run pytest tests                              1105 passed, 10 skipped
uv run pytest tests/api tests/backend tests/persistence tests/operations
                                                  218 passed, 2 skipped
uv run ruff check .                              All checks passed
uv run ruff format --check .                     298 files already formatted
uv run mypy                                      no issues in 290 source files
uv run python scripts/check_no_comments.py       comment policy: pass
uv run python -m afterlap_contracts.schema_export  (regenerated; drift test passes)
bun install --frozen-lockfile
bun run typecheck                                exit 0
bun run test                                     24 files, 322 tests passed
```

The 10 skips are the torch-dependent learning and bundle-format suites; the
`learning` extra is not installed here. `tests/operations/test_model_regime.py`
was written without torch precisely so the compatibility gates run anyway.

### The runbook, against a live server

`scripts/demo.py` against `uvicorn afterlap_api.main:app` on SQLite. Two
consecutive complete runs on one server:

```
--- step 1: liveness and readiness
    /health/ready: HTTP 200 status=ready
    measured capabilities: {... 'lifecycle_store': 'available', 'batch_worker': 'absent'}
--- step 3: one operator holds the control lease
    second operator refused with: HTTP 409 [lease_not_held]
--- step 5: step until the planner publishes an actionable, checked instruction
    independent check: pass at t=26.00s against ruleset sha256:0dba4023bba2...
    learned contribution enabled: False
    validated baseline in force: afterlap-baseline-fixed-schedule-1
--- step 9: the execution event arrives as its own, later event
    delay from communication (s): 0.3500000000000014
--- step 12: export the auditable record
    path: artifacts/exports/exp-013463e428ae4074.json
--- step 13: metrics: planner duration is reported apart from observation age
    planner duration ms: {'p50': 0.069, 'p95': 0.078, 'p99': 0.079, 'samples': 26}
    observation age s: {'p50': 0.16, 'p95': 0.16, 'samples': 26}

runbook complete: 13 steps, 132.07 s wall
```

The same runbook against `origin/main` at `b316857`, in a separate worktree,
completes and reports:

```
--- step 12: export the auditable record
    path: /Volumes/.../f1-baseline/artifacts/exports/exp-ab1ba50ba4c846b8.json
--- step 13:
    planner duration ms: {'p50': None, 'p95': None, 'p99': None, 'samples': 0}
    observation age s: {'p50': None, 'p95': None, 'samples': 0}
```

That is defect A14-2 and the absolute export path, measured on main and on
this branch, rather than described.

---

## 5. Not done, and why

* **Item 13, the Monza or Spa runbook.** Blocked. Compiled artefacts are
  git-ignored and no compiled package for either circuit exists in this
  checkout; producing one needs the OpenF1 ingestion Member 1 owns and network
  access. The runbook above therefore runs on the shipped synthetic sketch.
  Everything the item asks to verify about circuit identity: hash agreement
  across the manifest, the snapshot, the row, the export and the stream, plus
  every refusal: is covered by the drills in section 2, against a compiled
  package written by the test fixtures.
* **Item 6, pagination.** Deliberately not added; see above.
* **A14-5, disk-quota admission on `POST /experiments`.** Untouched. It needs
  `afterlap_ops/quota.py` moved into `packages/core/`, which is outside the
  paths this assignment owns.
* **The remaining unwired metrics** listed at the end of A14-2: ingestion age
  by channel, clock uncertainty, queue depth, estimator residuals, planner
  candidate and rejection counts, rule-context unknown counts, recommendation
  expiry and churn, database latency, failed-job count: are still unwired.
  This branch closed the four the operations specification names by name.

## 6. Operational limitations that remain

* **Docker Compose was not started.** No Docker daemon on the machine this ran
  on, so the compose acceptance case and the nginx path are unverified here.
  The batch healthcheck was verified through `batch_worker_main.py
  --healthcheck` and through `worker_status`, which is what the container
  probe calls; the compose wiring itself is reviewed, not run.
* **PostgreSQL was not exercised.** Everything above ran on SQLite. A08 §9.6
  already records this.
* **A pre-existing race between `POST /sessions` and the next request, newly
  measured.** A control-lease request issued immediately after creating a
  session sometimes answers 404 `session ... does not exist` for a session
  whose row is already in the database file. It surfaced as an intermittent
  failure of the runbook's step 3. It is not introduced here: 20 back-to-back
  create-then-lease cycles against `origin/main` at `b316857` failed 2 of 20,
  and the same 20 against this branch failed 0 of 20 in the same sample. The
  shape fits the FastAPI `yield`-dependency boundary, where `transaction()`
  commits in dependency teardown rather than before the response is written,
  so a client that is fast enough reads a snapshot taken before the commit.
  It is far more frequent when the SQLite file sits on a filesystem with weak
  locking; on the exFAT volume this branch was developed on it fires on most
  runs, and on APFS it is the 1-in-10 above.
  Reproduce with:

  ```
  # create, then immediately take the lease, twenty times
  for i in $(seq 1 20); do ... POST /api/v1/sessions ; POST .../control-lease ; done
  ```

  Fixing it means moving the commit ahead of the response for every mutating
  route, which is a transaction-boundary change across the whole control plane
  and belongs in its own change rather than in this one. Recorded here so it
  is not rediscovered as a flaky test.

* **A stale batch worker is visible but not acted on.** Nothing requeues a job
  whose worker died holding its lease; the lease simply expires. That is
  `workers/batch_worker.py`'s existing behaviour and is unchanged.

## 7. Reproduction

```
git checkout feat/23-circuit-platform
uv sync --frozen --all-packages --extra solver
uv run pytest tests
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python -m afterlap_contracts.schema_export   # must leave the tree clean
bun install --frozen-lockfile && bun run typecheck && bun run test

# the live runbook
AFTERLAP_ENV=development AFTERLAP_DATABASE_URL=sqlite+pysqlite:///$PWD/artifacts/demo.sqlite3 \
  uv run python -m uvicorn afterlap_api.main:app --host 127.0.0.1 --port 8000
uv run python scripts/demo.py --base-url http://127.0.0.1:8000

# worker health
uv run python scripts/batch_worker_main.py --once --wait-for-database 0
uv run python scripts/batch_worker_main.py --healthcheck
curl -s http://127.0.0.1:8000/api/v1/health/workers
```
