# AFTERLAP: full repository context dump

Working product name: **AFTERLAP**. GitHub `Manas-thakur/f1`. Prepared from the tree as of 12 September 2026.

This file is a standing context dump of what the code actually does, not a restatement of the marketing pitch. Specs live under `docs/`. Product code lives at the repository root. Synthetic fixtures unless a document or config says otherwise.

---

## 1. What the product is

AFTERLAP is a **race-engineer decision-support system for electrical energy and racing battles**. It helps an engineer choose a near-term electrical deployment strategy (harvest / conserve / neutral / push / overtake), evaluate an attack and the subsequent defence, and review the outcome.

It is **simulator-only** in this release. Public telemetry is a reference observation, not a battery feed. A connected driver display exists only inside simulation. It does **not** claim FIA certification, real-car actuation, or onboard electronics integration. Team-to-car network control is out of scope.

The required closed loop is:

> observation → estimation → legal planning → engineer selection → driver execution → outcome evaluation

Two interventions can branch from one complete snapshot with **reactive** opponents (the rival is not a frozen recording). Every output keeps provenance, applicable rule version, model version, and timestamps.

---

## 2. Hard invariants (read these first)

These are enforced in contracts, runtime, tests, and UI. Breaking them is a product defect, not a style issue.

1. **SI internally.** Display conversions (km/h, MJ, °C, kW) happen only at the UI edge via the channel registry.
2. **Unknown is `null` plus provenance and quality, never `0`.** Inventing a number is forbidden.
3. **`WorldState` never crosses into controller or operational UI.** The simulator owns physical truth. The controller and UIs receive `StateEstimate` and `Recommendation` only. Debug truth is a separate authenticated path, unavailable in replay / live-team.
4. **Selection is not execution.** `SELECT` records a human decision. Only an `ExecutionEvent` moves a recommendation to `executing`.
5. **Independent checker is final.** The planner's solver status is ignored. `unknown` is not a pass.
6. **Hard constraints live outside RL.** Human selection cannot bypass them. Learned preferences are soft; planner + checker still gate legality.
7. **No live RL exploration, silent model replacement, or automatic promotion.** `promote_bundle` defaults to no.
8. **Unimplemented capability returns an explicit unavailable result**, never a mocked success.
9. **No comments in source.** Allowed: license blocks and tool pragmas. CI enforces this.
10. **One operator lease per session.** A second operator can observe; they cannot race the first through contradictory commands.
11. **Battery energy (J) is not the CU-K recharge ledger.** They are different buses. Mixing them is a correctness bug.
12. **Overtake is a legal profile permission, not an energy number.** Eligibility is a state machine. Energy is a separate physical constraint.

---

## 3. Process model: how a click becomes physics

Next.js is the **public HTTP origin**. Python is **not** an HTTP server. Python exposes a length-prefixed JSON socket IPC runtime.

```
Browser
  → Next.js pages + /api/v1 + SSE  (apps/web, host 18473)
       REST:  spawn `python -m afterlap_api.cli request METHOD /api/v1/...`
       SSE:   spawn `python -m afterlap_api.cli stream SESSION --after-sequence N`
  → Python control plane  (apps/api, host 19284, container 8000)
       owns leases, events, outbox, routes, session registry
  → spawned session worker  (multiprocessing spawn, packages/application)
       owns one session's serialised state machine
  → domain core  (packages/core)
       simulator, ingestion, estimation, rules, planning
  → PostgreSQL + Parquet  (packages/infrastructure)
       lifecycle / decisions / outbox vs high-volume telemetry
```

No physics or solver work inside the Next.js process. No Redis, Kafka, Celery, or Kubernetes in this release. Batch workers claim jobs with `FOR UPDATE SKIP LOCKED` and must not occupy the runtime's reserved CPU cores.

Commands carry: id, session revision, deadline, immutable payload. Results repeat the correlation fields. Delivery is at-least-once; consumers deduplicate by sequence / event id.

---

## 4. Repository layout

| Path | Role |
|---|---|
| `apps/api` | Python control-plane CLI and in-process / spawned session runtime (`afterlap_api`) |
| `apps/web` | Next.js 15 / React 19 engineer console, lab, driver display, replay, `/api/v1` |
| `packages/contracts` | Authoritative Pydantic models → generated JSON Schema + TypeScript |
| `packages/core` | Simulation, data, rules, estimation, planning, learning, tracks, conditions, evaluation |
| `packages/application` | Session runtime ports and out-of-process spawn |
| `packages/infrastructure` | SQLAlchemy persistence, outbox, leases |
| `workers/` | Thin process launchers: `session_worker.py`, `batch_worker.py` |
| `configs/` | Cars, tracks, rules, scenarios, planning, learning, conditions, benchmarks |
| `scripts/` | Doctor, migrate, demo, release, acceptance, CI helpers |
| `tests/` | pytest suites by module |
| `infra/` | Compose catalog, Linux images, unique host ports |
| `Makefile` | Local stack orchestration (`make up`) |
| `docs/` | Specs, design mockups, deck, handoffs |
| `artifacts/` | Content-addressed store (tracks, models, trajectories) |

Python: CPython 3.12, `uv` workspace. Web: Bun 1.3.14, Next App Router.

---

## 5. Domain vocabulary

