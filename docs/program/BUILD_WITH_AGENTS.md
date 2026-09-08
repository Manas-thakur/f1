# Master implementation prompt

Give the agent this entire file with working directory at the repository root. The prompt uses whatever subordinate-agent tools the host actually exposes; it does not invent vendor commands or assume all subscriptions support parallel agents. It authorizes local implementation, not publishing or real-car integration.

---

You are the lead implementation agent for AFTERLAP. Build the complete product specified in `docs/`. Use subordinate coding agents where supported. Produce integrated working software, reproducible training/evaluation tooling and verified release artifacts. Do not stop at scaffolding, screenshots, another plan or isolated mocked routes.

## Boundaries and authority

1. Write production code at the repository root. Ignore unrelated parent-project content: do not inspect, modify, import, delete or reuse it. Read the documentation under `docs/`; preserve its mockups as design references.
2. Read AGENTS.md, README.md, TECH_STACK.md, ARCHITECTURE.md, DECISIONS.md, all contracts, DESIGN_SYSTEM.md, DESIGN_REVISION_02.md and the module map before dispatch.
3. Current tech stack and design revision supersede older visual descriptions and logical package paths. Preserve numerical, rule and observation invariants. Record any remaining resolution in `docs/handoffs/decisions.md`, naming affected contracts.
4. Read `tracks` and dispatch A16. Real-circuit support requires compiled metric geometry, event overlays and condition validation. A circuit name or image over synthetic dynamics does not satisfy it.
5. Keep synthetic/public/team provenance explicit. Never invent measured battery state, trained weights, benchmark wins, licensed data or FIA approval. Driver communication is simulator-only.
6. The local synthetic product requires no paid service, external publication, messages to other people or production credentials. Record future external integration prerequisites separately.

## Actual orchestration

Detect available agent/task tooling and use its documented interface. Spawn real subordinate agents when available. Otherwise perform the same work packages sequentially and record that limitation. Do not claim imaginary parallel work.

Maintain `docs/handoffs/status.md`: agent, allowed paths, dependencies, state, actual test evidence, next integration action. Start with at most four concurrent coding workers and increase only after checking resource use. Training has a separate compute budget and may not starve the session runtime.

Each worker receives its complete module AGENT_BRIEF plus this assignment:

```text
Agent ID and concrete outcome:
Allowed canonical write paths:
Read-only interface contracts and revision:
Provided dependency fixtures:
Acceptance commands and observable cases:
Forbidden edits: shared schemas, locks, migrations, router, other modules.
Handoff: docs/handoffs/<ID>.md
Exit: module review-ready after checks; never full-product complete.
```

Only the coordinator edits shared contracts, manifests, migrations and router. Workers propose shared changes in their handoff area. Use disjoint paths in a shared checkout. If isolated checkouts are supported, keep them within the authorized implementation boundary and integrate serially; do not alter a parent repository just to create worktrees.

Wait for results, inspect the actual diffs and rerun relevant checks. Worker summaries are not verification. Reproduce failures and assign bounded corrections; never weaken invariant tests to accept output. Persist progress before context limits and resume from the ledger without restarting completed work.

## Wave 0 foundation

Scaffold the independent uv/pnpm workspace and lock released compatible dependencies. Use canonical import paths in TECH_STACK. Freeze Pydantic contracts and generated TS/JSON schemas for StateEstimate, RuleContext, PlanCandidate, Recommendation, lifecycle/execution events, snapshots, model bundles and evaluation records. The supplied telemetry schema is a starting example, not the entire contract set.

Implement migrations, typed fixture factories, provenance/capability enums, schema drift checks and the acados build spike. Provide shared component slots, channel registry and client interfaces. Implement the documented test/start/doctor commands. Agents may not invent integration fields before contract freeze.

## Dispatch order

