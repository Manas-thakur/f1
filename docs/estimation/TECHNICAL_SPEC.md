# State estimation and opponent beliefs

## Deliverable

Implement `packages/core/estimation/`. `update(events, prior, context) -> StateEstimate` and `predict(estimate, target_time) -> StateEstimate`. Reject future observations beyond the cutoff. Keep a replayable estimator snapshot including covariance, particles, history and clock mapping.

## Own-car state

Use an extended Kalman filter for progress, velocity and acceleration if nonlinear relationships require it. Start with a documented motion process model and tune process/measurement noise using held-out residual coverage. Fuse speed/position with explicit clock uncertainty. Integrate measured battery-side power; correct with available battery-state measurements. If only partial energy information exists, propagate an interval/ensemble rather than collapsing it to a false precise value.

Battery observability gates deployment capability. A public-only replay can support context analysis and synthetic energy studies, but cannot issue a precise measured-energy recommendation. Store measurement provenance, observation age, residual and uncertainty for each estimated family.

## Opponent model

Use a finite mixture of reactive intentions (conserve/normal/attack/defend) with continuous pace/energy hypotheses. Initialise energy as a broad plausible prior only when the scenario's assumptions justify bounds. Update hypothesis weights from gap, acceleration and contextual likelihoods; normalise stably in log space and apply a minimum weight floor to avoid irreversible collapse. Maintain uncertainty from aero, tyre and engine ambiguity.

The operational model cannot read opponent truth from simulator state, RL info dictionaries or debug services. Tests should replace truth with unrelated values while holding observations fixed and confirm identical beliefs and decisions. If lateral placement is unavailable, mark geometry uncertain and avoid precise collision-risk claims.

## Scenario interface

`sample_scenarios(belief, count, seed)` returns weighted scenario trajectories/parameters for planner rollouts. Keep correlations across time: one sampled opponent cannot independently jump from empty to full battery each tick. Repeated planning may reuse particles with updated weights. Increase uncertainty under dropouts and model mismatch.

## Calibration and failure modes

Evaluate speed/progress RMSE, energy error where truth is legitimately available in simulation, interval coverage and behaviour classification calibration. Split by race/track, not adjacent rows. A 90% interval's empirical coverage should be measured and reported. Residual alarms trigger broader scenarios or analysis-only mode; they do not automatically retrain the live model. Test clocks, abrupt rival response, delayed observations, missing energy, false certainty and resumption after a feed gap.
