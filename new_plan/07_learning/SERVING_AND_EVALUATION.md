# Model serving, ablation and release evidence

## Frozen bundle

Store actor weights, five value-member weights, feature/action manifests, normalizer, target scaler, probability calibrator, support thresholds and model card. Top-level JSON includes schema version, artifact SHA-256 map, training code revision, Python/library versions, simulator/checker/planner hashes, rule family, reward/discount revision, continuation controller, supported scenario families, evaluation report and promotion status.

Load only local approved artifacts and validate every hash before initialization. Use PyTorch state dictionaries and restricted weights-only loading where supported by the pinned version; never unpickle an arbitrary user-uploaded object. SB3 resume archives belong to trusted training jobs, not an unauthenticated model upload endpoint. Do not load a network by trusting a filename alone.

## Operational sequence

1. At session start validate compatibility and warm up CPU inference; pin the bundle for that session.
2. At the one-second actor tick encode the current causal estimate, checking masks, support and clip frequency.
3. Run deterministic inference under inference mode; validate finite output and decode bounded preferences.
4. Planner generates candidates, optionally uses supported learned continuation and independently checks the result.
5. Publish the accepted plan with active actor/value/calibrator versions and baseline/learned contribution flags.
6. Monitor data age, invalidation and execution between ticks. No policy weight updates or exploratory actions occur online.

Target actor+value inference p95 below 10ms on declared CPU hardware is an initial allocation within the 200ms overall planner target, not a measured promise. Batch value calls across finalists. Record full end-to-end age separately from neural inference time. If a deadline is exceeded, ignore late results; do not allow a completed stale model call to restore invalidated advice.

Missing own energy capability suppresses precise energy advice. Unsupported learned state disables learning while retaining a revalidated baseline when possible. If the baseline is also invalid, withdraw advice. Rule changes invalidate outstanding plans; model pinning does not override rule changes. Current recommendation provenance explicitly identifies the fallback.

## Required comparison matrix

| Controller | Actor | Learned return | Purpose |
|---|---|---|---|
| Legal fixed schedule | No | No | Reproducible simple reference |
| Legal greedy attacker | No | No | Cost of short-term strategy |
| MPC-only | No | No | Core engineering baseline |
| MPC + actor | Yes | No | Proposal contribution |
| MPC + value | No | Yes | Continuation contribution |
| Full system | Yes | Yes | Combined effect |

Use equal observation access, scenario starting state, exogenous randomness and explicit solver compute allowance. Opponents react independently in each branch; do not replay their controls as immutable truth. Report both under-equal-budget performance and raw compute cost. Failed/withdrawn decisions remain in denominators. A method cannot appear superior by declining difficult scenarios without showing that behavior.

## Test population and statistics

Freeze training/tuning/calibration/test manifests and primary utility before training. Initial study target: at least 100 independent test scenarios, stratified across scenario families, evaluated for each of five training seeds. This is a starting sample plan, not a power guarantee. Use tuning variance to estimate whether the planned benefit margin can be resolved; increase sample size before opening the final test when necessary.

Use hierarchical paired bootstrap: resample independent scenarios and training seeds, preserving controller pairing. Multiple observations from the same episode are not independent trials. Report 95% intervals for utility difference and physical outcomes, plus raw per-scenario results. Baselines without a training seed need no fabricated seed variation.

The coordinator must freeze numeric meaningful-benefit and downside/latency limits in `configs/benchmarks/promotion.yaml` after scenario commissioning but before final testing. Record rationale. These cannot be responsibly guessed as universal F1 performance margins in a documentation package. The system must refuse promotion when thresholds or evidence are missing.

Hard release checks include zero observed modeled rule/physical violations in the declared test suite, information isolation, model compatibility, expiry and successful failure drills. Zero observed violations is not a proof of safety outside the suite. Learned promotion requires the predeclared primary benefit over MPC-only and all downside/latency non-inferiority gates.

## Failure taxonomy and reports

Record energy depletion, missed response, poor opponent belief, unknown eligibility, infeasible projection, planner timeout, model support rejection, lost communication, simulator defect and infrastructure failure separately. Archive losing branches and the earliest expected/actual divergence. Do not discard an environment error as a normal low-reward episode; it is a reproducibility defect.

Report actual finish/segment position, elapsed time, retained pass rate at defined checkpoints, energy reserve, modelled violations, withdrawals, churn, p50/p95/p99 latency, calibration coverage and all operating assumptions. Include source hashes, hardware and the exact rerun command. No screenshots of a reward curve stand in for a held-out report.

## End-to-end acceptance cases

1. Same snapshot and controller reproduces decisions/trajectory within tolerance.
2. A different budget changes physical deployment and later energy, not only displayed text.
3. Identical visible observations with altered hidden rival truth yield identical features and actor output.
4. A missing/incorrect feature hash disables the model with visible baseline identity.
5. Stale telemetry withdraws both engineer and simulator-driver advice.
6. Actor-only/value-only ablations execute real alternatives and create comparable records.
7. Failed promotion leaves baseline enabled and the candidate report inspectable.
8. Restart resumes from approved pinned artifacts, not the newest training checkpoint.

The implemented learning pipeline can be complete even if learned promotion is rejected after a real experiment. If meaningful training/evaluation never ran, learning remains incomplete and must be reported that way.
