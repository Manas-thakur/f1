# Optimisation formulation and evidence

## State and action

For scenario w, state x contains own progress/speed/energy/temperature, remaining regulatory ledgers, rival belief realisations and execution queue. u is a legal profile/budget segment. z is a discrete tactical intention selected by outer enumeration. Dynamics are `x[k+1,w] = f(x[k,w], u[k], w, dt[k])`. Near-term control is shared across scenarios so the planner cannot choose an action after seeing an unobserved future. Replanning supplies later feedback.

## Objective

Minimise `E_w[sum stage_cost + terminal_cost] + lambda_tail * CVaR_alpha(loss) + lambda_switch * switches`, subject to feasible physical/rule constraints. CVaR uses auxiliary eta and nonnegative xi[w]: `eta + sum p[w]*xi[w]/(1-alpha)` with `xi[w] >= loss[w]-eta`. Fix alpha and weights in objective manifest before held-out comparison. A utility loss combines normalised position/time terms; keep all components recorded and publish physical metrics separately.

Hard constraints include applicable electrical curves, battery operating range, correct-bus recharge ledger, thermal/torque envelope, ramp restrictions, track/corridor and action timing. A finite ensemble only checks sampled uncertainty; it is not universal robustness. Use conservative margins based on calibration and disclose the scenario model's coverage.

## Horizons

Detailed horizon ends after the likely counterattack or a specified checkpoint; coarser continuation covers subsequent laps. A learned ordinary-return terminal model supplies cost beyond the detailed horizon, conditioned on remaining laps, own energy and opponent belief. If outside its training support, disable that contribution and identify the validated baseline. Avoid a fixed arbitrary reserve that rewards unused energy at the true finish. At a truncated training/evaluation horizon, account for future energy value consistently.

## Probabilities

`pass_before(checkpoint)` and `ahead_at(checkpoint)` are different events. Calculate weighted scenario frequencies and retain the event definition, uncertainty method and calibration status. Report finite-sample uncertainty and model uncertainty separately. Geometric contact likelihood is only supported with appropriate lateral inputs. Do not manufacture a single risk score that hides missing geometry.

## Decision record

For each candidate store profile segments, sampled-scenario IDs, predicted speed/gap/energy bands, objective terms, constraint margins, continuation version, solver status and timing. Explain recommendations through computed differences and template reason codes such as `reserve_for_counterattack`, `insufficient_execution_lead`, `eligibility_unknown`, `energy_floor`, `small_expected_improvement`. Keep rejected alternatives to support the inspector and counterfactual experiments.

## Tests

Hand-computed one-segment energy allocation; symmetric opponents; dominance case where a plan uses more energy with no benefit; unavailable profile pruning; terminal-energy sensitivity; fixed-seed stability; model-disabled equivalence to baseline; solver success plus checker failure; recommendation chatter suppression and immediate invalidation precedence.


## Initial learned-value integration

Follow [continuation-value integration](../07_learning/VALUE_AND_CALIBRATION.md): acados generates smooth feasible candidates with analytic terminal terms; the ordinary-return ensemble reranks finalists outside the compiled solver. Do not double-count analytic and learned continuation. This is a bounded candidate approximation, not exact neural-terminal optimization.
