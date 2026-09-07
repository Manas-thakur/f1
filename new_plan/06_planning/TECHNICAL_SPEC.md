# Predictive energy and battle planning

## Deliverable

Implement `packages/core/planning/` with `plan(estimate, rule_context, model_bundle, deadline) -> PlanningResult`. Result is accepted candidates and reasons, or a typed unavailable/timeout. The planner never writes operator lifecycle events or directly actuates a real car.

## Decomposition

Tactical enumerator creates a bounded set of intentions: maintain, prepare attack, attack, defend and recover. Legal profile availability prunes candidates before optimisation. For each surviving intention, solve a continuous segment-energy schedule over the next battle and counterattack using sampled opponent scenarios. A coarser continuation/value model values the remaining horizon. Candidate generation may use a frozen SAC proposal to warm-start budgets; baseline candidates remain available.

Represent control as feasible driver-selectable profile segments with continuous allocation preferences. Do not emit an arbitrary millisecond power trace as if a human could execute it. Driver execution delay and instruction duration are inside the transition model. Use current plan as warm start; execute only the next instruction and replan from observed outcomes.

## Optimisation and checking

CasADi defines smooth continuous dynamics and derivatives; acados solves fixed discrete-profile subproblems. Do not feed discontinuous contact/pass events directly into a smooth solver and expect validity. Tactical geometry supplies feasible corridors and post-rollout outcome checks. Independently recheck each candidate with the rules module and refined boundary integration. A mathematically converged solver can still return a plan rejected by this check.

Rank legal candidates by declared expected race utility plus poor-tail loss and instruction-switch cost. Show position/time/energy/probability as distinct outputs; never relabel a weighted objective as seconds. Use an improvement threshold and minimum dwell to suppress chatter, but invalidate immediately for safety/rule/expiry changes.

## Runtime algorithm

1. Verify required inputs, freshness, rule coverage and execution time window.
2. Build weighted opponent scenarios from the belief state.
3. Add baseline and learned budget proposals; enumerate feasible intentions.
4. Optimise within the fixed deadline with bounded candidate/scenario count.
5. Re-simulate and check candidate trajectories; reject unknown critical constraints.
6. Compare expected benefit, downside, future energy and current-plan hysteresis.
7. Produce an immutable evidence record and structured recommendation fields.

## Failure handling and tests

On deadline expiry use only a revalidated current/baseline plan; otherwise withdraw tactical advice. Test missing battery state, unavailable Overtake, impossibly short instruction lead time, depleted energy, thermal derating, counterattack, unobserved rival reserve and pack change. A greedy pass that loses the position afterward should be valued through its complete defined horizon, not credited as permanent progress.

Planner latency target is initially p95 <=200 ms on declared hardware; measure candidate counts and scenario resolution. Lower resolution cannot be hidden as the same confidence level. See [mathematical specification](OPTIMIZATION.md).
