# Training, ablation and promotion

## Experiment manifest

Record source revision, environment hash, physics integrator, rule family, observation schema, random seeds, opponent population, reward/discount definition, SAC hyperparameters, normalizer, training steps, hardware and elapsed time. Store checkpoints and learning curves; a high training reward is not a promotion result.

## Splits

Split by track, scenario family, car parameter combinations and opponent policy identity. Separate train, tuning and final test manifests. Adjacent frames of the same race cannot be split into train/test to imply independent generalisation. Test data is opened only for candidate promotion. If it informs redesign, designate a new held-out test set for the final claim.

## Baselines and ablations

Compare legal fixed schedule, legal greedy attacker, MPC-only and full system using equivalent observations and external conditions. Add an ablation disabling only learned terminal value, and one disabling only policy warm-start. This identifies whether RL contributes accuracy, longer-horizon value or just speed. Report solver compute budget and failed/withdrawn decisions so a method cannot appear better by ignoring hard cases.

## Metrics

Primary: finish/segment position and elapsed time with paired confidence intervals. Secondary: pass retained at named checkpoint, energy at future critical checkpoints, constraint attempts/rejections, actual violations, poor-tail utility, probability calibration, recommendation churn, execution success, p50/p95/p99 latency and failure-mode coverage. For uncertainty intervals use paired bootstrap over independent scenarios/seeds, not every telemetry sample as an independent observation.

## Promotion policy

Before training, coordinator freezes a meaningful benefit margin and non-inferiority limits for downside/latency in `configs/benchmarks/promotion.yaml`. Values must be justified, not selected after seeing test results. A candidate must pass all hard invariants, improve the declared primary objective relative to MPC-only with appropriate statistical evidence, and remain within downside/latency limits. If it does not, leave the deployed learned contribution disabled; the research work remains available.

## Failure investigation

Archive all losses, not just wins. Group by energy depletion, eligibility discontinuity, opponent mismatch, inadequate horizon, simulator exploitation, bad probabilities and delayed execution. Reproduce from snapshot and locate the earliest divergence between expected and realised state. Fix model/observation/reward defects before adding neural-network capacity. Include perturbed dynamics and independent ledger checks to expose simulator loopholes.

## Suggested interfaces

`train --manifest ...`; `evaluate --candidate ... --benchmark ...`; `ablate --candidate ... --disable policy|terminal`; `package --candidate ... --report ...`; `promote --bundle ... --approval ...`. These are future CLI contracts, not commands already implemented in this documentation package.


## Detailed implementation contract

Follow the [ML/RL implementation guide](README.md) for the exact feature shape, cadence, initial training settings, ordinary-return fitting and deployment interfaces. These details refine this module overview.
