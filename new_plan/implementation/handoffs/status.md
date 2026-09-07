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
| A03 | Simulation truth, physics, opponents, snapshots | `packages/core/afterlap_core/simulation/`, `configs/tracks/`, `configs/cars/`, `configs/scenarios/`, `tests/simulation/`, `tests/numerics/` | dispatched |
| A04 | Rules engine and independent checker | `packages/core/afterlap_core/rules/`, `configs/rules/`, `tests/rules/` | dispatched |
| A02 | Ingestion, provenance, recording, replay | `packages/core/afterlap_core/data/`, `tests/data/` | dispatched |
| A12 | Web workspace, design system, shell | `apps/web/`, `package.json`, `pnpm-workspace.yaml` | dispatched |

## Wave 2

| Agent | Scope | State |
|---|---|---|
| A05 | Estimation: own-car EKF, rival particle filter | pending wave 1 |
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
