# Ordinary continuation value and outcome calibration

## Target definition

Train a separate supervised value ensemble to estimate the **ordinary discounted continuation utility** under a named frozen continuation controller. Exclude SAC entropy from labels. For observation cutoff t, generate a rollout using that frozen controller and construct:

```text
G[t] = r[t] + gamma*r[t+1] + ... + gamma^(T-t-1)*r[T-1]
```

Reward definition, gamma, potential shaping and true terminal treatment must be exactly the environment revision. Do not describe this number as seconds. Store elapsed time and finish position as separate evaluation fields. If the target is generated under a different controller, its bundle must name that controller; it is not a universal optimal value function.

For initial fitting, use complete short scenario episodes with real terminal outcomes. Do not assign zero continuation at an arbitrary cutoff. Longer rollout truncations require a separately justified bootstrap target and explicit confidence; keep them out of the first complete-return training set.

## Data construction

Freeze actor, planner and simulator versions. Collect complete rollouts across training scenarios including baseline trajectories, candidate states, low-energy failures and perturbed states within the declared support. At selected cutoffs save the **causal estimate** and its ordinary return. Offline truth may define realised outcomes, but never replaces the saved estimate with a smoothed future-aware state.

Group by complete episode and scenario when splitting train/tuning/calibration. Closely spaced cutoffs have correlated targets; sample/weight to stop long episodes dominating. Record sampling weights and continuation policy mixture. A mixture target estimates that named mixture, not any arbitrary future controller.

## Ensemble fitting

Use five independent MLPs with input 192, hidden [256,256], ReLU and scalar output. Initial settings: Adam 1e-3, batch 512, Huber loss with delta 1 on standardized returns, weight decay 1e-4. Standardize targets using training-only mean/std and invert before scoring. Bootstrap complete episodes for each member; vary initialization. Early stop using tuning episode error, patience 10 validation checks, saving the best epoch. These are starting settings to validate, not fixed scientific truths.

Report MAE/RMSE and bias by remaining distance, energy regime, track and opponent family. Ensemble disagreement approximates model uncertainty; it is not a calibrated prediction interval or collision probability. Fit empirical residual intervals on separate calibration episodes and report coverage by group. If calibration sample count is inadequate, report unavailable rather than a precise 95% band.

## MPC integration without hidden differentiation assumptions

Version 1 applies learned continuation in **outer candidate scoring**. acados solves a bounded candidate set using smooth dynamics and analytic terminal terms. Roll out feasible finalists across correlated rival scenarios to the explicit horizon, encode each terminal belief state and batch-evaluate the ensemble in PyTorch. This avoids pretending a PyTorch module is automatically differentiable inside the compiled solver.

For finalist c and scenario w, compute discounted explicit reward plus `gamma^H * V(terminal_estimate)`, with H in policy seconds and the same reward basis. Where solver grids use finer substeps, aggregate to that time basis. Near-term controls shared across scenarios remain non-anticipative. Predictions cannot use observations that would only become available after the horizon.

Retain baseline candidates so SAC cannot remove a feasible reference. Add a configured disagreement penalty to the utility loss before the existing scenario-tail objective. This penalty is a conservative heuristic, not a mathematical safety guarantee. Do not count both analytic and learned terminal reward: learned scoring replaces the analytic continuation **for reranking**, while analytic terms remain only in candidate generation. Log generation score and final score separately.

This design does not find the exact optimum of a neural terminal objective; quality depends on candidate coverage. Include candidate-count/compute-budget sensitivity and make the limitation explicit. Later direct symbolic network embedding would be an architecture revision with numerical equivalence/gradient tests.

If features are unsupported, rule family differs, residual support is poor or ensemble disagreement exceeds a frozen calibration threshold, disable learned scoring for that decision and identify baseline. Derive thresholds from calibration data and freeze them before final testing; a constant chosen after a loss is not a valid deployment gate.

## Pass and retained-position probabilities

These come from weighted scenario outcomes, not actor entropy or critic Q. Define labels separately: pass before checkpoint, ahead at checkpoint, and ahead at later retention checkpoint. Unknown lateral geometry cannot produce a precise contact-risk probability.

For supported events, fit a sigmoid on clipped raw scenario-frequency log odds using independent calibration episodes. Freeze event definition, checkpoint rule, controller version and valid regime. A calibration set with only positives/negatives is insufficient. Show raw frequency, calibrated probability and calibration status separately in decision records.

Report reliability diagrams with bin counts, Brier score, log loss and subgroup results. Brier score includes effects beyond calibration; a lower value alone does not establish reliable probabilities. Use cluster resampling over scenarios for uncertainty, not independent draws per telemetry frame. A finite scenario ensemble is neither a guarantee of universal safety nor a source of unlimited confidence.

## Tests and artifacts

- Hand-computed return including finish and truncation; no entropy term.
- Terminal value is zero at true finish.
- Explicit plus terminal reward has no overlap/double count.
- Learned-disabled scoring matches baseline exactly.
- Prediction from fixed observations is independent of hidden simulator truth.
- All models/scalers load with feature hashes; inverted target scale matches training units.
- Batch and single inference agree within declared float tolerance.
- Out-of-support models disable safely and emit reason codes.

Artifacts: per-member weights, training/tuning manifest, target scaler, episode bootstrap IDs, return-definition hash, continuation-controller hash, calibration residuals, fit metrics and model card.

[Scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html) explains calibration data separation, reliability diagrams and scoring caveats. The ensemble and planner-integration choices here are project design decisions.
