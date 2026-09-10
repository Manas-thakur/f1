# Simulation Lab, replay and branch comparison

## Deliverable

Implement `apps/web/src/features/lab/` and `features/replay/` plus typed experiment-job integration. Default routes are `/sessions/{id}/lab` and `/sessions/{id}/replay`. The backend simulator owns physics and snapshots. The frontend renders it and chooses experiments. Design reference: [lab](../design/mockups/app.html#lab), [replay](../design/mockups/app.html#replay).

## Scenario creation

Choose a reviewed track/car/ruleset manifest, seed, initial progress/gap/energy, opponent policy and observation conditions. Validate combinations before starting. Synthetic configurations display a persistent label. Parameter edits create a new scenario revision; they never mutate an archived experiment. Include delay and missing-channel controls for robustness testing, not just favourable passing setups.

## Run control

Start/pause/resume/step/stop use session commands. Speed control changes wall-time pacing only. A snapshot action requests the complete backend state at an event boundary and returns a hash. A timeline seek in replay restores the preceding snapshot and consumes events forward. Live-team sessions cannot seek their authoritative clock.

## Compare from here

Create one snapshot; choose reference strategy and candidate bundle; launch paired treatments with identical exogenous disturbance keys. Each branch runs its own responsive opponent and physics. Compare at common elapsed time or progress with clearly labelled alignment. Show original state, action difference, gap/energy trajectories, named checkpoint outcomes, constraints and uncertainty. A fixed historical rival trajectory is acceptable only in explicitly labelled observational replay, never as causal proof.

## Experiment jobs

Batch runs list seed count, tested scenario family, evaluation model revision and statuses. Provide queue/running/cancelled/failed/completed states. Cancellation preserves partial results labelled incomplete and excludes them from headline benchmark aggregates unless the protocol says otherwise. Download/export produces a manifest and trajectories, not just a screenshot.

## Debugging

Truth view requires simulation mode and explicit debug capability. It is visually separate and never feeds operational widgets. A sensitivity panel can vary one input across a declared range and plot outcome spread; resulting runs remain synthetic. A comparison summary should show losses as readily as wins.

## Acceptance

Test initialisation validation, pause invariance, snapshot/restore, branch equality with identical actions, diverging rival response after changed action, cancellation, failed jobs, dataset split metadata and provenance exports. Desktop supports side-by-side branches; mobile stacks them with common checkpoint labels. Missing experiment outputs render unmeasured, not zeros.
