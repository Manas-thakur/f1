# Validation and reproducibility

## Deliverable

Implement an independent benchmark harness in `packages/core/evaluation/` and cross-module `tests/acceptance/`. It consumes frozen scenarios, candidate controllers and evaluation manifests. It produces raw paired results, metrics, uncertainty intervals, failure cases and a machine-readable report. It must not share the planner's objective calculation blindly.

## Test layers

Contracts/units -> physical invariants -> rule thresholds -> observation isolation -> deterministic planning cases -> operator lifecycle -> closed-loop branches -> held-out stochastic benchmarks -> runtime/fault recovery. Use separately calculated expected values for energy and simple dynamics. Do not write assertions that merely repeat the implementation's formula call.

## Benchmark design

Fixed legal schedule, legal greedy controller, MPC-only and full system all receive equivalent observations. Run paired scenarios/seeds with independently reacting rivals. Separate terminal position, elapsed time, retained passes, checkpoint energy and constraint outcomes. Record withdrawals/timeouts rather than excluding them. A pass-retained event must have a named checkpoint/horizon fixed before evaluation.

Use training/tuning/test separation by track/parameters/opponent families. Confidence intervals resample independent scenario/seed units, not correlated telemetry frames. Show distributions and poor-tail cases, not only mean improvement. Assess probability calibration with reliability bins and Brier score using declared event labels; show support count. Report the effect of disabling learned components.

## Robustness matrix

Sweep data age, dropped energy channel, missing rules, changed rival response, low initial energy, thermal derating, line-boundary timing, delayed driver action, solver timeout, DB outage, worker crash and model hash mismatch. Test rule invalidation racing an operator selection. An unknown critical condition must not result in a confident active directive.

## Release gates

G0-G8 are defined in the execution plan. Publish each gate's status with test IDs, run date, source revision and evidence path. Physics fidelity, numerical convergence and real-car validation are separate statuses. Passing simulated tests is not certification. RL promotion needs predeclared meaningful benefit and downside/latency bounds, not post-hoc thresholds.

## Report format

Include manifest hashes, environment versions, hardware, scenario population, sample counts, missing/failed runs, paired estimates/intervals, per-family results, calibration, latency percentiles, all hard violations and reproducible losing snapshots. The UI evidence screen reads this report and displays unavailable for absent evidence. No frontend-computed fabricated win rate.
