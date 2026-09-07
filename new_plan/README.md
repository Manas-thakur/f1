# TrackShift Energy & Overtake — implementation plan

This is a standalone greenfield specification. It does not depend on, inspect, or reuse anything elsewhere in the parent directory. Working product name: **AFTERLAP** (a provisional name, not a cleared trademark). Prepared 8 September 2026.

The intended product helps a race engineer choose an electrical deployment strategy, evaluate an attack and the subsequent defence, and review the outcome. It uses a calibrated reduced-order simulator, a constrained predictive planner, and a learned long-horizon energy strategy. It does not claim to be an FIA-certified control system.

## Start here

1. Read [project boundaries](AGENTS.md), [architecture](00_program/ARCHITECTURE.md), and [decisions](00_program/DECISIONS.md).
2. The coordinator follows [execution plan](00_program/EXECUTION_PLAN.md). Assign a module using its `AGENT_BRIEF.md`.
3. All agents read [domain contracts](01_contracts/DOMAIN_MODEL.md), [API](01_contracts/API.md), and [units and time](01_contracts/UNITS_TIME.md).
4. Open [the visual package](12_design/mockups/index.html). This links three UI concepts, the selected operating workspace, driver display, and two landing pages. Everything is local and uses illustrative fixtures.
5. Run the documentation checks: `python new_plan/tools/validate_package.py` from the parent directory. For browser preview, run `python -m http.server 8765 --bind 127.0.0.1 --directory new_plan/12_design/mockups` and visit `http://127.0.0.1:8765/`.

## Implementation additions

- [Selected technology stack](00_program/TECH_STACK.md): dependencies, processes, canonical code paths and build gates.
- [Master multi-agent build prompt](00_program/BUILD_WITH_AGENTS.md): give this entire document to Claude or Cursor to execute the plan.
- [Detailed ML/RL guide](07_learning/README.md): exact features, environment, SAC, ordinary-return models, calibration and serving.
- [Current design revision](12_design/DESIGN_REVISION_02.md): revised screens and implementation rules.

## Module map

| Folder | Responsibility |
|---|---|
| [00_program](00_program/ARCHITECTURE.md) | Product boundaries, architecture, decisions, integration order |
| [01_contracts](01_contracts/DOMAIN_MODEL.md) | Shared data types, wire schema, events, REST/WebSocket contracts |
| [02_data](02_data/TECHNICAL_SPEC.md) | Ingestion, clocks, source provenance, recording and replay |
| [03_simulation](03_simulation/TECHNICAL_SPEC.md) | Physics, battery, track, opponents, deterministic branching |
| [04_rules](04_rules/TECHNICAL_SPEC.md) | Versioned regulations and independent plan validation |
| [05_estimation](05_estimation/TECHNICAL_SPEC.md) | Own-car state, hidden opponent state, uncertainty |
| [06_planning](06_planning/TECHNICAL_SPEC.md) | Scenario MPC, tactical candidates, recommendations |
| [07_learning](07_learning/TECHNICAL_SPEC.md) | SAC, long-horizon value, training, promotion |
| [08_backend](08_backend/TECHNICAL_SPEC.md) | API, sessions, persistence, workers, operator authority |
| [09_engineer_console](09_engineer_console/TECHNICAL_SPEC.md) | Race engineer workflow and evidence inspection |
| [10_simulation_lab](10_simulation_lab/TECHNICAL_SPEC.md) | Scenarios, branching, experiments, replay |
| [11_driver_display](11_driver_display/TECHNICAL_SPEC.md) | Simulator-only driver interface and lifecycle |
| [12_design](12_design/DESIGN_SYSTEM.md) | Research, concept comparison, screen specifications, mockups |
| [13_validation](13_validation/TECHNICAL_SPEC.md) | Benchmarks, calibration, numerical and end-to-end validation |
| [14_operations](14_operations/TECHNICAL_SPEC.md) | Deployment, observability, security, incident recovery |
| [15_presentation](15_presentation/DEMO_RUNBOOK.md) | Presentation narrative and honest claims |
| [16_sources](16_sources/SOURCE_REGISTER.md) | Official references, research and verification scope |

## What is delivered versus planned

Delivered here: specifications, coordination instructions, example wire objects, a scenario fixture, local interactive design prototypes, and package validation tooling. The mockups do not run physics, train RL, access real telemetry, or measure comparative performance. Their numbers are labelled illustrative. The evidence screen deliberately leaves actual benchmark results unmeasured.

See the [design QA report](12_design/QA_REPORT.md) for observed browser behavior, completed checks and remaining validation boundaries.

Future agents create production code **only under `new_plan/implementation/`** unless the user later changes that boundary. The mockups are a design reference, not the production frontend architecture. Documentation and source files outside the agent's ownership remain unchanged.

## Required outcome

A reproducible scenario can run through observation, estimation, legal planning, engineer selection, driver execution and outcome evaluation. Two interventions can branch from one complete snapshot with reactive opponents. Every output retains provenance, applicable rule version, model version and timestamps. RL is enabled only after outperforming the same planner without RL on held-out tests under the promotion protocol.
