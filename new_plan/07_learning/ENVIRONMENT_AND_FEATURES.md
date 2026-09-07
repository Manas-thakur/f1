# Environment, observation, action and reward contract

This is feature revision `energy-v1`. Any change to order, semantics, scaling or mask rules requires a new hash and model retraining/revalidation. A01 generates a machine-readable manifest from this specification before training.

## Observation: 96 values plus 96 masks

The actor receives float32 `concat(values[96], known_mask[96])`, shape `(192,)`. Use a flat Gymnasium Box; it is an engineered-history feed-forward policy, not recurrent SAC. All entries originate from StateEstimate and currently known context. Unknown values are zero **after** normalization and their mask is zero. A genuine known zero has mask one. No NaN or infinite values reach the network.

| Offsets | Contents in exact order |
|---|---|
| 0–23 | speed, acceleration, lap fraction, remaining race distance, own energy mean, own energy standard deviation, battery temperature, thermal headroom, recharge spent this lap, recharge allowance remaining, observed electrical power, current deployment ceiling, current recovery ceiling, own observation age, clock uncertainty, current instruction hold remaining, driver-delay mean, driver-delay standard deviation, estimated tyre/pace residual, completed laps, wet flag, yellow flag, overtake eligibility, eligibility-known flag |
| 24–63 | Eight lookahead samples, each ordered: distance ahead, curvature, grade, known deployment ceiling, estimated recovery capacity. Offsets are 100/250/500/750/1000/1500/2000/3000 metres, wrapping track geometry but not race completion. |
| 64–75 | Nearest relevant ahead rival: signed gap seconds, relative speed, energy belief mean, energy belief standard deviation, pace bias, pace uncertainty, conserve probability, normal probability, attack probability, defend probability, observation age, present flag |
| 76–87 | Nearest relevant behind rival: same twelve fields |
| 88–95 | Four-second gap trend, four-second own depletion rate, gap innovation magnitude, missed-execution count over eight seconds, last decoded budget, last decoded reserve target, time since last instruction change, instruction-change count over eight seconds |

Use positive signed gap for an ahead rival and negative for behind. Stable identity slots prevent switching between cars on tiny noise; record identity changes and reset that slot's historical summaries. No rival means present=0 with known present flag; all other slot masks are zero. Unknown rival energy can have a **known belief summary** with wide variance; provenance is estimated, not measured. A missing prior means masked summary. A flag's known state and its Boolean value are separate where required.

Lookahead ceiling is derived from currently known applicable context. Future unknown eligibility is masked, not predicted as guaranteed. Beyond the finish, mask lookahead entries. Observed recovery capacity is a model estimate; include its feature provenance in the manifest.

## Normalization and support

Use fixed documented physical scaling for progress/distance, speed, acceleration, time, energy, power and temperature; select scales from supported scenario bounds in G0. Store per-field offset, scale, clip limits and provenance. Fit any residual empirical scalers on training data only. Keep flags/probabilities in [0,1]. Clip normalized continuous values to [-5,5] for numerical protection and log pre-clip values and clip counts for out-of-distribution checks. Clipping does not make an unsupported state safe.

Unit conversions happen once in the encoder: domain uses SI; named feature scales may convert J to MJ and W to kW. Masks and units are tested with hand-built vectors. Actor and continuation model use exactly the same frozen encoder.

## Action: two continuous preferences

Gym action space is `Box(-1,1,shape=(2,))`. Decode `a[0]` into desired deployment energy over a fixed ten-second preference window; decode `a[1]` into energy target at the next declared tactical checkpoint. Formula: `lower + (a+1)/2*(upper-lower)`.

Budget lower bound is zero. Upper bound is a conservative reachable expenditure estimate from current energy, applicable limits and the ten-second window. Reserve lower/upper bounds come from the declared battery operating range and reachable checkpoint interval. Bounds are logged. If they collapse, return the fixed value; if invalid/unknown, disable learned preferences and use the validated baseline capability path.