| Term | Meaning |
|---|---|
| **WorldState** | Private sim truth: physics, opponents, RNG, integrator, driver queues. No wire schema. |
| **StateEstimate** | Operational belief: own car, rival beliefs, race context, quality, uncertainty. Only planner/UI input. |
| **TelemetryEvent** | Canonical ingested sample: channel, SI value, provenance, quality, sequence, times. |
| **SourceCapability** | What a feed can actually measure, at what rate, with which limitations. |
| **RulePack / RuleContext** | Immutable pack + live flags, eligibility, curves, limits. Unknown ≠ invent a default. |
| **Eligibility** | `unknown → ineligible / eligible_detected → active`. Overtake profile permission. |
| **DeploymentProfile** | Coarse human-executable modes: `harvest`, `conserve`, `neutral`, `push`, `overtake`. |
| **CandidatePlan** | One legal intention with profile segments, scenario outcomes, terminal target. |
| **Recommendation** | Published advice with action_code, trigger, end condition, expiry, constraint_result. |
| **Scenario MPC** | Shared near-term action across weighted opponent futures; CVaR-style tail; terminal value beyond the detailed horizon. |
| **SAC** | Soft Actor-Critic proposing two continuous soft preferences. Constrained planner still resolves legality. |
| **Continuation value** | Separate ordinary-return ensemble used to rerank feasible finalists. Not SAC's entropy-regularised Q. |
| **Control lease** | Short-lived single-operator authority for mutable commands. |
| **Snapshot / branch** | Full WorldState restore; shared exogenous RNG keys; reactive opponents then diverge. |
| **Provenance** | `measured` \| `estimated` \| `configured` \| `simulated` on every numeric value. |
| **Quality** | `valid` \| `degraded` \| `stale` \| `missing` \| `invalid`. |
| **Cutoff** | Newest observation session-time that reached the estimator. Later events cannot contribute to that decision. |
| **CU-K ledger** | Regulatory recharge bus, integrated separately from battery stored energy. |
| **Track readiness** | `discovered → geometry_validated → event_rules_validated → condition_calibrated → simulation_eligible`, or `rejected`. Validator-derived, never hand-set. |

### Session modes

- `simulation`: headless engine is the source of observations; driver-action API allowed.
- `replay`: recorded feed; seeking the live clock is not a session command in this release (UI cursor is view-only).
- `live_team`: future authorised team telemetry. Simulator driver commands are **403**.

### Recommendation lifecycle

```
proposed → selected → communicated → executing → completed
         ↘ rejected | expired | invalidated
```

Action codes: `maintain`, `prepare_attack`, `attack`, `defend`, `recover`, `withdraw_advice`. Display wording is a template map, not a second enum.

Operator actions: `select`, `reject`, `mark_communicated`.

Execution match: `matched`, `different_profile`, `late`, `unsolicited`.

---

## 6. Contracts (`packages/contracts/afterlap_contracts/`)

Single schema authority. Pydantic models generate `packages/contracts/generated/{schemas.json,contracts.ts}`. Drift is a CI failure (`schema_export --check`). Frontend consumes `@contracts`. Ajv validates stream envelopes before the store updates.

Key modules:

| File | Contents |
|---|---|
| `base.py` | `CONTRACT_REVISION`, `SCHEMA_VERSION`, hashing |
| `enums.py` | All closed enumerations listed above |
| `quantities.py` | `ScalarValue`, `IntervalValue`, `ProbabilityStatement`, `EnsembleBelief` |
| `telemetry.py` | `TelemetryEvent`, `SourceCapability`, chunk manifests |
| `estimate.py` | `StateEstimate`, `OwnCarEstimate`, `RivalBelief`, `EstimateQuality` |
| `rules.py` | `RuleManifest`, `RuleContext`, `ConstraintResult`, power curves |
| `planning.py` | `CandidatePlan`, `PlanningResult`, `Recommendation`, `ObjectiveTerms` |
| `lifecycle.py` | `ControlLease`, `OperatorEvent`, `SessionCommand`, `ExecutionEvent`, `OutcomeRecord` |
| `session.py` | `SessionManifest`, `SessionSnapshot`, `RuntimeCapabilities` |
| `events.py` | `StreamEnvelope` and per-type payloads |
| `models.py` | Feature / reward / model / benchmark / promotion / experiment manifests |
| `catalogue.py` | Track / conditions / scenario HTTP DTOs |
| `requests.py` | Request/response types for every mutating route |
| `errors.py` | `ErrorCode` + `ApiError` (never exception traces) |
| `registry.py` | Canonical channel catalogue |
| `fixtures.py` | Synthetic builders for tests |

### Canonical channels

`speed_mps`, `acceleration_mps2`, `progress_m`, `lap_distance_m`, `s_m`, `battery_energy_j`, `electrical_power_w`, `deploy_power_w`, `harvest_power_w`, `recharge_ledger_j`, `battery_temperature_k`, `gap_ahead_s`, `gap_behind_s`, `lateral_position_m`.

Each has SI unit, display unit/scale, family, expected provenance, plot colour token, optional bounds. Unmapped vendor fields stay raw; they are not guessed.

### Stream event types

`snapshot`, `telemetry_view`, `estimate_updated`, `recommendation_updated`, `execution_observed`, `rule_context_changed`, `quality_changed`, `experiment_progress`, `heartbeat`, `resync_required`.

Telemetry views may coalesce. Decision / quality / operator events are lossless. A sequence gap triggers `resync_required` then a REST snapshot. A heartbeat proves a connection exists, not that telemetry is fresh.

### Error codes

| Code | HTTP |
|---|---|
| `stale_revision` | 409 |
| `idempotency_conflict` | 409 |
| `lease_not_held` | 409 |
| `recommendation_expired` / `recommendation_invalidated` | 422 |
| `validation_failed` | 422 |
| `mode_not_permitted` | 403 |
| `not_found` | 404 |
| `capability_unavailable` / `persistence_degraded` / `spool_exhausted` | 503 |
| `internal` | 500 |

