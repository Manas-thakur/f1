# A16 coordinator state

Updated 2026-09-09 after the model switch. Rows marked integrated were re-run
by the coordinator before merge; nothing here is a worker's unverified claim.

## Integrated on `main`

| PR | Content |
|---|---|
| #18 | Wave 0: `TrackPackage`/loader/`RawSourceCache`, `TrackSource` + `EnvironmentField` seams, engine hooks, session-contract identity fields, D-10 |
| #19 | `ScenarioConfig.event_id/conditions_id`; `ScenarioBundle.environment/environment_hash` in `bundle_hash` |
| #20 | A16-1 registry (23 circuits), six source manifests, pipeline CLI |
| #21 | A16-3 independent validator + FIA overlay two-reviewer queue; D-11 (OpenF1 CC BY-NC-SA 4.0) |
| #22 | D-12 justified 1 % driven-line length tolerance; Monza → `geometry_validated` |
| #24 | A16-4 conditions package, six condition docs, four real 2025 tapes |
| #25 | A16-5 `ElectricalLimits`: car, thermal, grip and confirmed-event electrical ceilings |

Verified facts: `load_track("monza")` returns a `CompiledTrackSource` and the
engine runs on it; Mexico City tape density 0.909 vs Monza 1.155 kg/m³; Spa
grip 0.55 during recorded rain; `tests/tracks` (minus the two in-flight compile
tests), `tests/conditions`, `tests/simulation`, `tests/numerics`, backend, api,
evaluation, learning, contracts all green at the last merge.

## Circuit readiness, measured by the independent validator

| circuit | status | arc length vs official | closure | failing check |
|---|---|---|---|---|
| monza | geometry_validated | 0.569 % | 3e-7 m | - |
| spa | geometry_validated | 0.653 % | 1e-6 m | - |
| monaco | discovered | 1.840 % | 8e-4 m | length_official |
| mexico-city | discovered | 1.365 % | 8e-5 m | length_official |
| singapore | discovered | 1.313 % | 2e-5 m | length_official |
| suzuka | rejected | 0.390 % | 3e-7 m | grade_bounded |

Two circuits can drive the simulator: Monza (fast, nearly flat: 12.5 m of
elevation, max grade 0.029) and Spa (long, 102 m of elevation, max grade
0.150). They are physically different, which is what the acceptance run
needs. Three circuits are short of the official length by more than the
declared 1 % driven-line tolerance and stay `discovered`; the tolerance was
NOT relaxed to move them. Suzuka's elevation span is right (40.3 m) but 39 of
5800 samples carry grades up to 0.907, which would inject fake gravitational
load, so it is rejected pending a z-channel fix.

No circuit reaches `simulation_eligible`, and none can: that rung needs a
surveyed corridor, and location telemetry cannot supply one. Real-circuit runs
are therefore `geometry_validated` scenarios labelled
`real_circuit_synthetic_energy`. No conditions calibration evidence exists
either, so `condition_calibrated` stays unknown.

## In flight

| Worker | Scope | State |
|---|---|---|
| A16-2b | z-channel outlier fix, recompile and revalidate, `handoffs/A16-2.md` | running |
| A16-6 | wake/tow, overtake stages, reactive rivals | running |
| A16-7b | tests for the circuit split, sampler and real-circuit Gym env | running |
| A16-8 | session factory resolution, track/conditions routes, persistence columns, stream identity | running |

## Not started

A16-9 UI (Lab track selector with
readiness, SVG map from `/api/tracks/{id}/centreline`, engineer/driver show
circuit + readiness + `real_circuit_synthetic_energy`); A16-10 cross-circuit
evaluation and the 13-point E2E on two circuits with disconnection tripwires.

## Open decisions and external items

- PR #23 (another contributor, "Lift product code to the repository root") is
  open and conflicts with every A16 branch; not touched.
- Local uncommitted edits under `apps/web` and `new_plan/12_design` are not
  from A16 workers; not touched.
- FIA power curves are chart-only in every 2026 PUI: `standard_curve`/
  `overtake_curve` stay unknown (D-12). No human review has been recorded on
  any overlay; effective values are all `None`.
- `artifacts/` is git-ignored; compiled packages and tapes exist only locally
  with their hashes recorded in handoffs and manifests.
