# Cross-agent acceptance and handoff checklist

## First integrated vertical slice

Start with synthetic two-car scenario; step simulation; emit delayed own-car observations; estimate state; load synthetic reviewed rules; generate legal baseline plan; publish recommendation; select and communicate via API; execute deliberately in simulator; observe execution; record named checkpoint outcome. This must work before RL is involved. The UI must expose missing/stale states during the same run.

## Definition of integrated

| Boundary | Contract test |
|---|---|
| Simulator -> ingestion | Only observation fields, correct SI, no opponent truth |
| Ingestion -> estimator | Clock/order/replay handling and quality flags preserved |
| Estimator -> planner | Cutoff respected, nullable energy and uncertainty supported |
| Rules -> planner | Illegal profile excluded; unknown critical constraint suppresses advice |
| Planner -> independent checker | Checker can reject a converged solver result |
| Checker -> lifecycle | Revision, expiry and rule hash validated atomically |
| Engineer -> lifecycle | Idempotent selection does not imply execution |
| Simulator driver -> lifecycle | Executed profile and actual timing can differ from recommendation |
| Runtime -> UIs | Same authoritative revision, resync on gaps, visible provenance |
| Snapshot -> experiments | Full-state restoration, equal-action equivalence, reactive rival divergence |
| Training -> serving | Feature/normaliser/rules manifest match, frozen inference |
| Evaluation -> evidence UI | Missing results unavailable; losses and confidence intervals preserved |

## Worker handoff template

```markdown
# Axx handoff
Status: review-ready / blocked
Commit or patch reference:
Owned paths changed:
Public functions/types:
Contract version consumed:
Assumptions and provenance:
Tests (exact commands and outputs):
Measured performance (hardware and sample population):
Known limitations:
Integration instructions:
Contract proposals:
```

## Merge and review procedure

Coordinator compares handoff write set with assignment; rejects overlapping rewrites; runs contract vectors; integrates one module; runs its boundary tests; updates the status board; only then accepts the next dependency. Do not grant a frontend agent root router ownership merely to bypass coordination. Do not accept a simulator handoff without conservation and restore tests. Do not accept RL handoff solely from reward plots.

## Initial implementation test commands

Coordinator establishes `python -m pytest tests/contracts`, module-specific `python -m pytest tests/<module>`, and `npm run test` / `npm run test:e2e` in the new implementation workspace. These are required script contracts to create, not functioning commands in this documentation-only package. Record actual executable versions in lockfiles and the release manifest.

## Build versus research uncertainty

An agent can complete software interfaces and tests with synthetic calibration, but must label model realism unvalidated. Unknown real car parameters do not justify inventing measurements. Missing private FIA supporting information limits rules coverage; declare the unsupported context rather than marking the entire architecture blocked. Runtime capability modes make those boundaries explicit.
