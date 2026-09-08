# A07 — reinforcement learning: ready-to-paste agent brief

Implement the reinforcement learning module for AFTERLAP using this specification package. This is implementation work, not a request for another plan.

## Mandatory context

Read `docs/AGENTS.md`, `docs/README.md`, `program/ARCHITECTURE.md`, `program/DECISIONS.md`, `program/EXECUTION_PLAN.md`, all `contracts` documents and [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md). Read other markdowns in this module. References are relative to docs/ unless stated otherwise.

## Write scope

All production paths are at the repository root. Own only: packages/core/learning/; tests/learning/. Ignore files outside this repository. Do not alter other workers' modules, root dependency files, schemas, database migrations or router registration without coordinator integration. A01 is the coordinator exception for its declared responsibilities. Do not overwrite the documentation mockups with production code.

## Dependencies

simulation, rules, planning, validation. Use coordinator-provided contract fixtures until dependencies are integrated. Missing dependencies must return explicit unavailable states, not fake successful behaviour. Submit contract changes in `docs/handoffs/A07-contract-proposal.md` and continue independent work.

## Deliverables

Gym wrapper, SAC training, separate return estimator, frozen bundles and ablation report. Include public interfaces, deterministic fixtures, meaningful tests, diagnostics, failure paths and source/provenance notes. Implement all acceptance cases in the module specification. Validate the shared contract vectors. No real-F1 actuation, hidden simulator-truth access, fabricated measurements or live model exploration.

## Execution sequence

1. Confirm the assigned interface contract and dependency readiness from coordinator status.
2. Implement the smallest deterministic end-to-end path for this module.
3. Add the domain-specific correctness tests before optimisation or visual polish.
4. Implement missing/stale/invalid/timeout behaviours and provenance.
5. Integrate through the agreed interfaces and run module plus contract tests.
6. Measure applicable performance; distinguish measurements from targets.
7. Write `docs/handoffs/A07.md` with paths, commands/results, assumptions, unresolved issues and required integration actions.

Do not declare the full product complete. Mark this module review-ready only when its acceptance cases pass. Never edit test expectations merely to conceal a failed invariant.