Same idempotency key + same body → prior result. Same key + different body → 409. If selection races a rule invalidation, invalidation wins.

---

## 7. Closed-loop session tick (the actual algorithm)

Owned by `apps/api/afterlap_api/session/runtime.py` (`InProcessSessionRuntime`). One lock, one monotonic `revision`. A solver result whose revision no longer matches is **discarded**, never applied.

```
Simulator.step(WorldState)
  → Simulator.observe()                 # noisy, delayed; no truth fields
  → SimulatorObservationSource
  → SimulatorAdapter                    # TruthLeakError if a truth field appears
  → IngestionPipeline (10 stages)
  → TelemetryEvent stream
  → estimation.update(..., cutoff_s)    # post-cutoff events dropped
  → StateEstimate
  → rules.resolve_context + EligibilityMachine
  → RuleContext
  → planning.plan(estimate, rule_context, model_bundle, deadline)
       enumerate intentions
       CasADi/IPOPT segment-energy allocation
       re-simulate via public branching API
       independent check_plan
       score + optional learned rerank
  → Recommendation (or withdraw)
  → OutboxPublisher → StreamEnvelope
  → SessionRecorder → SQL + Parquet
```

Driver path is delayed twice:

1. Runtime queues a deliberate input with the **human reaction delay**.
2. Simulator applies its own **mechanical actuation lag**.

Only after (1) elapses does an `ExecutionEvent` exist. Selection and "mark communicated" produce zero executions.

Degradation (`session/degradation.py`): missing own-car energy → analysis-only, no precise energy directive. Unknown opponent energy → wider scenarios, not a fake point value. Missing event rules → unsupported eligibility. Solver timeout → revalidated prior plan or withdrawn advice. Database failure → bounded local spool + visible warning. Spool full → halt new operational recommendations. Training/model mismatch → disable learned contribution, name the baseline.

---

## 8. Domain core (`packages/core/afterlap_core/`)

Package extras: `data` (pyarrow), `solver` (CasADi/IPOPT), `track-ingestion` (scipy/pypdf), `learning` (torch/gymnasium/SB3). No HTTP dependency.

Cross-cutting:

- `cli.py`: coordinator Typer CLI
- `config.py`: YAML documents with `value` / `unit` / `source` / `verification`
- `paths.py`: `Paths`, `ArtifactStore`, SHA-256 content addressing, atomic writes
- `diagnostics.py`: `run_doctor` (contracts / solver / torch / DB). Absent optional deps are not failures; `--strict` is.
- `timebase.py`: `SessionClock`, `EventQueue`, freshness
- `rng.py`: `KeyedRandom`, `StreamRegistry`. Exogenous draws keyed by `(scenario, seed, event_type, time_bin)` so paired branches share disturbance and diverge only on treatment.
- `factors.py`: physics vs reward vs policy-influence separation
- `feature_manifest.py`: frozen `energy-v1` encoder (96 values + 96 mask → shape `(192,)`)

### 8.1 Data: ingestion, quality, recording, replay

Owns original source events. Does not estimate, invent battery, or decide.

Adapters:

- `SimulatorAdapter` (operational path)
- `PublicReplayAdapter` (OpenF1-class public feed, ~3.7 Hz, no battery)
- `TeamFeedAdapter` / `SyntheticTeamFeedAdapter` (authorised / synthetic)

`TruthLeakError` if a mapping tries to carry hidden truth (`rival_battery_energy_j`, etc.). DRS / raw x,y,z are refused with named reasons.

**Ten pipeline stages** (`data/pipeline.py`): parse → structural validate → clock convert → SI → dedupe → reorder → session sequence → quality → append → publish.

Dedup key: `(source_id, epoch, source_sequence)`. Session sequences are monotonic across sources. Late post-cutoff events are labelled `out_of_order` and excluded from a finalised decision.

Quality: freshness from age + declared cadence; `integration_gap_s` widens energy uncertainty.

Recording: Parquet chunks, acquisition provenance, credential redaction.

Replay: `ReplaySession`, `ReplayClock`, snapshot store, mode badges. Replay never mutates the archived original.

Backpressure: `CoalescingBuffer` (display) vs `LosslessBuffer` (raw). Recording fault is visible, not silent drop.

### 8.2 Simulation: physical truth

Reduced model, not a digital twin. Explicit midpoint (RK2) float64. Battery demand held constant per step. Thermal: analytic linear ODE.

Public API: `reset`, `step`, `snapshot`, `restore`, `observe`. `debug_truth()` is debug-only.

Step order: safety/line events (interpolated) → legal profiles → delayed driver actions → forces → integrate motion + battery → thermal → geometry/passes → noisy delayed observations → checkpoints.

Physics: longitudinal + bicycle lateral, grip, drag, wake. Energy: `EnergyLedger`, FIA overlay curves, thermal derate. Overtake: footprint overlap + progress; retained-pass at a named later checkpoint.

Opponent policies: `AttackPolicy`, `DefendPolicy`, `ConservePolicy`, `NormalPolicy`. Reactive, not playback.

Branching: `branch`, `run_branch`, `run_paired`, `snapshot_hash`. Shared exogenous keys, then treatments diverge.

Constants: `DEPLOY_FRACTION` / `HARVEST_FRACTION` per `DeploymentProfile`; `TIMING_LINE_ID`.

Environment hooks (`track_source.py`): `TrackSource`, `EnvironmentField`, `StaticEnvironment`, `CompiledTrackSource`. Compiled real-circuit packages drive the engine when present.

