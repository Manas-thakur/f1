# Parallel agent execution plan

## Coordinator first

Create `implementation/` as an independent project. Scaffold Python package, React workspace, test runners and pinned lockfiles. Implement and validate contract v1, source capability matrix, shared fixture loader and basic CI. This is wave 0 and is a blocking dependency. Do not have every worker initialise its own app or dependency tree.

## Waves

| Wave | Agents that can work in parallel | Required exit |
|---|---|---|
| 0 | A01 contracts/coordinator | Schemas, fixtures, generated client and test command contracts frozen |
| 1 | A02 data; A03 simulator; A04 rules; A09 engineer shell; A10 lab shell; A11 driver; A12 design | Independent modules pass fixture tests; no integration success claimed |
| 2 | A05 estimation; A06 baseline planning; A08 backend; A13 evaluation; A14 operations | Feed -> estimate -> constrained plan -> API vertical slice |
| 3 | A07 learning; A09/A10/A11 real integration; A13 closed-loop benchmark | Frozen learned candidate; lifecycle, expiry and branch flows functional |
| 4 | Coordinator + A13 integration; A15 presentation | Held-out report, failure drill, claim audit, reproducible release |

Workers should not be idle waiting on full modules: use the coordinator's typed fixtures. Integration begins with simple deterministic scenarios before long training. A07 can develop environment wrappers during wave 2 but cannot meaningfully train until simulator, rules and baseline outputs pass their gates.

## Ownership

Each module contains a ready-to-paste `AGENT_BRIEF.md`. Its allowed write set includes corresponding module tests. Root dependency files, generated schemas, migrations and shared UI shell/tokens are coordinator-controlled. A09 owns engineer route, A10 lab/replay route, A11 driver route, A12 shared design components through coordinator review. Do not simultaneously edit `App.tsx` or router registration: submit one small integration patch in the handoff.

## Coordinator prompt

> Implement the AFTERLAP product strictly within new_plan/implementation. Read new_plan/AGENTS.md and 00_program plus 01_contracts first. Own root scaffolding, contract freeze, dependency versions, migrations, shared router and integration gates. Assign workers only the disjoint paths in their AGENT_BRIEF. Ignore all pre-existing parent-project contents. Require tests and handoffs, merge by wave, and keep simulated data explicitly labelled. Do not publish externally. A complete product requires the closed-loop and failure-handling gates; static mockups are only the design reference.

## Worker launch procedure

Paste the entire relevant brief, specify its agent ID and point it to this plan. Tell the worker to implement, run its tests and produce the required handoff. Require a contract proposal instead of silent interface changes. Track status in `implementation/handoffs/status.md` with dependency-ready, implementing, blocked, review-ready and integrated states. Do not infer completion from the presence of a file.

## Integration gates

G0: schema compatibility and unit tests. G1: physics convergence and no free energy. G2: rule boundary cases with independent expected values. G3: partial-observation isolation and estimation coverage. G4: baseline constrained planning including timeout/expiry. G5: human lifecycle and connected simulator display. G6: branching determinism and reactive rivals. G7: held-out model comparison including RL ablation. G8: failure recovery, export reproducibility and honest presentation.

An agent may finish its local work while a downstream gate remains blocked. The coordinator records the distinction and never converts an unavailable dependency into fabricated telemetry or a successful placeholder response.


## Coordinator launch

Use the complete [master implementation prompt](BUILD_WITH_AGENTS.md) and [selected stack](TECH_STACK.md). Their canonical source layout maps the logical paths in module briefs to importable packages.

A16 owns real-circuit and condition packages. Start its source/schema work in wave 1; integrate validated geometry in wave 2; complete event overlays and circuit-conditioned evaluation with A03/A04/A07/A13 in waves 3–4. A16 may not mark a track simulation-eligible without the evidence in `17_real_tracks_conditions/VALIDATION.md`.