These are **soft preferences**, not unconditional constraints or direct wheel torque. The planner penalises deviation with fixed configured weights, generates baseline candidates as well, and returns a physically/legal feasible plan. The same projection/planning path is in training and serving. Replay stores the original SAC action as the agent action; projected/actual actions are diagnostic fields. Replacing the replay action with a different executed control would train the critic on the wrong action semantics.

## Step and execution timing

Policy cadence is exactly 1 second in training and serving v1. Physics starts at 0.01-second steps with convergence checks. One policy step queues preferences, solves/reuses an eligible plan, advances simulated driver-delay/execution and integrates to the next policy tick. Safety invalidation may happen between ticks; it does not trigger an extra off-cadence policy call. The learned proposal is held until the next tick while baseline safety reacts immediately.

Planning horizon may use finer dynamics and extend beyond ten seconds. The budget preference window is fixed even as physical solver substeps vary. Driver pending commands, cooldown and actual execution are part of environment state. Inputs cannot instantly change torque just because the actor emitted a new vector.

## Reward revision objective-v1

Use an explicitly dimensionless utility. Initial commissioning coefficients below are engineering hypotheses; freeze or revise on training/tuning before final tests:

```text
base_reward = -elapsed_seconds / 1 second
              -0.1 * instruction_changes
terminal_finish = -30 * (finish_position - 1)
terminal_failure = -1200  # scenario-defined physical DNF/safety abort
shaping = gamma * Phi(next_state) - Phi(current_state)
Phi = -remaining_reference_time_seconds / 100
reward = base_reward + terminal_term + shaping
gamma = exp(-1 / 300) ≈ 0.996672
```

Reference remaining time comes from a fixed track pace model and observed progress, not future race truth. Set terminal potential to zero at true terminal states. With consistent discount/terminal treatment the shaping is potential-based; test telescoping numerically. Do not add repeatable positive rewards for each pass. Repeatedly passing and being repassed earns no bonus. Never reward unused finish energy. A truncated episode retains continuation value and does not zero its potential.

Position/time utility is a declared tradeoff, not physical seconds. Report actual position/time separately. The 300-second discount horizon is an initial delayed-consequence horizon, not a claim to optimise every minute of a full Grand Prix. Include longer-race sensitivity in evaluation. A meaningful terminal finish scenario must have sufficient rollout length; do not call every 60-second cutoff a finish.

The failure penalty must not reward early abandonment to avoid future negative time rewards. This initial value assumes at most 20 cars and at most one charged instruction change per second: the discounted running-cost bound is approximately 1.1/(1-gamma)=331 and the maximum finish-position cost is 570. A failure penalty of 1200 exceeds their sum. Reject scenario families outside these assumptions until the bound is recomputed, and test deliberate DNF against safe continuation.

Constraints are enforced outside reward learning. A rejected proposal is logged and the actual baseline response determines the transition. A physical invalidity abort is a genuine terminal failure with evidence. A software error, missing mandatory source or external resource stop is an invalid experiment, not a policy DNF or a profitable early terminal. Exclude it from learning transitions while retaining it in run failure accounting.

## Gym semantics and tests

`reset(seed,options)` initializes every RNG and returns observation/info. `step` returns observation,reward,terminated,truncated,info. Finish/DNF is terminated. External training time limit is truncated; preserve the terminal observation and bootstrap only where valid continuation exists. SB3 vector adapters must retain timeout metadata and final observations through automatic reset. A partial last physics interval at finish has its actual elapsed reward; no bootstrap follows a true finish.

Info may hold diagnostic IDs and reward components, but policy wrappers must never consume privileged truth. Run Gym/SB3 environment checkers, deterministic reset/branch tests, feature-mask tests, delayed execution tests, invalid action bounds, reward-loop tests, finish/truncation tests and feature truth-mutation tests before collecting training data.

[Gymnasium time-limit semantics](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/) distinguishes termination from truncation; this distinction is essential to correct bootstrapping.
