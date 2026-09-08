# Product presentation runbook

## Opening

Open the engineer workspace on a controlled synthetic scenario. State the actual question: can the car pass now and still defend at the next opportunity? Identify simulated data, current rule coverage and model/evaluation version. Do not introduce a fictional real-team partnership.

## Demonstration sequence

1. Show current gap, available energy and a later counterattack checkpoint. Explain the decision in one sentence.
2. Let the implemented planner compute a recommendation; engineer selects and marks communicated; driver executes deliberately in the simulator. Selection and execution remain visibly different.
3. Follow the battle through the retained-position checkpoint, not only the moment of passing.
4. Branch from the original snapshot against the legal reference controller. Explain that rivals react independently to each branch and external disturbance keys are paired.
5. Inspect energy/gap trajectories, rules, assumptions and realised outcome. Show a case where waiting was better and a case where attacking was justified, only if actual evaluation supports those results.
6. Change one input or use an unseen scenario; recompute. Do not hard-code the successful response.
7. Inject stale telemetry and demonstrate withdrawal of advice. Restore and re-estimate before resuming.
8. Open the real benchmark report with the MPC-only ablation, uncertainty intervals and losing cases.

## Evidence needed before claims

"Improves race outcome" needs paired held-out results. "Real-time" needs hardware and latency percentiles plus end-to-end observation age. "Calibrated probability" needs reliability results with event/horizon definition. "Rule-aware" needs a coverage matrix with unsupported conditions. "Real F1 telemetry" needs source/channel provenance. "Driver integration" must be described as simulator integration unless independently approved onboard work exists.

## Current package

The HTML files are design mockups. They can demonstrate intended navigation/lifecycle but cannot serve as evidence for physics, RL or comparative performance. Their illustrative label must remain visible during design review. Replace fixture trajectories with measured simulator outputs only after integration gates pass.

## Suggested narrative

Lead with the racing decision, demonstrate the consequence, then explain the architecture. End with validation and limits. The differentiator is reviewable evidence, partial-observation honesty and retained-position evaluation, not the number of models or charts.
