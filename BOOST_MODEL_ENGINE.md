# Boost model engine

## What this system is

The race simulator is a hybrid control system. It combines deterministic physics, seeded automatic racecraft, optional reinforcement-learning experiments, and a manual boost override.

The live boost button asks the decision engine for the current guarded recommendation, then applies that recommendation to one selected car. The engine uses its rules baseline by default and a PPO policy when one is supplied at startup. Every other car continues using the existing automatic racecraft and storyline logic.

| Part | Responsibility |
| --- | --- |
| `RaceSession` | Owns the race, cars, automatic decisions, manual overrides, checkpoints, and simulated time |
| `Racecraft` | Uses delayed observations to choose pace, passing behavior, lane targets, and battery profiles |
| `StorylineDirector` | Adds deterministic seeded events such as attack, push, surge, and coast |
| Simulation engine | Applies command delay, drivetrain power, battery limits, thermal limits, grip, weather, and motion |
| `BoostDecisionEngine` | Produces a per-car profile recommendation from delayed telemetry, with policy-independent availability guards |
| `BoostDecisionEnv` | Trains the energy-only `boost-decision-v1` PPO policy |
| `RaceEnv` | Wraps one controlled car and its opponents in a Gymnasium environment for PPO training |
| Race server | Streams observed frames over WebSocket and accepts control commands |
| SQLite control state | Persists the current car selected by either operator view |
| Next.js app | Displays `/race` and `/tel/{car_id}`, updates selection, and forwards carless boost POST requests |

This is a reduced synthetic simulator. It is useful for software integration, control experiments, repeatable scenarios, and operator-interface development. It is not calibrated against a real Formula 1 vehicle and must not be treated as a validated real-car controller.

## How it fits the selected-car problem

The required operating rule is:

1. The operator watches a car on `/race`, or chooses a car from the dropdown on `/tel/{car_id}`.
2. The browser stores that current car through the server in `.afterlap/race/control.sqlite3`.
3. The Boost button or hardware sends an HTTP POST with no car identity.
4. The server reads the current car from SQLite, evaluates its latest recommendation, and rejects the command if boost is unavailable.
5. After a successful guard check, the server clears the previous manual battery-profile override and assigns the recommended profile to the newly selected car.
6. All other cars remain outside the manual override map, so their existing automatic and seeded storyline decisions continue normally.
7. Selecting and boosting another car transfers manual boost authority to that car. The former car returns to automatic battery-profile decisions.

The number of cars is dynamic. The UI builds its dropdown from the cars in the current race frame, and the server validates that the requested car exists in the active session.

## End-to-end request flow

```text
hardware input or Boost button
  -> POST {dashboard host}/race/boost
  -> Next.js route handler
  -> POST {race runtime}/boost
  -> read selected_car_id from SQLite
  -> RaceServer boost command
  -> BoostDecisionEngine recommendation and safety guard
  -> RaceSession.bms_profiles contains only the selected car
  -> automatic_action replaces that car's requested battery profile with the recommendation
  -> simulator command delay and physics
  -> delayed observed telemetry over /race/socket
  -> /race and /tel/{car_id} display the result
```

The dashboard host is intentionally dynamic. The browser uses a same-origin URL, and hardware can set `HOST` at runtime:

```sh
HOST="${HOST:-http://127.0.0.1:18760}"
curl --fail-with-body --request POST "${HOST%/}/race/boost"
```

A successful request returns:

```json
{"operation":"boost","car_id":"car-01","status":"accepted"}
```

`accepted` means the current recommendation passed its guards and the override reached the race session. Visible electrical deployment still follows command delay and physical constraints. A depleted or thermally limited battery cannot create unavailable power, and pit phases retain their pit-specific profiles.

The local stack has no authentication or control lease. Put authentication, TLS, authorization, rate limiting, and an operator lease in front of this endpoint before connecting real remote hardware.

## Start the working system

Install the pinned dependencies once:

```sh
make install
```

Start the simulator and dashboard:

```sh
make race
```

Open:

- `http://127.0.0.1:18760/race` for the full race view
- `http://127.0.0.1:18760/tel/car-01` for the telemetry display

On `/race`, the viewed car changes through classification, scene selection, or the car navigation controls. On `/tel/{car_id}`, use the car dropdown. Each change updates the shared SQLite selection before a subsequent boost request is sent. Start the race, then press Boost. The button is disabled while disconnected, paused, missing the selected car, already observing active boost, or blocked by the current recommendation guard.

## What can be trained

There are two separate PPO environments.

### Energy deployment decision model

`BoostDecisionEnv` is the model relevant to the Boost button. It controls only the battery deployment profile for `car-01` during training. Steering, braking, racing line, collision handling, and pit behavior stay automatic.

Its 76-value observation contains 38 normalized values followed by 38 availability masks. The values cover own battery and motion telemetry, race and weather context, curvature and racing-line lookaheads, and the nearest cars ahead and behind. Missing telemetry remains different from a measured zero.

Its discrete action chooses one of five profiles: `harvest`, `conserve`, `neutral`, `push`, or `overtake`. A decision is held for 0.5 simulated seconds. Reward favors progress, gained positions, and completed passes, while charging for energy use, unsafe boost requests, risk, lost positions, and action churn.

The safety and availability guard is independent of PPO. It blocks boost for missing telemetry, low energy, high temperature, braking, launch conditions, and other unavailable states. Public event-specific Overtake authorization is unavailable, so an unsafe or unsupported output is downgraded.

