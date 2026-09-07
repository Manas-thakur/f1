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
| A05 | Estimation: own-car EKF, rival particle filter | dispatched |
| A06 | Planning: enumerator, MPC, checker integration | pending wave 1 |
| A08 | API, persistence, session runtime, lifecycle | pending wave 1 |
| A13 | Evaluation harness and benchmarks | pending wave 2 |

## Wave 3

| Agent | Scope | State |
|---|---|---|
| A07 | Gym environment, SAC, continuation ensemble | pending wave 2 |
| A09/A10/A11 | Engineer console, lab/replay, driver display | pending wave 2 |

## Wave 4

| Agent | Scope | State |
|---|---|---|
| A14 | Operations, packaging, failure drills | pending wave 3 |
| A15 | Presentation and release report | pending wave 3 |

## Contract proposals received

None yet. Workers submit them to `handoffs/<agent-id>-contract-proposal.md`;
only the coordinator merges and increments the contract revision.
