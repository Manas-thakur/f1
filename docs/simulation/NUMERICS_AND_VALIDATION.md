# Numerical implementation and fidelity

## Step ordering

At each step: process safety/line events at their true crossing time; update legal profiles; apply delayed driver action; calculate tyre/engine/electrical forces; integrate motion and battery; update thermal state; detect geometry; create observations with noise/delay; record completed checkpoints. Split the step when a regulatory boundary occurs inside it. Use deterministic tie ordering from the clock contract.

## Reference equations

`F_drag = 0.5 * rho * CdA * v_air^2`; `F_grade = m*g*sin(grade)`; `a = (F_drive-F_drag-F_roll-F_grade)/m`.

`P_battery_out = P_dc_deploy / eta_discharge`; `P_battery_in = eta_charge * P_dc_harvest`. Integrate each separately and cap by physical power/energy bounds before calculating actual torque. Electrical/gear efficiencies must not be double-applied. CU-K ledger integrates the quantity at its specified bus, not battery gain. Auxiliary loads consume battery energy and remain explicit.

`C_th * dT/dt = P_loss - h*(T-T_ambient)` is a reduced thermal model. It requires labelled parameter assumptions. Add more detailed thermal physics only after residuals/sensitivity show this model insufficient.

## Validation matrix

| Case | Expected invariant | Diagnostic |
|---|---|---|
| Coast with no drive | Kinetic energy decreases on level track | force/energy balance |
| Brake with regen disabled | Battery does not recharge | ledger trace |
| Deploy near lower energy bound | Actual power saturates before violating bound | saturation event |
| Harvest near upper bound | Excess recovery is rejected physically | brake blending trace |
| Constant radius | Lateral demand respects friction envelope | tyre utilisation |
| Timing line | Only lap-specific counters reset | before/after event record |
| Same snapshot and action stream | Matching state sequence | platform-specific tolerance |
| Double integration resolution | Stable energy/elapsed time/ordering | convergence report |
| Stochastic sensor noise | Repeatable with same keyed seed | observation hash |

Establish numerical tolerances empirically using the reference solver, then freeze them before benchmark evaluation. Record float precision, integrator, dt, hardware/compiler and model revision. Do not select a tolerance that hides a failing conservation test.

## Calibration

Fit identifiable parameters from training-only traces. Use held-out segments for speed/residual evaluation. Pace matching alone cannot identify engine power, drag and electrical power independently; keep plausible parameter ensembles when information is insufficient. Historical older-regulation traces calibrate generic road/pace shape only, not 2026 electrical allocation. Document track-map precision and whether lateral geometry is surveyed or synthetic.

## Independent evaluator

Use a higher-resolution integrator and perturbed held-out parameter sets for evaluation. Where feasible implement an independent energy ledger and line-crossing reference. Shared bugs can make controller and simulator appear consistent; compare with hand-calculated cases and a separate checker. A formal real-car fidelity claim requires real-car measurements unavailable in this package.