**Honesty measured in the release report:** from one scenario, `push` reached 908.23 m with 0.294 MJ remaining vs `conserve` at 887.01 m with 2.233 MJ. Regen-disabled braking never raises battery energy.

### 8.3 Rules: packs, eligibility, independent checker

Pure functions + one state machine. No LLM, network, or RNG.

- `load_rule_pack` from `configs/rules/`
- `resolve_context` / `admissible_profiles` / `select_curve`
- `EligibilityMachine`: crossings at interpolated time
- `check_plan` / `build_trace` (`CHECKER_VERSION`)

Three-valued result: `pass` / `fail` / `unknown`. Coverage is declared per concern (`implemented_and_tested`, `review_required`, `not_applicable`, `unsupported`). Packs forbid certification-claim phrases. All shipped packs are `synthetic: true`.

A pack hash change invalidates outstanding plans.

Shipped packs: `synthetic-pack-v1`, `synthetic-pack-v2-strict`, `synthetic-pack-unknown`.

Checker independence is tested by handing it `solver_status="converged"` with a declared PASS: it still re-derives and rejects illegal interiors (e.g. −20 kJ dip).

### 8.4 Estimation: beliefs only

Consumes `TelemetryEvent`, publishes frozen `StateEstimate`. Never reads simulator truth. Mutating hidden rival energy while holding observations fixed yields byte-identical beliefs.

- `OwnCarFilter`: EKF on progress / speed / acceleration / energy
- `RivalParticleFilter`: systematic resample, ESS, intention mixture
- `SlotTracker`: `ahead_1` / `behind_1` with hysteresis
- `sample_scenarios` → weighted, temporally correlated opponent futures
- Calibration (`NIS` / coverage / Brier) is offline only, not on the inference path

Rival energy is never labelled `measured`. Without a trustworthy own-energy interval, `EstimateQuality.own_energy_capability` withdraws precise energy advice.

Configs: `configs/estimation/own-car-ekf-v1.yaml`, `rival-modes-v1.yaml`.

Reported calibration shortfall: rival energy coverage 0.7885 vs nominal 0.90 (mode-prior bias). Own speed/progress/energy sit near 0.87–0.90.

### 8.5 Planning: candidates + recommendation

Entry: `plan(estimate, rule_context, model_bundle, deadline) → PlanningResult`

Pipeline:

1. Freshness / capability gate
2. Scenarios from estimate
3. Bounded tactical enumerator (`TEMPLATES`: maintain, prepare_attack, attack, defend, recover)
4. CasADi/IPOPT continuous segment-energy allocation (`solve_allocation`)
5. Re-simulate via branching API + `check_plan`
6. Score (objective-v1, CVaR tail, hysteresis); optional learned continuation rerank
7. Publish recommendation or withdraw

Pruning is suppression, not quiet downgrade. Unknown eligibility removes attack. Unresolved conditions empty `admissible_profiles` → `PlanningStatus.RULES_UNKNOWN`. Maintain is always enumerated first so a learned proposal cannot erase the baseline.

Planning statuses: `ok`, `no_feasible_candidate`, `deadline_exceeded`, `input_unavailable`, `rules_unknown`, `solver_unavailable`.

Deadline: a late answer is withdrawn, not published stale. Target p95 200 ms; **measured p95 827 ms**. Re-simulation is ~86% of planner cost. acados is not built; CasADi/IPOPT is the active solver (D-02).

Learned continuation never double-counts the analytic terminal. No bundle → result equals baseline exactly.

Objective: legality is a hard gate. Among accepted candidates, maximise declared expected race utility with a poor-tail penalty. Position, elapsed time, energy, and probability are separate published fields. A utility number is never labelled "seconds".

### 8.6 Learning: SAC + continuation value

Gymnasium env `AfterlapEnv` at **1 s** policy cadence: decode preferences → plan → integrate → re-estimate → reward.

Two continuous actions: segment budget preference and checkpoint energy target. Reachable bounds computed from the current estimate; preferences are soft.

Frozen `energy-v1` features: 96 values + 96 known-mask.

| Offsets | Contents |
|---|---|
| 0–23 | own-car and race context |
| 24–63 | eight lookahead samples (100…3000 m), five fields each |
| 64–75 | nearest rival ahead (12 fields) |
| 76–87 | nearest rival behind (12 fields) |
| 88–95 | short-horizon history summaries |

Feature hash is embedded in every model bundle. Mismatch disables the learned contribution rather than feeding the network the wrong 96 numbers.

Reward revision tracks `objective-v1` plus potential shaping. Training: SB3 SAC (`cli train`). Serving: hash-checked bundle load. Promotion: refuses without frozen thresholds + evidence.

**Current state: incomplete.** Pipeline is reproducible. Packaged actor is zero tensors named `UNTRAINED_PLACEHOLDER`. `promote_bundle` refuses with `benchmark_report_absent`. Coverage, not compute, is the blocker: `oval-low-energy` and `loop-no-energy-channel` withdraw on 100% of decisions. Docker API image **excludes** the `learning` extra on purpose (torch/CUDA bloat). Doctor reports torch/learning as degraded inside that image.

### 8.7 Tracks: real-circuit geometry (A16)

Converts public F1 circuit data into versioned simulation packages. Does not claim a map image is a driveable digital twin, or that public telemetry exposes battery state.

CLI: `python -m afterlap_core.tracks.cli`

```
registry list|show
sources fetch
ingest / compile / validate
ingest-fia / review-overlay
```

Exit 0 ok / 1 refused / 2 capability unavailable.

