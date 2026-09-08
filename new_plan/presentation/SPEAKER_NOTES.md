# Speaker notes

## 1. AFTERLAP

The decision is not simply whether to press an overtake button. Electrical deployment changes what remains for the next straight, while track shape, weather, grip, traffic and eligibility change the value of each joule. AFTERLAP turns that sequence into an engineer decision with a visible plan and evidence.

## 2. The engineering question

An immediate pass can be a bad decision if it empties the useful energy window and exposes the car to a counterattack. We optimize the complete battle: approach, pass attempt and retained position at a later checkpoint.

## 3. 2026 circuit scope

The current official schedule snapshot contains 23 physical circuits. Calendar identity and track identity differ: the Bahrain Grand Prix currently uses Sepang, and Madring changed from its provisional announcement design. The system pins track and event packages separately so revisions remain auditable.

## 4. Circuit diversity changes energy value

The chart uses official nominal lengths for six contrasting circuits. Length alone does not decide strategy. Monza combines long full-throttle running and heavy stops; Monaco restricts passing space; Spa adds elevation and weather; Mexico adds altitude. These become geometry and condition variables rather than hardcoded track labels.

## 5. A simulation-grade track package

A circuit image is insufficient. We compile metric centreline, elevation, curvature and a validated corridor. The event overlay adds FIA detection and activation lines, straight-mode areas and power-unit parameters. Every source and review is hashed.

## 6. Real observations, clear limits

Public data gives location, speed, gaps, stints, flags and weather. It does not provide true rival battery charge or an authorised team energy state. We use public data to anchor context and distributions, while energy truth remains synthetic or authorised and explicitly labelled.

## 7. Factors that alter the decision

The causal diagram shows why these inputs cannot be reduced to independent sliders. Weather changes density and grip; grip changes braking and recovery; traffic changes drag and downforce; rules change feasibility. Correlated scenario sampling preserves these relationships.

## 8. Deployment and regeneration

Electrical power is constrained by speed-dependent event rules and the absolute technical ceiling. Regeneration also depends on braking work, tyre grip, motor limits, battery acceptance and the lap ledger. The model accounts for the correct energy bus and prevents double counting.

## 9. The learning problem

At one-second intervals SAC observes a masked estimate and proposes two preferences: energy budget over the next ten seconds and reserve at the next checkpoint. It never controls steering or torque directly. The same constrained planner converts preferences into feasible trajectories during training and runtime.

## 10. Factors do not have one universal weight

We distinguish physics parameters, explicit reward coefficients and learned feature influence. Hard rules do not become penalties. We explain influence through paired interventions, ablation and global sensitivity analysis, always tied to a track and operating state.

## 11. Hybrid decision architecture

Estimation creates beliefs from incomplete observations. SAC contributes long-horizon preferences. MPC evaluates physical candidates. A separate rules checker can reject every learned suggestion. The engineer selects a recommendation, and observed execution closes the loop.

## 12. Training across circuits

The curriculum begins with deterministic energy primitives before complete real circuits and reactive traffic. Entire circuits and combined weather conditions remain held out. The policy sees geometry, not a track-name shortcut.

## 13. Evidence before promotion

We compare legal fixed, greedy, MPC-only, actor-only, value-only and full controllers from paired snapshots. Promotion needs predeclared benefit and downside limits, zero modeled violations in scope, calibrated uncertainty and acceptable latency. Failure keeps the proven baseline active.

## 14. Three operational views

The lab defines and branches a scenario. The engineer console presents the action, assumptions, rule margins and later consequence. The driver display shows one short simulator instruction with an expiry. Selection, communication and execution remain separate events.

## 15. Why this is different

The product joins four things that are often shown separately: real event packages, reactive counterfactual simulation, constrained learning and evidence-linked human operation. The differentiator is the auditable decision chain. The final demo should show the same snapshot producing two physically different futures, not two authored chart lines.
