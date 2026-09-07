# Model inventory, data and ownership

## Selected models

| Component | Implementation | Input → output | Owner |
|---|---|---|---|
| Own-car estimate | Motion EKF plus battery power integration and measurement correction | Timestamped own observations → state mean, covariance and freshness | A05 |
| Rival belief | 128 weighted particles across conserve/normal/attack/defend modes | Gap/pace history and context → correlated energy/pace/mode hypotheses | A05 |
| Energy strategy | SB3 feed-forward SAC actor | 192 masked observation values → 2 budget preferences | A07 |
| Continuation return | Five independent 2-layer MLP regressors | Same feature contract at horizon → ordinary return mean and model disagreement | A07 |
| Probability calibration | Frozen sigmoid mapping per supported outcome definition | Scenario-frequency log odds → calibrated event probability | A07 with A13 |

Particle count, network sizes and training defaults are initial settings to profile. The first release does not require a Transformer, a language model, self-play population training or a learned replacement for vehicle dynamics. Engineer explanations come from checked reason codes and numeric differences. No LLM is in the planning loop.

## Own-car estimation

Use a state such as progress, speed, acceleration and battery energy. Propagate motion using declared process noise and measured input; integrate energy at the explicitly defined electrical bus. Apply sensor correction only for available measurements. Covariance evolves with elapsed time and clock uncertainty. Missing absolute energy cannot be fixed by a clever model: without an initialized trustworthy energy interval, the session loses precise energy-advice capability.

Tune process/measurement noise on calibration trajectories and assess normalized innovations and interval coverage on separate trajectories. Numerical linearisation and covariance propagation require their own tests. Do not force tiny covariance to make the interface look confident. Document the initial energy source and every subsequent correction.

## Rival particle filter

Each particle contains energy hypothesis, pace bias, behaviour mode and mode-memory state. Propagate through the same available context using a simplified rival model. Compute likelihood of observed gap/speed changes, including own-state uncertainty and model residual variance. Update log weights, normalise with log-sum-exp and resample systematically when effective sample size drops below N/2. Apply bounded process noise after resampling; preserve legal energy ranges and nonzero mode support.

Use a mode transition matrix declared in a manifest. Estimate it from synthetic opponent trajectories or explicitly label a hand-authored prior. Observationally similar behaviours must remain ambiguous. A fast rival could have different tyres, aero, engine output or deployment. Battery uncertainty must not collapse just because acceleration is observed.

Inference cannot read the opponent generator's policy name or internal state. The offline scoring process may compare against hidden simulation labels after the run; keep those labels in a different dataset/table and import path. Snapshot particles, RNG state, mode memory and observation history for reproducibility.

## Data layers

1. Source events: raw observations, source timestamps, arrival times, capability flags and IDs.
2. Causal estimates: estimate cutoff, feature inputs, masks and uncertainty. No later smoothing for operational training features.
3. Transitions: observation, raw SAC action, decoded preference, actual plan hash, executed input, reward components, next observation, termination/truncation flags.
4. Privileged evaluation labels: simulator truth, opponent state and actual outcomes. Used only by offline metrics and legitimate supervised target construction.
5. Manifests: scenario/track/car/rule/model/objective/normalizer hashes, seed family and code revision.

Partition Parquet by dataset version and scenario family, with episode identifiers inside each file. Avoid a tiny file per physics tick. Store float64 raw physical quantities and float32 neural inputs. A transition is committed only when its next observation and outcome are known; interrupted partial records retain explicit status.

## Splits and data generation

Define disjoint manifests before experimentation: training, tuning, calibration, final test. Split whole episodes and group by track layout, opponent policy identity and car parameter combination. No adjacent-frame random split. Hold out complete synthetic track layouts and unusual parameter combinations; disclose the exact scope. A public race can inform geometry/pace context without becoming true energy labels.

Generate reference episodes with legal fixed schedule, legal greedy attacker and MPC-only. Include poor outcomes and withdrawn advice. Domain randomization samples physically coherent parameter sets; do not independently sample incompatible drag, acceleration and power envelopes. Save sampled parameters in privileged manifests. Validate simulator convergence and energy accounting before creating large datasets.

Collect calibration runs using the frozen candidate distribution as well as baseline runs. Do not calibrate the final test after observing its outcomes. If test failures inform a redesign, retire that set as development data and allocate a new final test.

## Dataset acceptance

- Every feature timestamp is at or before its decision cutoff.
- Episode/scenario IDs do not cross protected splits.
- No WorldState, rival truth or reward label appears in the feature object.
- Replacing all hidden rival states while holding visible observations fixed produces identical features and beliefs.
- Raw action, projected preference and actual execution are separately recoverable.
- Units, masks, missing-value conventions and normalizer hashes are explicit.
- Corrupt/truncated records are quarantined and counted, not silently removed from the denominator.

Create a dataset card listing source permissions, synthetic assumptions, population coverage, excluded cases and known simulator deficiencies. Never report simulation accuracy as real-car model accuracy.