Pipeline: OpenF1 location ingest → metric centreline compile (B-spline) → independent validator → FIA PDF overlay (two-reviewer confirmation required) → loader for sim.

Readiness is evidence-derived. Compiled packages pin hashes. Geometry, official activation lines, energy limits, and weather keep separate provenance.

**Six circuits compiled** from public position telemetry: Monza, Spa, Monaco, Suzuka, Mexico City, Singapore. Acceptance run is on **Monza and Spa**.

Three permanent limits with available sources:

1. **No circuit reaches `simulation_eligible`.** That rung needs a surveyed corridor. Position telemetry is a driven line, not track edges. `corridor_quality: unknown`, lap width `nan`, lateral DOF disabled, overtake overlap/contact returns `unavailable`.
2. **2026 Power Unit Information curves are charts.** Text extraction gets axis ticks, not machine-readable curves. Event curve stays unknown; car-document ceiling applies; `event_curve_unknown` is recorded.
3. **Geometry is real; the car is not.** Runs on compiled circuits are labelled `real_circuit_synthetic_energy` on session, persistence, export, and all three UIs.

OpenF1 licence: CC BY-NC-SA 4.0. Redistribution of compiled packages beyond research needs a licence review.

Season registry (`configs/tracks/registry/season_2026.json`) lists the full 2026 calendar as `discovered` unless a package has been compiled. Calendar identity ≠ physical track identity.

### 8.8 Conditions: weather, grip, race control

Physics coefficients only. Never imports learning/planning. A physical parameter is never reinterpreted by a policy (`FACTOR_AND_INFLUENCE.md`).

- Atmosphere: ISA / moist air density
- Wind: `headwind_mps`
- Grip / tyres: surface + compound factors
- `ConditionsTape` / `TapeEnvironment`
- `RaceControlTape` / `FlagPhase`
- OpenF1 weather ingest helper

Shipped tapes: `static-reference`, `synthetic-wet-gusty`, plus circuit race tapes for Monza / Spa / Monaco / Mexico City 2025.

### 8.9 Evaluation: independent benchmarks

The check, not the thing being checked.

- Does **not** import simulator battery/physics modules (ledger equations retyped)
- Does **not** import planning or estimation
- Controllers reach the harness through a `Controller` protocol

Controllers: `LegalGreedyAttacker`, `LegalFixedSchedule`, `HashCheckedController`, unavailable placeholders.

`run_benchmark` / `run_ablation`. Robustness sweep must not emit a confident directive under unknown conditions. Gates refuse certification-claim language.

Manifests: `configs/benchmarks/manifests/commissioning-smoke.yaml`, `held-out-test-v1.yaml`, plus `promotion.yaml`.

---

## 9. Control plane, persistence, workers

### 9.1 Application ports (`packages/application`)

`SessionRuntimePort`: initialise, advance, pause/resume, apply_driver_action, mark_communicated, snapshot/restore, stop.

`ProcessSessionRuntime`: multiprocessing **spawn** only. Command kinds: initialise, tick, observe, plan, apply_simulator_input, mark_communicated, pause, resume, snapshot, restore, health, persistence, stop.

Pre-work refusals: wrong session, stale `expected_revision`, past deadline. Default queue size 32, command timeout 30 s.

### 9.2 API (`apps/api/afterlap_api`)

CLI: `python -m afterlap_api.cli`

| Command | Behaviour |
|---|---|
| `serve` / `runtime` | Bind TCP control plane (`127.0.0.1:8000`) |
| `request METHOD PATH` | IPC request (`--in-process` optional) |
| `stream SESSION_ID` | Envelopes after sequence |
| `version` | Schema / contract versions |

`ControlPlane` starts DB schema, routes, registry, outbox publisher, stream hub. Router is a lightweight method/path table, not FastAPI.

### 9.3 HTTP routes (`/api/v1`)

| Method | Path |
|---|---|
| POST | `/sessions` |
| GET | `/sessions`, `/sessions/{id}/snapshot` |
| POST | `/sessions/{id}/control-lease` |
| POST | `/sessions/{id}/commands` (start/pause/resume/step/stop) |
| POST | `/sessions/{id}/recommendations/{rid}/actions` |
| POST | `/sessions/{id}/simulator/driver-action` |
| POST | `/sessions/{id}/snapshots` |
| GET | `/decisions/{id}` |
| GET | `/tracks`, `/tracks/{id}`, `/tracks/{id}/centreline` |
| GET | `/conditions`, `/scenarios` |
| GET | `/rulesets/{id}`, `/models` |
| POST/GET | `/experiments`, `/experiments/{id}`, cancel |
| POST/GET | `/exports`, `/exports/{id}` |
| GET | `/health/live`, `/health/ready`, `/health/workers`, `/version` |
| GET | `/metrics` (JSON, not Prometheus text) |
| GET | `/sessions/{id}/stream?after_sequence=N` (SSE via Next) |

Mutable routes need operator identity, control lease, `Idempotency-Key`, expected revision.

### 9.4 Persistence (`packages/infrastructure`)

PostgreSQL 17 (compose) or SQLite via `AFTERLAP_DATABASE_URL`. SQLAlchemy 2, Alembic, psycopg 3.

ORM: Session, Manifest, SessionEvent, OperatorCommand, ControlLease, Decision, PlanCandidate, LifecycleEvent, ExecutionEvent, OutcomeRecord, TelemetryChunk, Snapshot, ExperimentJob, ModelBundle, RuleManifest, ExportJob, OutboxRecord.

Design: a decision stores the estimate it used. Bulk telemetry is Parquet. Events + revision + outbox commit in one transaction. Crash-after-commit-before-delivery is an explicit test.

