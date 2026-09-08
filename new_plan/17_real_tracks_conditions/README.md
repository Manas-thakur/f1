# Real circuits and race conditions

This module converts actual Formula 1 circuits and event conditions into versioned simulation packages. It replaces the illustrative test loop when the product runs a real-circuit scenario. It does not claim that public telemetry exposes battery state or that a map image is a driveable digital twin.

## Required reading

1. [2026 circuit registry](TRACK_REGISTRY_2026.md)
2. [Track-data pipeline](TRACK_DATA_PIPELINE.md)
3. [Race-condition model](RACE_CONDITION_MODEL.md)
4. [Factor and influence model](FACTOR_AND_INFLUENCE.md)
5. [RL generalisation protocol](RL_TRACK_GENERALISATION.md)
6. [Validation and acceptance](VALIDATION.md)

Machine-readable inputs:

- [2026 event registry](season_2026_registry.json)
- [track package schema](track-package.schema.json)
- [Monza manifest example](monza-2026.example.json)

## Ownership

Create production code under `new_plan/implementation/packages/core/afterlap_core/tracks/` and tests under `new_plan/implementation/tests/tracks/`. This module owns ingestion, compilation, track manifests and condition sampling. It proposes contract changes through the coordinator. It does not edit the simulator, rules engine, estimator, planner or learning code directly.

## Product invariant

Every run pins a track-package hash and an event-package hash. Geometry, official activation lines, energy limits and observed weather may come from different sources and must retain separate provenance. A newer FIA event document creates a new event package; it never mutates an archived run.

The simulator receives a continuous centreline, boundaries and environment fields. The controller receives only permitted lookahead and observations. Privileged track geometry may be known because the circuit is known. Privileged rival energy and future weather remain hidden.

## What “real track” means

A track package is eligible for simulation only when it has metric centreline geometry, elevation, direction, start/finish, pit-lane exclusion, width or conservative corridor, corners/sectors and source/licence records. A race event additionally requires the event-specific FIA circuit map, Power Unit Information and applicable race-control state. Formula1.com length/lap counts are registry checks, not sufficient geometry.

Public historical observations calibrate pace, weather and traffic distributions. Synthetic vehicle coefficients still require explicit assumptions until authorised data is available. Real circuit shape plus invented battery truth must be labelled a real-circuit synthetic scenario.
