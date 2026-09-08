# A16 — real circuits and race conditions

Implement actual-circuit packaging and race-condition sampling for AFTERLAP. Work is complete only when validated packages drive the simulator; displaying circuit names or maps is insufficient.

## Read first

Read `docs/AGENTS.md`, the selected stack and contracts, simulation/rules/estimation/learning specifications, and every file in this folder. Verify external facts against current FIA event documents. A calendar or Power Unit Information document may change after this plan's snapshot.

## Write scope

Own `implementation/packages/core/afterlap_core/tracks/`, `implementation/configs/tracks/`, `implementation/configs/conditions/`, `implementation/tests/tracks/` and `docs/handoffs/A16.md`. Ask the coordinator to integrate schema, CLI, dependency or simulator changes. Do not edit other workers' modules or parent content.

## Delivery sequence

1. Implement source manifests, raw cache and track/event package schema validation.
2. Build metric centreline compiler with periodic smoothing, arc length, curvature, grade and alignment.
3. Implement geometry QA and comparison reports.
4. Ingest event-specific FIA lines/curves into a two-reviewer queue with pass/fail/unknown rules.
5. Build historical OpenF1/FastF1 condition adapters with provenance and rate/cache controls.
6. Implement coherent weather, surface, tyre and race-control scenario tapes.
7. Qualify Monza, Monaco, Spa, Suzuka, Mexico City and Singapore before scaling across the registry.
8. Integrate one package into the simulator through a coordinator-owned contract and prove that geometry/conditions change physical energy and battle outcomes.

## Acceptance

Run schema, closure/length/orientation, source-revision, density/wind, correlation, deterministic-tape and hidden-truth tests. Compare an independent energy ledger at real track landmarks. Show failure on missing corridor or unrevised FIA overlay. Record exact sources, permissions, hashes, commands and numerical results.

No package reaches simulation-eligible through a manually changed status field. A validator creates the status from evidence. Do not infer battery state from public telemetry or trace official map artwork into geometry without permission and metric validation.
