# Energy deployment model engine

## What it is

The energy deployment engine is a real-time recommendation system for simulated 2026 Formula 1 battery use. Its job is narrow by design: every 0.5 simulated seconds it selects one of five deployment profiles for a car:

- `harvest`
- `conserve`
- `neutral`
- `push`
- `overtake`

It does not steer, brake, choose the racing line, handle collisions, or control pit strategy. Those systems remain automatic. This makes the output a recommendation that a driver, hardware button, or UI can accept or ignore.

The engine works in two modes:

1. `rules_baseline`: deterministic risk, reward, availability, and deployment logic that works without a trained model.
2. `ppo`: a Stable-Baselines3 Proximal Policy Optimization policy whose choice is always checked by the same safety and regulation guard.

The simulator is deterministic for a fixed configuration and seed. It is useful for repeatable training and evaluation, but its geometry, vehicle parameters, opponents, and opportunity labels are synthetic and uncalibrated. Results are simulator evidence, not proof of real-car performance.

## How it fits the problem

The engine turns delayed race telemetry into an immediate answer to four questions:

1. Is electrical boost currently safe and available?
2. Is there a modeled overtaking opportunity?
3. Which energy profile has the best expected race value?
4. What are the estimated reward, risk, and reward-to-risk ratio?

This supports the requested workflow:

```text
weather + car + battery + circuit + rivals + racing line
                         |
                         v
                 76-value observation
                         |
                         v
              rules baseline or PPO policy
                         |
                         v
             policy-independent safety guard
                         |
                         v
      recommendation + confidence + risk/reward
                         |
                         v
       Next.js /race/socket WebSocket endpoint
                  /                 \
                 v                   v
        dashboard Apply boost    hardware or CLI button
```

The current FIA integration enforces the published base 2026 electrical limits, including the 350 kW ERS-K maximum, 4 MJ usable energy-store window, and 8.5 MJ per-lap recharge ceiling. Event-specific Detection Gap, Detection Line, Activation Line, power sectors, and Overtake authorization are not public inputs in this repository. Therefore the engine reports synthetic opportunity detection but does not claim event-valid FIA Overtake activation. A PPO `overtake` result is reduced to ordinary `push` until official event data is supplied.

## What the model observes

`boost-decision-v1` receives 38 normalized features plus 38 availability masks, producing 76 `float32` inputs. A missing or delayed value is encoded as zero with a zero mask, so missing telemetry is different from a real zero measurement.

| Group | Inputs |
| --- | --- |
| Own car | speed, acceleration, battery energy, battery temperature, recharge this lap, electrical power, boost time, deployed energy, grip, lateral position |
| Race context | lap fraction, race fraction, wetness, ambient temperature, wind, track grip, track width, remaining time |
| Track preview | curvature at 0, 50, 100, 200, and 400 metres |
| Racing line | target lateral position at the same five distances |
| Rival ahead | relative progress, relative speed, gap, lateral position, speed |
| Rival behind | the same five rival values |

Only delayed observations enter the decision. Rival battery truth, future weather, and hidden simulator state are excluded.

## How a decision works

The rules assessment first checks valid telemetry, minimum launch speed, usable energy reserve, battery thermal limits, and heavy braking. It then estimates:

- straight score from upcoming curvature;
- opportunity from the nearest car ahead, gap, and closing speed;
- risk from cornering, wetness, proximity, temperature, and energy reserve;
- reward from gap, closing speed, straight quality, and available energy;
- reward-to-risk ratio as reward divided by risk when a reward exists.

Without a model, this assessment selects a reasonable baseline profile. With a model, PPO selects a profile and exposes its action probability as confidence. The guard then blocks an unsafe `push`, replaces unavailable `overtake` with `push`, and can force `conserve`. The WebSocket server repeats the current guard check when an Apply boost command arrives, preventing a stale recommendation from being blindly applied.

## How training works

The Gymnasium environment controls `car-01`. One action is held for 0.5 simulated seconds. The reward encourages forward progress, gained positions, completed passes, and a strong finish. It penalizes lost positions, battery energy use, risky boosting, unavailable boosting, frequent profile changes, and failed sessions.

Training uses CPU Stable-Baselines3 PPO. The default setup uses a multilayer perceptron, a discount factor of `0.996672`, ten optimizer epochs per cycle, and seeded simulation episodes. Live `/race` loops stay on one configuration and seed. Training resets draw a new episode seed from the environment RNG, and `train-decision` enables start-state diversity so `car-01` is not always pole with 3.1 MJ. The same seed still replays the same episode. Each requested training cycle is followed by evaluation on a held-out seed range. The best evaluation checkpoint is saved whenever mean reward improves.

Install dependencies and train a first policy:

```sh
make install
make race-train-decision \
  CIRCUIT=monza \
  DECISION_CARS=6 \
  DECISION_DURATION=60 \
  STEPS=10000 \
  CYCLES=5 \
  EVAL_EPISODES=3 \
  TRAINING_OUTPUT=.afterlap/race/boost-policy
```