### Full race controller model

`RaceEnv` is a broader experiment. It exposes 40 values and eight continuous actions covering driver authority, battery profile, pace, lateral target, low drag, and pedals. It controls `car-01`; the remaining cars stay automatic. This policy is evaluated offline and is not the policy used by the live Boost button.

## Train the boost decision model

Install the learning dependencies:

```sh
uv sync --frozen --all-packages --group learning
```

Run a short wiring check:

```sh
make race-train-decision \
  CIRCUIT=monza \
  DECISION_CARS=2 \
  DECISION_DURATION=8 \
  STEPS=128 \
  CYCLES=1 \
  EVAL_EPISODES=1
```

This proves that the Gym contract, PPO collection, cycle evaluation, and policy saving work. It does not produce a useful policy.

Run a larger experiment with opponents and repeated evaluation:

```sh
make race-train-decision \
  CIRCUIT=monza \
  DECISION_CARS=6 \
  DECISION_DURATION=60 \
  STEPS=100000 \
  CYCLES=5 \
  EVAL_EPISODES=10 \
  TRAINING_OUTPUT=.afterlap/race/boost-policy
```

The output is:

- `boost-policy.zip`, containing the final PPO policy
- `boost-policy.best.zip`, containing the best evaluation-cycle checkpoint
- `boost-policy.manifest.json`, containing the model and environment contract
- `boost-policy.metrics.json`, containing the rules baseline, cycle history, failure rate, and manual promotion status

Each cycle trains on a stream of episode seeds, evaluates on deterministic held-out seeds, compares against the rules baseline, and records whether mean reward improved. `train-decision` and `evaluate-decision` turn on start-state diversity by default: grid order, pack origin, battery energy, launch speed, and weather are sampled from the episode seed. Live `serve` stays on the fixed grid and 3.1 MJ start charge. Promotion is never automatic. Use multiple seeds, circuits, weather conditions, and variability presets for serious experiments. Keep complete scenario families out of training for evaluation, and report incomplete or failed runs. Pass `--no-diversity` to restore the fixed start loop.

## Evaluate and run it

Evaluate the saved boost policy:

```sh
make race-evaluate-decision \
  CIRCUIT=monza \
  DECISION_CARS=6 \
  DECISION_DURATION=60 \
  EVAL_EPISODES=20 \
  POLICY=.afterlap/race/boost-policy
```

The loader verifies the environment version, observation fields and size, action profiles, and reward contract. An incompatible policy is rejected.

Load the policy and its metrics into the live dashboard:

```sh
make race \
  POLICY=.afterlap/race/boost-policy \
  METRICS=.afterlap/race/boost-policy.metrics.json
```

Without `POLICY`, the live engine uses the rules baseline. With `POLICY`, recommendations report `source: ppo`, include confidence, and still pass through the same rules-based safety guard before the button or POST can apply them.

Train the separate full race controller only when experimenting with its broader action space:

```sh
make race-train CIRCUIT=monza CARS=20 LAPS=5 DURATION=1800 STEPS=100000
```

## Generate data

Generate JSONL transitions for inspection or offline-learning research:

```sh
make race-generate CIRCUIT=monza SEED=42 CARS=20 LAPS=5 DURATION=1800
```

The first line is a manifest. Later lines contain observation, action, reward, next observation, termination flags, and bounded diagnostic information. PPO is on-policy and collects its own rollouts, so this JSONL file is not consumed by the current PPO training command.

## How the scripts integrate

`scripts/race.py` is the main command entry point:

- `serve` creates `RaceSession`, loads the optional boost policy and metrics, and starts the live server
- `train-decision` trains the energy-only policy in cycles and writes policy, manifest, and metrics artifacts
- `evaluate-decision` compares a saved energy policy across seeded episodes
- `generate` samples actions and writes transition data
- `train` trains the separate full-controller PPO policy
- `evaluate` runs either a full-controller policy or a fixed control until finish or truncation
- `catalogue` prints circuit definitions
- `schema` prints the race, driver, and learning contracts

`scripts/race_control.py` is the hardware-oriented WebSocket client. It can read recommendation status, apply guarded boost, disable a boost override, and send transport commands. The new HTTP POST is a simpler same-origin integration for hardware that does not need a persistent WebSocket client.

`scripts/race_stack.py` starts two local processes:

- the Python race runtime, normally on port `18761`
- the Next.js dashboard, normally on port `18760`

The browser receives telemetry through `/race/socket`. Selection changes go through `/race/selection/{car_id}`, while boost goes through `/race/boost` without a car identifier. Keeping the browser paths on the dashboard origin makes forwarded ports and changing hosts work without frontend configuration.

## Important current boundary

The live server loads the boost-decision policy only to recommend a battery profile. It does not transfer steering, braking, racing-line, pit, or collision authority to the policy. Recommendations are calculated independently for every car, but a manual button or POST applies an override only to the selected car. Unselected cars continue using automatic racecraft and seeded storyline behavior.

The separate full-controller `RaceEnv` policy remains an offline experimental path. Using that policy in the live multi-car dashboard would require a per-car runner, inference cadence, failure fallback, and an explicit authority model. That is intentionally outside the manual boost integration.

## Verification commands

```sh
make race-check
bun run build
make race-browser-check
```

These cover Python tests, formatting, lint, types, the no-comment policy, frontend checks, the production build, live race behavior, the POST request, selected-car targeting, dropdown changes, telemetry rendering, and battery drain under boost.
