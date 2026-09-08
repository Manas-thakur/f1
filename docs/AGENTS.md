# Agent working agreement

## Boundary

Documentation lives in `docs/`. Product code lives at the repository root. Do not use broad repository clean or reset commands. No deployment or external messages are requested by this package.

## Required reads

Read [docs/README.md](README.md), [program/ARCHITECTURE.md](program/ARCHITECTURE.md), [program/DECISIONS.md](program/DECISIONS.md), [program/EXECUTION_PLAN.md](program/EXECUTION_PLAN.md), [contracts/DOMAIN_MODEL.md](contracts/DOMAIN_MODEL.md), [contracts/API.md](contracts/API.md), [contracts/UNITS_TIME.md](contracts/UNITS_TIME.md), your module specification and your AGENT_BRIEF. Paths in implementation instructions are relative to the repository root.

Also read [selected stack](program/TECH_STACK.md), [master orchestration prompt](program/BUILD_WITH_AGENTS.md), and [current design revision](design/DESIGN_REVISION_02.md). Learning, estimation and planning agents read the [detailed ML guide](learning/README.md). Canonical Python package paths in TECH_STACK supersede logical folder shorthand in earlier briefs. The masked neural encoding is an explicit adapter; unknown domain values still remain null with provenance.

## Ownership and coordination

The coordinator owns contracts, root dependency files, database migrations, shared frontend tokens, integration tests and model/ruleset promotion. Each worker owns only its assigned module directories and tests. Workers propose contract changes in `docs/handoffs/<agent-id>-contract-proposal.md`; only the coordinator merges them and increments the contract revision. No second API format, private unit convention, or duplicate simulation engine.

Agents may develop against contract-compatible fixtures while dependencies are under construction. Mark fixtures synthetic. Never silently replace missing functionality with random numbers or return a successful status for an unimplemented action. A stub returns an explicit unavailable result.

The coordinator merges one dependency wave at a time and runs the contract suite.

## Invariants

- SI internally; display conversions at the edge. Unknown is null plus provenance, never zero.
- Simulation truth is isolated from controller observations and frontend operational views.
- Team-to-car network control is outside real-F1 scope. The connected driver screen is simulation-only.
- Hard modelled constraints are enforced outside RL. Human selection does not bypass them.
- No live RL exploration, silent model replacement or automatic promotion.
- No confidence, win rate, latency or certification claim without evidence and scope.
- No real rival battery-state label without authorised measurements.
- Browser prototypes must keep the visible illustrative-data notice.

## Handoff format

Write `docs/handoffs/<agent-id>.md` containing: delivered paths; public interfaces; assumptions; tests and exact commands/results; performance measurements and hardware; remaining defects; required integration actions; fixture provenance; source/license notes. A worker marks its own module ready for review, not the complete product done.

## Completion

Implementation, meaningful tests, failure handling, fixture compatibility, operational metrics and handoff are all required. Do not declare a placeholder API, static screenshot, training reward curve, or single favourable scenario a completed capability. Match the module's acceptance cases and the release gates.
