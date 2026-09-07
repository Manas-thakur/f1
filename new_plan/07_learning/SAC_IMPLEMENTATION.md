# SAC training implementation

## Why this algorithm

The action is two bounded continuous preferences, so select Stable-Baselines3 SAC with MlpPolicy. Its off-policy replay can reuse expensive simulation transitions. This is a reason to test SAC, not evidence that it outperforms MPC. Use the library implementation; do not casually rewrite actor entropy, target critics or action squashing.

The [official SAC documentation](https://stable-baselines3.readthedocs.io/en/master/modules/sac.html) supports continuous Box actions and does not provide recurrent policies. Our history features make the initial implementation compatible with a feed-forward actor. We do not claim that finite history makes partial observation perfectly Markov.

## Networks and objective

Actor: 192 input values → 256 ReLU → 256 ReLU → mean and log-standard-deviation heads for a two-dimensional squashed Gaussian. Twin critics each read observation and action and output entropy-regularised Q. Serving uses the deterministic actor mean with the library's squashing/scaling convention.

In schematic notation:

```text
y = r + gamma * (1-terminated) * [min(Q1_target,Q2_target)(s',a') - alpha log pi(a'|s')]
critic_loss = MSE(Q1(s,a), y) + MSE(Q2(s,a), y)
actor_loss = E[alpha log pi(a|s) - min(Q1,Q2)(s,a)]
```

The timeout correction must preserve final observations as described in ENVIRONMENT_AND_FEATURES. Automatic-reset observations from a new episode are never a valid bootstrap state for the old one. Soft Q is **not** a race-time estimate or the MPC continuation value.

## Initial experiment settings

| Parameter | Starting configuration | What to inspect |
|---|---|---|
| Actor/critic hidden layers | [256,256], ReLU | Learning stability and inference cost; no automatic capacity growth. |
| Learning rate | 3e-4 | Critic divergence and sensitivity on tuning set. |
| Batch size | 256 | CPU/GPU utilization and gradient stability. |
| Replay capacity | 500,000 transitions | Approximately 0.8 GB for two float32 192-element observations alone; allocate overhead separately. |
| Learning starts | 10,000 transitions | Warm-up covers legal projection and different energy regimes. |
| Gamma | exp(-1/300) | One-second cadence; assess horizon sensitivity. |
| Target update tau | 0.005 | Target stability. |
| Entropy coefficient | auto | Log alpha/entropy; do not hand-label exploration as uncertainty. |
| Entropy target | -2, matching action dimension | Confirm library convention in pinned version. |
| Train frequency | One vector step | Record total transitions from all environments. |
| Gradient steps | Number of new transitions, e.g. 4 for 4 envs | Approximately one update per collected transition; profile compute. |
| Vector environments | Start with 4 subprocess environments | Cap BLAS threads per worker; avoid oversubscription. |
| Device | Explicit cpu or cuda in manifest | Small MLP plus expensive simulator may be CPU-bound; measure. |
| Seeds | At least 5 independent training seeds for final study | Final confidence includes training variation. |

These are starting settings, not measured optimal choices. A01 pins a released SB3/Gymnasium/PyTorch combination and checks callback/timeout behavior for that version. Do not copy a documentation master signature that may contain unreleased features.

## Training sequence and frozen components

1. Validate the environment and run 100 legal reference episodes. Inspect energy ledgers, driver delay and hidden-state isolation.
2. Run a 10,000-transition smoke job solely to verify finite losses, checkpoints, resume and complete episodes. It is not a trained product.
3. Train single-car energy allocation with the same two-action semantics. Keep observation shape identical, with absent rival masks.
4. Introduce two-car attack/defence, then wider traffic and observation faults. Use a manifest-defined mixture of prior and new stages to reduce forgetting.
5. Train the actor against **frozen MPC-only/analytic continuation**. Environment behavior cannot change beneath its replay buffer because a value model is training elsewhere.
6. Freeze the actor, collect continuation rollouts and fit the separate ordinary-return ensemble.
7. Evaluate actor-only, value-only and combined system. If further actor training uses the frozen learned value, create a new environment revision and replay buffer; never mix transitions from different planner/value semantics without deliberate off-policy justification.

Keep physical action projection consistent between training and serving. Optional supervised pretraining is not required for v1; do not insert a behavior-cloning loss into SB3 without owning and validating the changed algorithm. The initial supported path is reference data for validation, followed by standard SAC training.

## Runtime budget and checkpoints

Benchmark at least 1,000 environment transitions before choosing total training steps. Record aggregate transitions/sec, solve latency, CPU, RAM and failures. Estimate wall time as transition target / measured throughput plus evaluation overhead. One million one-second transitions with a 100ms planner is already about 28 serial hours of planner time; vectorization may help but is not a guaranteed speedup. Short synthetic curricula and bounded solver candidate sets are essential engineering controls.

Run jobs in increments with checkpoint evaluation; choose the next allocation based on tuning curves rather than pretending a fixed step count guarantees quality. Save actor/critic/optimiser state, replay, RNGs, environment version, normalizer, step count and manifest atomically. Resume tests compare subsequent deterministic evaluation; GPU/platform bitwise equivalence is not promised.

Track reward terms separately, actual finish position/time, energy distributions, proposal projection distance, solver timeouts, instruction churn, observed executions, critic loss, entropy and throughput. A high reward with frequent withdrawals is a failure mode to investigate.

## Package and CLI ownership

Implement `learning/features.py`, `actions.py`, `env.py`, `reward.py`, `train_sac.py`, `callbacks.py`, `checkpoints.py`, plus tests under `tests/learning/`. Expose the command family through the coordinator CLI:

```text
python -m afterlap_core.cli train --manifest configs/learning/sac-v1.yaml
python -m afterlap_core.cli train --resume artifacts/<run>/checkpoint.json
python -m afterlap_core.cli evaluate --candidate <bundle> --benchmark <manifest>
```

These are implementation contracts, not commands already implemented by this documentation change. A job reports failed/unavailable accurately. No dummy weights, synthetic loss curves or training-success responses.


The [initial machine-readable configuration](training.example.json) records these defaults. It is input to a future CLI adapter, not a direct SB3 constructor payload: separate environment, algorithm, reward and promotion fields. It contains no trained model or measured results.
