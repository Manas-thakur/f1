# Integration status board

Coordinator-maintained. A file existing is not completion; a row moves to
`integrated` only after the coordinator has run its boundary tests here.

States: `dependency-ready` → `implementing` → `review-ready` → `integrated`, or
`blocked`.

## Orchestration

Subordinate agent tooling **is** available in this session, so work packages are
dispatched as real concurrent agents with disjoint write paths in one shared
checkout. Concurrency is capped at four coding workers. Only the coordinator
edits contracts, `pyproject.toml`, `uv.lock`, migrations, the shared router and
generated schemas.

## Wave 0 — contracts and coordinator (A01)

| Item | State | Evidence |
|---|---|---|
| uv workspace, locked dependencies | integrated | `infra/dependency-baseline.md`, `uv.lock` |
| Pydantic contract revision 1 | integrated | `packages/contracts/afterlap_contracts/` |
| Generated JSON Schema + TypeScript | integrated | `packages/contracts/generated/`, drift test |
| Typed fixture factories | integrated | `afterlap_contracts.fixtures` |
| Contract acceptance vectors | integrated | `tests/contracts/test_contract_vectors.py` |
| Clock, event order, keyed RNG, artefact store | integrated | `tests/contracts/test_foundation.py` |
| `doctor` command and G0 numerical spike | integrated | `afterlap_core.cli doctor` |

## Wave 1

| Agent | Scope | Allowed write paths | State |
|---|---|---|---|
| A03 | Simulation truth, physics, opponents, snapshots | `packages/core/afterlap_core/simulation/`, `configs/tracks/`, `configs/cars/`, `configs/scenarios/`, `tests/simulation/`, `tests/numerics/` | integrated |
| A04 | Rules engine and independent checker | `packages/core/afterlap_core/rules/`, `configs/rules/`, `tests/rules/` | integrated |
| A02 | Ingestion, provenance, recording, replay | `packages/core/afterlap_core/data/`, `tests/data/` | integrated |
| A12 | Web workspace, design system, shell | `apps/web/`, `package.json`, `pnpm-workspace.yaml` | integrated |

### Coordinator verification of wave 1

Each module was re-verified here rather than accepted on its worker's report.

| Claim | How the coordinator checked it | Result |
|---|---|---|
| Truth isolation (A03) | Mutated the rival's true energy from 1.96 MJ to 4.0 MJ inside the private world and re-read own-car observations | byte-identical; the mutated value appears nowhere |
| No free energy (A03) | Ran the regen-disabled scenario braking for 30 s and tracked the peak battery energy | never rose above its start; ended 0.075 MJ lower |
| Deployment changes physics (A03) | Ran push and conserve from one scenario for 12 s | 908.23 m / 0.294 MJ against 887.01 m / 2.233 MJ |
| Determinism and restore (A03) | Two identical runs, then snapshot, advance, restore and re-advance | complete states identical in both cases |
| Truth leak guard (A02) | Fed a record carrying `rival_battery_energy_j` through `SimulatorAdapter` | refused with `TruthLeakError` |
| DRS is not eligibility (A02) | Asked the public mapping table for `drs`, `x`, `y`, `z` | each refused with a named reason |
| Checker independence (A04) | Read the test that hands it `solver_status="converged"` with a declared PASS | still re-derived and rejected |
| Chart honesty (A12) | Opened the built app in Chrome at 1500 px | two defects found; see below |

Two defects were found by coordinator review that the workers' own suites could
not reach:

1. A12's chart painted a wall-clock x axis on a distance plot and clipped y
   ticks showing raw SI beneath a kW/MJ legend. Neither was reachable because
   uPlot paints ticks with `fillText` and nothing read the canvas. Fixed, with
   browser assertions that were falsified against the original configuration
   first.
2. A02's `SimulatorAdapter` docstring claimed a constructor-level guarantee it
   did not enforce. Rewritten to describe the record-level check that is
   actually tested.

## Wave 2

| Agent | Scope | State |
|---|---|---|
| A05 | Estimation: own-car EKF, rival particle filter | integrated |
| A06 | Planning: enumerator, MPC, checker integration | integrated |
| A08 | API, persistence, session runtime, lifecycle | integrated |
| A13 | Evaluation harness and benchmarks | integrated |

## Wave 3

