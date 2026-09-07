# Agent working agreement

## Boundary

The user explicitly requested a fresh project plan and asked that everything else in `C:\Work\f1` be ignored and left untouched. Do not inspect, import, clean, move, delete, install into, or refactor those other contents. Documentation lives in `new_plan/`; future implementation lives in `new_plan/implementation/`. Do not use broad repository clean/reset commands. No deployment or external messages are requested by this package.

## Required reads

Read README, 00_program/ARCHITECTURE.md, 00_program/DECISIONS.md, 00_program/EXECUTION_PLAN.md, 01_contracts/DOMAIN_MODEL.md, 01_contracts/API.md, 01_contracts/UNITS_TIME.md, your module specification and your AGENT_BRIEF. Paths in implementation instructions are relative to `new_plan/implementation/`.

Also read [selected stack](00_program/TECH_STACK.md), [master orchestration prompt](00_program/BUILD_WITH_AGENTS.md), and [current design revision](12_design/DESIGN_REVISION_02.md). Learning/estimation/planning agents read the [detailed ML guide](07_learning/README.md). Canonical Python package paths in TECH_STACK supersede logical folder shorthand in earlier briefs. The masked neural encoding is an explicit adapter; unknown domain values still remain null with provenance.

## Ownership and coordination

The coordinator owns contracts, root dependency files, database migrations, shared frontend tokens, integration tests and model/ruleset promotion. Each worker owns only its assigned module directories and tests. Workers propose contract changes in `implementation/handoffs/<agent-id>-contract-proposal.md`; only the coordinator merges them and increments the contract revision. No second API format, private unit convention, or duplicate simulation engine.

Agents may develop against contract-compatible fixtures while dependencies are under construction. Mark fixtures synthetic. Never silently replace missing functionality with random numbers or return a successful status for an unimplemented action. A stub returns an explicit unavailable result.

Use separate branches/worktrees when available and authorised for the new implementation project, or strict disjoint directories when sharing one checkout. A worktree does not grant permission to read the old parent project. The coordinator merges one dependency wave at a time and runs the contract suite.

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

Write `implementation/handoffs/<agent-id>.md` containing: delivered paths; public interfaces; assumptions; tests and exact commands/results; performance measurements and hardware; remaining defects; required integration actions; fixture provenance; source/license notes. A worker marks its own module ready for review, not the complete product done.

## Completion

Implementation, meaningful tests, failure handling, fixture compatibility, operational metrics and handoff are all required. Do not declare a placeholder API, static screenshot, training reward curve, or single favourable scenario a completed capability. Match the module's acceptance cases and the release gates.