Migrations:

- `c04e287ba46c` contract-revision-1 schema
- `d38b6c1a70f5` real-circuit identity columns

Batch jobs: `claim_experiment_job` with `SKIP LOCKED`.

### 9.5 Workers

- `workers/session_worker.py`: re-exports application process runtime
- `workers/batch_worker.py`: claim → stage checkpoints → atomic finalise; lease-lost discard; cooperative cancel
- `scripts/batch_worker_main.py`: compose `batch` service; wait for DB; artefact quota before claim; run evaluation harness per `(treatment, seed)`

---

## 10. Web app (`apps/web`)

Next 15.5.9, React 19, Zustand 5, TanStack Query 5, uPlot, Radix Dialog, AJV. Vitest + Playwright + axe-core.

Python bridge: `src/server/python.ts`. Resolves repo root, runs `uv run python -m afterlap_api.cli` (or `AFTERLAP_PYTHON`). Compose sets `AFTERLAP_AUTOSTART_RUNTIME=0` because runtime is a sibling service. Local `dev` can autostart `serve`.

### Routes

| Path | Surface |
|---|---|
| `/` | Marketing landing |
| `/simulation-lab` | Marketing lab page |
| `/sessions` | Session list |
| `/sessions/[id]/engineer` | Engineer console |
| `/sessions/[id]/lab` | Simulation lab |
| `/sessions/[id]/driver` | Driver display (sim-only) |
| `/sessions/[id]/replay` | Replay charts |
| `/lab` | Lab without a session yet |
| `/models` | Model manifests |
| `/rulesets/[id]` | Ruleset evidence |
| `/experiments/[id]/report` | Experiment report |
| `/settings` | Settings |

Nav groups: Workspace (Sessions / Engineer / Lab / Replay / Driver), Evidence (Models / Rules), Preferences (Settings).

### Engineer console

Decision steps: **Observe → Review → Select → Communicate → Verify**.

Components: `RecommendationPanel`, `BattleView`, `EnergyTimeline`, `DecisionHistory`, `EvidenceInspector`.

Feed/advice states include disconnected, expired, missing-energy, solver-timeout, rule-unknown, and others (`features/engineer/lifecycle.ts`). Narrow viewport → read-only summary. Select/reject/mark_communicated go through idempotent commands with expected revision. 409 refreshes evidence; it does not silently retry.

Frontend **never** computes eligibility, probability, or energy ledgers. Those come from the server.

### Simulation lab

Configure → Run → Snapshot → Branch → Review.

`CircuitConfiguration`, `ScenarioPanel`, `RunControl` (start/pause/resume/step/stop, wall pacing 0.25–4×), `BranchCompare`, `ExperimentJobs`.

Snapshots are immutable WorldState references (hash). Experiments: `POST /experiments` → 202 job id. Cancel keeps partial results labelled incomplete.

### Driver display

Simulator-only. Precedence: **safety > withdrawn > stale > instruction > completed > neutral**. Shows selected/communicated/executing only. 5 s stream watchdog. Profile button → `POST .../simulator/driver-action`. `live_team` is refused server-side even if the UI were shown.

### Replay

Energy / power / speed / gap charts. Shared cursor is **view-only** in this release (no seek-restore session command). Live-team cannot seek the clock.

### State

Zustand `sessionStore`: `server` (manifest, estimate, recommendation, ruleContext, telemetry, lease, revision, sequences), `stream` (connection, resync, rejections), `view` (channels, cursor, inspector), `request` (in-flight idempotent commands).

TanStack Query: sessions, snapshot, decision, ruleset, models, experiment. Immutable caches for rulesets/models (`staleTime: Infinity`).

Never optimistically mark a recommendation selected or an execution observed.

### Auth

There is **no real auth**. Bootstrap operator `console-operator` in `AFTERLAP_ENV=development`. Production refuses bootstrap, so nobody can operate. Do not bind off-loopback.

### Design system

CSS Modules, semantic HTML, custom instruments. Tokens in `styles/tokens.css`. Charts: uPlot with min/max-preserving decimation; exact inspection uses original samples. Accessible numeric summaries beside plots. Browser prototypes keep a visible illustrative-data notice.

---

## 11. Configs (`configs/`)

Every physical parameter carries `value`, `unit`, `source`, `verification`. Dominant verification is `synthetic_assumption`. A synthetic config makes software executable; it does not establish realism.

| Directory | What it controls |
|---|---|
| `cars/` | `synthetic-2026.yaml`, `synthetic-2026-no-regen.yaml` (mass, power, battery, thermal) |
| `tracks/` | Synthetic `test-loop`, `test-oval`; per-circuit `source.yaml`; `registry/season_2026.json` |
| `scenarios/` | `two-straight-counterattack` (demo default), oval variants, `*-real-battle`, regen/channel edge cases |
| `rules/` | v1, v2-strict, unknown |
| `conditions/` | Static, wet-gusty, circuit race tapes |
| `estimation/` | EKF + rival particle configs |
| `planning/` | `planner-v1.yaml` (horizons, budgets, deadline). Not objective coeffs. |
| `objectives/` | Frozen `objective-v1.yaml` |
| `learning/` | `env-v1`, `env-real-v1`, `sac-v1`, `value-v1`, `circuit-split-v1` |
| `benchmarks/` | smoke, held-out, promotion thresholds |
| `factors/` | `factor-registry.yaml` |

Demo default: scenario `two-straight-counterattack`, ruleset `synthetic-pack-v1`, seed 42. Actionable instruction appears around t = 26 s simulated.

---

## 12. Scripts and coordinator CLI