| Agent | Scope | State |
|---|---|---|
| A07 | Gym environment, SAC, continuation ensemble | integrated, learning INCOMPLETE |
| A09/A10/A11 | Engineer console, lab/replay, driver display | integrated |

## Wave 4

| Agent | Scope | State |
|---|---|---|
| A14 | Operations, packaging, failure drills | integrated |
| A15 | Presentation and release report | integrated as handoffs/RELEASE_REPORT.md |

## Contract proposals received

None yet. Workers submit them to `handoffs/<agent-id>-contract-proposal.md`;
only the coordinator merges and increments the contract revision.


---

## Wave 4 — release

`handoffs/RELEASE_REPORT.md` carries the gate-by-gate assessment, measured
performance, stated limitations and the claims this release does not support.

**985 Python tests, 322 web unit tests, 157 browser tests. All green.**

### Outstanding, in priority order

| Item | State |
|---|---|
| **A16 real circuits and conditions** | **not built.** `BUILD_WITH_AGENTS.md` was revised mid-build to require it and `new_plan/17_real_tracks_conditions/` holds 397 lines of specification plus a track-package schema, a season registry and a Monza example. No pipeline, geometry compiler, event overlay or condition model exists. The product does not meet its current specification. |
| **Learning** | **incomplete.** Pipeline complete and reproducible; actor is a zero-tensor placeholder; no held-out study; promotion refused with `benchmark_report_absent`. Coverage, not compute, is the blocker: two scenario families withdraw on 100 % of decisions. |
| Planner latency | **827 ms p95 against a 200 ms target.** Re-simulation is 86 % of the planner's own cost. |
| Exogenous physical disturbance | Not implemented, so seed-level bootstrap variance is zero and held-out intervals are scenario-resampled only. |
| Session-aware readiness (A14-4) | Open decision: the available patch changes container restart behaviour either way. |
| Three uncalled metrics (A14-2) | `observe_planner`, `observe_observation_age`, `spool_depth` have no caller. |
| Spawned worker persistence (A14-10) | An out-of-process session has no recorder and mints its own id. |
| acados | Absent on this platform; CasADi/IPOPT is the active solver (D-02). |

## A16 — real circuits and race conditions

Coordinator-owned seams (integrated on `main`, PR #18): `tracks/package.py`,
`tracks/loader.py`, `tracks/provenance.py`, `simulation/track_source.py`
(`TrackSource`, `EnvironmentField`, `StaticEnvironment`, `CompiledTrackSource`),
engine environment hooks, session-contract identity fields, D-10.

| Worker | Scope | Allowed write paths | State |
|---|---|---|---|
| A16-1 | Registry, source manifests, CLI | `tracks/registry.py`, `tracks/cli.py`, `configs/tracks/registry/`, `configs/tracks/<id>/source.yaml`, `tests/tracks/test_registry.py`, `tests/tracks/test_cli.py` | implementing |
| A16-2 | OpenF1 ingestion, B-spline compiler, compiled packages | `tracks/ingest/`, `tracks/compile.py`, `tests/tracks/test_openf1_ingest.py`, `tests/tracks/test_compile.py`, `artifacts/tracks/<id>/` | implementing |
| A16-3 | Independent validator, FIA overlay two-reviewer queue | `tracks/validate.py`, `tracks/fia_overlay.py`, `tests/tracks/test_validate.py`, `tests/tracks/test_fia_overlay.py`, `artifacts/tracks/<id>/events/` | implementing |
| A16-4 | Atmosphere, wind, grip, tyres, race control, OpenF1 weather tapes | `afterlap_core/conditions/`, `configs/conditions/`, `artifacts/conditions/`, `tests/conditions/` | implementing |
| A16-5 | Energy deployment, battery, regeneration extensions | TBD after wave A | dependency-ready |
| A16-6 | Traffic, wake, reactive rivals | TBD after wave A | dependency-ready |
| A16-7 | Gym env cross-circuit sampler, held-out split, no-track-ID leak | TBD after wave A | dependency-ready |
| A16-8 | API, persistence, streams: tracks/scenarios routes, factory resolution | TBD after wave A | dependency-ready |
| A16-9 | Lab, Engineer OS, Driver Display integration | TBD after wave B | dependency-ready |
| A16-10 | Cross-circuit evaluation, 13-point E2E on two circuits | TBD after wave B | dependency-ready |