| Wave | Work packages | Required result |
|---|---|---|
| 1 | A02 ingestion, A03 simulator, A04 rules, A12 shell/primitives, A16 track registry/schema | Timestamp tests; convergence and energy ledger; independent rule boundaries; accessible shell; versioned circuit manifests. |
| 1b | A09 engineer, A10 lab/replay, A11 driver | Routes against typed fixtures with explicit pending/stale/unavailable states. Dispatch as capacity frees. |
| 2 | A05 estimation, A06 baseline planner, A08 API, A13 evaluation, A16 geometry compiler | Observed simulator → estimate → checked plan → actual stream; validated metric geometry with derived curvature, grade and boundaries. |
| 2b | A14 operations, A07 feature/environment contracts | Packaged failure recovery; Gym environment and information isolation. |
| 3 | A07 training/value, A09/A10/A11 integration, A13 experiments, A16 event/condition integration | Frozen candidate, real lifecycle and branching, held-out circuit and combined-condition results. |
| 4 | A15 presentation, coordinator and A13 independent review | Reproducible release with evidence-linked claims. |

Read the learning README and all linked specifications before training. The validated baseline runs while candidates train. Implement the learned components even if promotion fails; implementation completion and model approval are distinct.

## Required vertical slice

A clean install starts a versioned synthetic scenario. Electrical deployment changes battery energy and vehicle motion. Observations hide rival truth. Estimation supplies timestamped beliefs. Planner evaluates candidates; checker rejects invalid ones. Engineer selects and communicates a current instruction; simulated driver execution arrives as a separate event. Driver display expires obsolete advice. Resulting telemetry changes the next decision. Persist and export the complete record.

The lab snapshots the complete state and branches two actual interventions with reactive rivals. Identical seed/input reproduces a trajectory within stated tolerance. Changing strategy changes physical controls and rollouts, not selection between two stored chart arrays. Fixture mode remains visibly distinct.

## Release gates

- G0: locked installation, contracts, generated types, numerical spike.
- G1: convergence, correct battery bus/ledger, no free energy, reactive opponents.
- G2: rule/event pass/fail/unknown with independently calculated boundaries.
- G3: chronological cutoff, estimator coverage, hidden-truth mutation tests.
- G4: finite planner deadlines, constraints, revision invalidation, baseline identity.
- G5: operator lease, idempotency, selection/communication/execution and expiry.
- G6: deterministic snapshot/branch, responsive rivals and export/replay fidelity.
- G7: trained candidate, separate continuation estimator, held-out ablations and recorded promotion decision.
- G8: restart, dropout, database failure, missing models, solver timeout, bounded spool.
- G9: browser review at 320/375/414/768/1024/1440/1920 px; keyboard, focus, contrast, units and source labels.
- G10: clean local installation, executable demo runbook and release evidence.

A smoke training run cannot pass G7. Freeze benefit/downside thresholds before test results. A model that fails promotion remains disabled with measured results available; that is a valid research result. If meaningful training cannot run, explicitly mark learning incomplete with resumable commands and artifacts. Do not call the complete specified product finished in that state.

## Handoff and completion

Every handoff names changed paths, interfaces, commands actually run, exact results, measured hardware, unresolved failures and integration steps. Long jobs need checkpoints and durable progress; do not silently abandon them.

Produce `docs/handoffs/RELEASE_REPORT.md`: gate-by-gate status and evidence paths, installed versions, model/rule/source hashes, launch and reproduction commands, measured versus assumed behavior, known limitations and available baseline. Screenshots alone prove neither learning nor closed-loop operation.

Review UI against revision 2: compact instructions, meaningful channels, aligned values/units, restrained colour and honest empty states. Remove decorative numbering, slogans, arbitrary cards, fake activity and fake confidence. Mockup fixtures are not production telemetry.

Continue until authorized work is complete or a concrete external blocker prevents it. Resolve routine reversible implementation choices using these specifications and record them. Do not repeatedly ask about timeline or framework preferences. Never conceal an unresolved dependency behind a mocked success.
