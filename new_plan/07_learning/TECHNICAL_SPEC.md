# Reinforcement learning and terminal value

## Deliverable

Implement `packages/core/learning/` plus training/evaluation CLI jobs. Use SAC with a small continuous action: upcoming segment energy budget and checkpoint energy target. Policy proposes preferences; the same constrained planner/feasibility path used in evaluation resolves them. No steering, brake-by-wire or real-car network actuation.

## Environment

Gymnasium wrapper exposes the exact StateEstimate feature contract, not WorldState. Include own energy/pace/thermal information, track lookahead, race remaining distance, applicable rule context, rival beliefs, observation age, current profile and recent history. Missing values use explicit masks and calibrated fill conventions. Store feature order, normalisation and units in a hashed manifest. A standard feed-forward SAC implementation can consume engineered history summaries; do not claim it is recurrent without implementing and testing a recurrent algorithm.

Use a fixed tactical decision cadence for initial training and variable integrator substeps beneath it. If later actions have variable durations, correctly adapt discount/return calculations rather than assuming each step has the same elapsed time. Select a discount horizon consistent with several laps; default gamma values may undervalue delayed consequences.

## Reward and terminal values

Reward elapsed time and terminal racing outcome through a declared objective revision. Do not give repeatable positive rewards merely for overtaking and being repassed. Regulatory violations are rejected externally, and attempted invalid preferences are recorded for diagnostics. Constraint success is not learned by assigning a large negative reward alone. Include instruction churn/execution cost so the policy cannot rely on impossible driver reactions.

Train a separate value estimator on ordinary realised continuation returns from frozen-policy/MPC rollouts. This avoids using entropy-regularised SAC Q as a physical race forecast. Calibrate and bound terminal predictions. The value network must use only information available at its observation cutoff. At true finish, no reward for unused battery beyond applicable physical constraints; at truncation, bootstrap correctly.

## Training pipeline

Generate legal reference trajectories; optionally behaviour-clone initial budget proposals. Train through single-car energy tasks, then two-car attack/defence, then traffic and delays. Randomise physically plausible car parameters, energy initialisation, observations and opponent populations. Keep held-out parameter combinations and whole track layouts. Use multiple random seeds and immutable experiment manifests. Never train on test seeds after examining their failures without retiring that test set.

## Serving

Export a frozen model bundle with weights, feature schema, normalizer, approved scenario family, source pack hashes and benchmark evidence. Infer deterministically during operational simulation. Runtime adaptation updates beliefs, not policy weights. If manifest/features/rules disagree, reject the bundle and identify the baseline. Promotion is coordinator-controlled and requires the ablation protocol.

See [training and promotion](TRAINING_AND_PROMOTION.md) for exact evaluation procedure and [research sources](../16_sources/SOURCE_REGISTER.md) for SAC and predictive-control references.


## Detailed implementation contract

Follow the [ML/RL implementation guide](README.md) for the exact feature shape, cadence, initial training settings, ordinary-return fitting and deployment interfaces. These details refine this module overview.
