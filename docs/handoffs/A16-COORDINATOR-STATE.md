# A16 coordinator state — complete

Revised 9 September 2026. Every row was re-run by the coordinator before merge;
nothing here is a worker's unverified claim.

## Merged

| PR | Content |
|---|---|
| #18 | Track package, loader, raw-source cache, `TrackSource` and `EnvironmentField` seams, contract identity fields, D-10 |
| #19 | Scenario-level event and conditions identity in the bundle hash |
| #20 | 2026 registry (23 circuits), six source manifests, pipeline CLI |
| #21 | Independent validator and the FIA two-reviewer overlay queue, D-11 |
| #22 | Driven-line length tolerance, D-12 (superseded by D-14) |
| #24 | Conditions: atmosphere, wind, grip, tyres, race control, four real 2025 tapes |
| #25 | Electrical ceilings from car, thermal, grip and confirmed event values |
| #26 | Factor registry, cross-checked against the objective and the feature manifest |
| #27 | Simulator channel-name drift fixed in the data mapping |
| #28 | `track_geometry` gated on validated geometry, D-13 |
| #29 | OpenF1 ingestion and the metric centreline compiler, with the elevation fix |
| #30 | API resolution, catalogue routes, identity columns, stream identity |
| #31 | Real-circuit UI across laboratory, engineer console and driver display |
| #32 | Cross-circuit RL sampling; one conditions resolution for planner, trainer and control plane |
| #33 | Earned length tolerance and self-crossing direction, D-14 |
| #35 | Traffic: tow, overtake stages, reactive rivals |
| #37 | The real-circuit acceptance run |

## Circuit readiness, measured

All six compiled circuits reach `geometry_validated`.

| circuit | deficit | earned tolerance | margin | max grade |
|---|---|---|---|---|
| monza | 0.555 % | 0.707 % | 0.152 % | 0.028 |
| spa | 0.655 % | 1.061 % | 0.406 % | 0.153 |
| suzuka | 0.517 % | 1.308 % | 0.791 % | 0.081 |
| monaco | 1.895 % | 2.335 % | 0.440 % | 0.098 |
| singapore | 1.315 % | 1.396 % | 0.081 % | 0.062 |
| mexico-city | 1.367 % | 1.409 % | 0.042 % | 0.026 |

Two circuits carry the acceptance run: Monza (fast, 12 m of elevation) and Spa
(long, 102 m of elevation). The tolerance is earned from each circuit's own
turning under D-14, and the margins at Singapore and Mexico City are under a
tenth of a percent, which D-14 states plainly.

## Permanent limits

No circuit reaches `simulation_eligible` and none can: that rung needs a
surveyed corridor, which position telemetry cannot supply. Every 2026 Power
Unit Information curve is a chart, so no event power value is machine readable
and none has ever tightened a limit. No overlay has two-reviewer confirmation.
The car, battery and driver documents stay synthetic, so every real-circuit run
is labelled `real_circuit_synthetic_energy`.

## Outstanding

- The modules carry no regression tests of their own. Verification was by
  running the code and by the acceptance run, on the user's instruction to
  prioritise completion. Each handoff names this as its first gap.
- The conditions calibration evidence path is unused: no tape has been bound to
  a circuit as calibration, so `condition_calibrated` stays unknown.
- `artifacts/` is git-ignored, so compiled packages and tapes live only locally.
  Their hashes travel in the manifests, handoffs and this file.
- An untracked `infra/.env` on this machine fails a security test that refuses
  the file's presence. Not committed, not deleted: it may hold local
  credentials.