Useful variation is controlled through the same race CLI. For example:

```sh
uv run --group learning python scripts/race.py train-decision \
  --circuit silverstone \
  --seed 42 \
  --cars 6 \
  --duration 120 \
  --weather rainy \
  --wetness 0.7 \
  --wind-mps 8 \
  --preset training \
  --steps 50000 \
  --cycles 10 \
  --eval-episodes 10 \
  --output .afterlap/race/boost-policy
```

Training produces:

| Artifact | Meaning |
| --- | --- |
| `boost-policy.zip` | final PPO policy |
| `boost-policy.best.zip` | best evaluation-cycle checkpoint |
| `boost-policy.manifest.json` | feature, action, reward, simulator, and regulation compatibility contract |
| `boost-policy.metrics.json` | baseline and per-cycle evaluation results |

The manifest prevents a policy from loading when its observation, action, environment, or reward contract does not match the runtime.

## Evaluation and improvement loop

Run a larger held-out evaluation before loading a policy:

```sh
make race-evaluate-decision \
  CIRCUIT=monza \
  DECISION_CARS=6 \
  DECISION_DURATION=60 \
  EVAL_EPISODES=20 \
  POLICY=.afterlap/race/boost-policy
```

The evaluator reports mean reward, reward spread, finish position, deployed energy, passes, opportunity recall, boost action rate, and failure rate. Each training cycle also records cumulative timesteps, optimizer epochs, improvement over the rules baseline, and whether it became the best cycle.

A model is only marked as a promotion candidate when its best mean reward beats the seeded baseline and its evaluation failure rate is zero. Promotion is never automatic. A practical improvement loop is:

1. Train across several circuits, weather states, car counts, and independent seeds.
2. Hold out whole circuits and scenario families instead of splitting adjacent frames.
3. Compare PPO and the rules baseline on identical seeds.
4. Reject regressions in failures, finish position, opportunity recall, or energy use even if reward rises.
5. Repeat evaluation with finer physics steps and perturbed car parameters.
6. Review the best checkpoint and metrics manually before loading it.
7. Add measured telemetry calibration before making real-world performance claims.

## How the runtime and scripts integrate

Start the full stack with the trained policy and metrics:

```sh
make race \
  POLICY=.afterlap/race/boost-policy \
  METRICS=.afterlap/race/boost-policy.metrics.json
```

The startup path is:

1. `Makefile` passes the policy and metrics as `RACE_POLICY` and `RACE_METRICS`.
2. `scripts/race_stack.py` starts the Python race server and the Next.js app.
3. `scripts/race.py serve` loads `BoostDecisionEngine` and validates the policy manifest.
4. The race server advances physics, builds delayed observations, calculates a recommendation for every car, and publishes frames.
5. Next.js proxies `/race/socket` to the Python WebSocket server. The browser and external controls use only the Next.js address.
6. The dashboard worker receives frames and displays the recommended mode, availability, confidence, target, gap, risk, reward, ratio, training graph, and evaluation metrics.
7. Apply boost sends `{ operation: "boost", car_id }`. The server checks the latest guarded recommendation and returns an acknowledgement or error with the command ID.
8. Return to automatic sends the same operation with `enabled: false` and removes the manual battery profile.

The CLI follows exactly the same route as the browser and is the reference for a physical button integration:

```sh
make race-status
make race-boost
make race-boost-off
uv run python scripts/race_control.py boost \
  --car car-02 \
  --url ws://127.0.0.1:18760/race/socket
```

A hardware process can copy this small protocol: connect to `/race/socket`, wait for a frame, read `recommendations[car_id]`, enable its button only when `can_apply` is true, send a unique command ID on press, and treat only the matching `ack` as successful activation.

## Important files

| File | Responsibility |
| --- | --- |
| `packages/core/afterlap_core/race/decision.py` | observation encoder, rules baseline, risk/reward calculation, Gym environment, manifest validation, PPO inference |
| `packages/core/afterlap_core/race/training.py` | PPO cycles, baseline comparison, evaluation metrics, best checkpoint, promotion candidate |
| `apps/api/afterlap_api/race_server.py` | live inference, guarded boost command, WebSocket frames |
| `scripts/race.py` | train, evaluate, serve, schema, and simulator CLI |
| `scripts/race_stack.py` | Python and Next.js process launcher |
| `scripts/race_control.py` | hardware-oriented WebSocket command example |
| `apps/web/src/features/race/Decision.tsx` | recommendation panel, controls, metrics, and training graph |
| `docs/FIA_2026_RULE_COVERAGE.md` | exact regulation coverage and known gaps |
| `RACE_SIMULATOR.md` | full simulator, physics, environment, and verification reference |

Inspect the machine-readable model contract at any time:

```sh
uv run python scripts/race.py schema
```

