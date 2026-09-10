# AFTERLAP documentation

Specifications, design, presentation materials and handoffs. Product code is at the repository root.

Working product name: **AFTERLAP**. Prepared 8 September 2026. The product helps a race engineer choose an electrical deployment strategy, evaluate an attack and the subsequent defence, and review the outcome. It does not claim to be an FIA-certified control system.

## Start here

1. Read [project boundaries](AGENTS.md), [architecture](program/ARCHITECTURE.md), and [decisions](program/DECISIONS.md).
2. The coordinator follows [execution plan](program/EXECUTION_PLAN.md). Assign a module using its `AGENT_BRIEF.md`.
3. All agents read [domain contracts](contracts/DOMAIN_MODEL.md), [API](contracts/API.md), and [units and time](contracts/UNITS_TIME.md).
4. Open [the visual package](design/mockups/index.html).
5. Run `python docs/tools/validate_package.py` from the repository root. Preview mockups with `python -m http.server 8765 --bind 127.0.0.1 --directory docs/design/mockups`.

## Implementation additions

- [Selected technology stack](program/TECH_STACK.md)
- [Master multi-agent build prompt](program/BUILD_WITH_AGENTS.md)
- [Detailed ML/RL guide](learning/README.md)
- [Current design revision](design/DESIGN_REVISION_02.md)

## Map

| Folder | Responsibility |
|---|---|
| [program](program/ARCHITECTURE.md) | Product boundaries, architecture, decisions, integration order |
| [contracts](contracts/DOMAIN_MODEL.md) | Shared data types, wire schema, events, REST/SSE contracts |
| [data](data/TECHNICAL_SPEC.md) | Ingestion, clocks, source provenance, recording and replay |
| [simulation](simulation/TECHNICAL_SPEC.md) | Physics, battery, track, opponents, deterministic branching |
| [rules](rules/TECHNICAL_SPEC.md) | Versioned regulations and independent plan validation |
| [estimation](estimation/TECHNICAL_SPEC.md) | Own-car state, hidden opponent state, uncertainty |
| [planning](planning/TECHNICAL_SPEC.md) | Scenario MPC, tactical candidates, recommendations |
| [learning](learning/TECHNICAL_SPEC.md) | SAC, long-horizon value, training, promotion |
| [backend](backend/TECHNICAL_SPEC.md) | API, sessions, persistence, workers, operator authority |
| [engineer-console](engineer-console/TECHNICAL_SPEC.md) | Race engineer workflow and evidence inspection |
| [simulation-lab](simulation-lab/TECHNICAL_SPEC.md) | Scenarios, branching, experiments, replay |
| [driver-display](driver-display/TECHNICAL_SPEC.md) | Simulator-only driver display and lifecycle |
| [design](design/DESIGN_SYSTEM.md) | Research, concept comparison, screen specifications, mockups |
| [validation](validation/TECHNICAL_SPEC.md) | Benchmarks, calibration, numerical and end-to-end validation |
| [operations](operations/TECHNICAL_SPEC.md) | Deployment, observability, security, incident recovery |
| [demo](demo/DEMO_RUNBOOK.md) | Presentation narrative and honest claims |
| [sources](sources/SOURCE_REGISTER.md) | Official references, research and verification scope |
| [tracks](tracks/README.md) | 2026 circuits, event overlays, race conditions and RL generalisation |
| [deck](deck/README.md) | Final-round deck, speaker notes, visual assets |
| [handoffs](handoffs/status.md) | Module delivery records |
| [tools](tools/validate_package.py) | Documentation package checks |

## Required outcome

A reproducible scenario can run through observation, estimation, legal planning, engineer selection, driver execution and outcome evaluation. Two interventions can branch from one complete snapshot with reactive opponents. Every output retains provenance, applicable rule version, model version and timestamps. RL is enabled only after outperforming the same planner without RL on held-out tests under the promotion protocol.