### `python -m afterlap_core.cli`

`doctor [--json] [--strict]` · `generate-contracts [--check]` · `list-configs <kind>` · `simulate` · `train` · `evaluate` · `ablate` · `promote` · `version`

**Gap:** `simulate` imports `afterlap_core.runner.run_headless`, and **`runner.py` is not in the tree.** That command will fail until the runner is implemented or the CLI is rewired. Closed-loop simulation is otherwise exercised via the session runtime and `scripts/demo.py`.

### Other scripts

| Script | Purpose |
|---|---|
| `scripts/doctor.py` | Compose start gate → core doctor |
| `scripts/migrate.py` | Alembic upgrade; optional `--wait-for-database` |
| `scripts/demo.py` | 13-step live API runbook (lease → plan → select → communicate → drive → snapshot → branch → export) |
| `scripts/acceptance_real_circuit.py` | 13 physical claims on Monza + Spa |
| `scripts/release_bundle.py` | Assemble/verify release bundle |
| `scripts/batch_worker_main.py` | Batch worker loop |
| `scripts/check_no_comments.py` | CI comment policy |
| `scripts/afterlap_pytest_plugin.py` | Registered from root `pyproject.toml` |
| `scripts/afterlap_ops/` | HTTP client for demo; artefact disk quota |

`demo.py` never prints a success it did not observe. Exit 0 means every step happened against a live server.

---

## 13. Infra and CI

Compose project `afterlap` (`infra/docker-compose.yml`):

| Service | Role |
|---|---|
| `db` | Postgres 17.7, host `:17539` |
| `migrate` | one-shot Alembic |
| `runtime` | `cli serve :8000`, host `:19284` |
| `batch` | `batch_worker_main.py`, CPU ceiling |
| `web` | Next standalone, host `:18473` |

Volumes: db, artifacts, nested trajectories / models. `AFTERLAP_DB_PASSWORD` has **no default**.

Images:

- `api.Dockerfile`: Python 3.12 + uv, all extras **except `learning`**. CasADi/IPOPT present. acados degraded.
- `web.Dockerfile`: bun build → Node standalone + Python CLI client. `AFTERLAP_RUNTIME_URL=http://runtime:8000`

All binds `127.0.0.1`. No auth → never expose on a routable interface.

CI (`.github/workflows/ci.yml`):

- **python** (Linux): ruff format/check, mypy, no-comments, docs validate, schema drift, doctor, pytest excluding `slow`/`torch`/`tests/learning`
- **web**: lint, tsc, vitest, next build, Playwright
- **portability**: Windows + macOS lighter gate

Release report cited **985 Python tests, 322 web unit tests, 157 browser tests** at last coordinator assessment.

Gates G0–G8 (execution plan): contracts/numerics → physics → rules → estimation isolation → planner deadlines → human lifecycle → branching → held-out RL ablation → failure recovery. G4 latency target missed. G7 learning incomplete.

---

## 14. End-to-end user flows

### Engineer

1. `/sessions` → `/sessions/{id}/engineer`
2. REST snapshot + SSE
3. Inspect sources, quality, battle/energy charts
4. Recommendation `proposed` → Select (idempotent) → `selected`, **zero executions**
5. Mark communicated → driver acts in sim → `executing` / `completed`
6. Reject with reason, or expiry/invalidation clears the action
7. Evidence inspector → `GET /decisions/{id}`

### Lab / branching

1. Pick circuit / conditions / scenario
2. RunControl advances sim
3. Snapshot at a boundary (hash)
4. BranchCompare: reference vs candidate controllers, paired seeds
5. Queue experiment, poll, open `/experiments/{id}/report`
6. Export via `POST /exports`

### Driver

Only `mode=simulation`. Instruction visible only if selected/communicated/executing. Safety / withdraw / stale / watchdog clear the instruction. Profile press becomes an `ExecutionEvent` after the configured delay.

### Training / promotion (intended, not currently producing a promoted model)

Train SAC on the legal env → ablate vs fixed / greedy / MPC-only → freeze thresholds in `promotion.yaml` → hash-verified bundle → coordinator promote. Runtime adapts beliefs, not weights. No trained policy exists yet.

---

## 15. Architecture decisions (locked)

| ID | Decision |
|---|---|
| ADR-01 | Local runtime; offline training; no cloud latency; no online exploration |
| ADR-02 | Reduced physics with local 2D battle geometry; energy must change motion |
| ADR-03 | Scenario MPC plus bounded SAC contribution |
| ADR-04 | Separate ordinary-return terminal value (SAC Q is not a race-time prediction) |
| ADR-05 | Versioned rule/event packs; stale plans invalidate |
| ADR-06 | Fixed schemas, SI, explicit provenance |
| ADR-07 | Reactive counterfactual opponents |
| ADR-08 | Engineer is the primary operator |
| ADR-09 | Driver link simulation-only |
| ADR-10 | Benchmark gate for any learned model |
| ADR-11 | No LLM in planner or rules |
| ADR-12 | No full CFD or tyre thermodynamics initially |
| ADR-13 | Next.js is the public HTTP origin; Python is a CLI |

Budget targets (not measured claims): 100 Hz simulated dynamics (convergence at 50/100/200 Hz); estimate up to 20 Hz when sources support it; tactical planning event-triggered ~1 Hz; UI snapshots ~10 Hz. Public 3.7 Hz channels must never be advertised as 20 Hz measurements. Record ingestion-to-display age separately from human execution delay.

---

## 16. What is built vs what is not

### Built and integrated

