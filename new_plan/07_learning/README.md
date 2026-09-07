# ML and RL implementation guide

Learning contributes delayed energy strategy. It does not replace constraints, rule checking or engineer authority. Feature count alone does not justify RL; delayed consequences and action-dependent future states do. Its benefit must be measured against an equally informed predictive planner.

Read in order:

1. [Model and data specification](MODEL_AND_DATA_SPEC.md).
2. [Environment and exact feature contract](ENVIRONMENT_AND_FEATURES.md).
3. [SAC algorithm and training recipe](SAC_IMPLEMENTATION.md).
4. [Continuation value and calibration](VALUE_AND_CALIBRATION.md).
5. [Serving and evaluation](SERVING_AND_EVALUATION.md).
6. Existing [technical scope](TECHNICAL_SPEC.md) and [promotion policy](TRAINING_AND_PROMOTION.md).

These specify an initial implementable design. Hyperparameters, scales and reward weights are engineering starting settings, not optimal values or FIA constants. Freeze them in manifests and validate them.

At a one-second policy tick, a 192-element masked observation enters SAC. Two outputs express upcoming deployment budget and reserve preference. Constrained planning considers the learned proposal alongside baseline candidates, then an independent checker validates the executable result. Driver latency and actual execution affect the next state. Training observes realised utility; operational inference updates no weights.

A separately trained supervised ensemble supplies ordinary continuation return beyond the explicit horizon. A belief filter models hidden opponent hypotheses. Neither can label inferred rival energy as measured battery telemetry.