- Contract revision 1, generated TS, drift tests
- Simulator, ingestion, rules, estimation, planning, evaluation
- Session runtime, leases, SSE, persistence, outbox, spool
- Engineer console, lab, driver display, replay, models/rules views
- Compose packaging, doctor, demo runbook, failure drills
- Real-circuit pipeline (ingest/compile/validate/conditions) and 13-claim acceptance on Monza + Spa
- Catalogue routes for tracks / conditions / scenarios

### Incomplete or missing

- **Learning:** untrained placeholder actor; promotion refused; two scenario families give zero usable signal
- **Planner latency:** 827 ms p95 vs 200 ms target
- **`afterlap_core.runner`:** referenced by `cli simulate`, file absent
- **acados:** not built; CasADi/IPOPT only
- **Surveyed corridor / event power curves:** cannot reach `simulation_eligible`; overlay values stay `None`
- **Replay seek** as a session command: UI cursor only
- **Auth:** development bootstrap only
- **Exogenous physical disturbance:** not implemented; seed-level bootstrap variance is zero
- **Three metrics without callers:** `observe_planner`, `observe_observation_age`, `spool_depth` (called out in handoffs)
- **`docs/handoffs/status.md` wave-4 A16 row is stale** (still says "not built"); the release report and the code are the source of truth

---

## 17. How to run

Python 3.12 and Bun 1.3. Host ports are pinned in `infra/ports.env`.

```
make env
make up
make demo
make down
```

Surfaces: engineer console `http://127.0.0.1:18473`, API same origin `/api/v1`, Python runtime `127.0.0.1:19284`, Postgres `127.0.0.1:17539`. `make help` lists the rest. `docs/operations/LOCAL_STACK.md` is the runbook.

Checks:

```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/contracts tests/numerics
uv run python docs/tools/validate_package.py
bun run lint && bun run typecheck && bun run test && bun run build
```

Use `uv run` / `bun run`. Do not call `.venv/bin/python` from shared scripts. Paths in contracts use `/`; filesystem access uses `pathlib.Path`.

---

## 18. Module ownership (how the repo was built)

Multi-agent waves. Coordinator owns contracts, root locks, migrations, shared Next routes, generated schemas. Workers own disjoint module directories.

| Agent | Scope |
|---|---|
| A01 | Contracts, workspace, doctor, G0 |
| A02 | Data ingestion / replay |
| A03 | Simulation truth |
| A04 | Rules / checker |
| A05 | Estimation |
| A06 | Planning |
| A07 | Learning |
| A08 | API / persistence / session runtime |
| A09–A11 | Engineer / lab+replay / driver |
| A12 | Web shell / design system |
| A13 | Evaluation |
| A14 | Operations / packaging |
| A15 | Presentation / release report |
| A16 | Real circuits and conditions (A16-1 registry, A16-2 ingest/compile, A16-3 validate/FIA, A16-4 conditions, later energy/traffic/RL-split/API/UI/eval) |

Handoffs: `docs/handoffs/`. Specs: each module has `TECHNICAL_SPEC.md` and `AGENT_BRIEF.md` under `docs/<module>/`. Start at `docs/README.md`, `docs/program/ARCHITECTURE.md`, `docs/program/DECISIONS.md`, `docs/contracts/DOMAIN_MODEL.md`.

---

## 19. Tests (what they prove)

| Suite | Proves |
|---|---|
| `contracts/` | Schema generation/drift, module boundaries, feature manifest, readiness enum, vectors |
| `data/` | Pipeline, late events, backpressure, recording/replay, quality, capability↔emission |
| `simulation/` | Determinism, snapshot/restore, paired branches, opponent hysteresis, truth isolation, energy limits |
| `numerics/` | Physics laws, energy conservation, regen bounds, convergence |
| `rules/` | Checker independence, eligibility timing, power curves, pack change, unknown fail-closed |
| `estimation/` | EKF, rival PF isolation, slots, scenarios, calibration, capability |
| `planning/` | Allocation, constraints, determinism, deadline, latency, lifecycle |
| `learning/` | No truth in info, features, reward, value ensemble, serving hashes, promotion refusal, smoke |
| `evaluation/` | Harness/report, independent ledger, robustness, statistics |
| `conditions/` | Atmosphere, wind, grip, tape, race control, OpenF1 weather, field→engine |
| `tracks/` | Registry, provenance, ingest, compile, readiness, FIA two-reviewer, CLI exits, compiled package drives sim |
| `api/` `backend/` | CLI, catalogue, control plane, vertical slice, stream, concurrency, degradation |
| `persistence/` | Migrations, lifecycle, outbox deliverability, circuit identity |
| `operations/` | Cold start, DB failure, spool/quota, health, security/redaction, worker heartbeat/restart, shutdown, model hash, portability |
| `acceptance/` | Vertical slice |

Markers: `slow`, `solver`, `torch`, `db`. Never weaken an invariant test to make a build pass.

---

## 20. Mental model in one paragraph

AFTERLAP is a **closed-loop synthetic race-engineer product**. A Next.js console talks to a Python CLI control plane over `/api/v1` and SSE. A spawned session process steps a reduced F1 physics engine, ingests only observations, estimates own-car and rival beliefs without seeing truth, plans legal electrical tactics with CasADi/IPOPT, rechecks them with an independent rules engine, and publishes a recommendation a human must select. Selection is a decision record. Execution happens later, in the simulator, after a modelled delay. Outcomes are stored with hashes. Branches restore a complete snapshot and let reactive rivals diverge. Learned models exist as a gated, currently untrained, optional reranker around that constrained planner. Real circuits contribute geometry from public telemetry; battery truth remains synthetic and labelled as such.
