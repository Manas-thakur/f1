# RL training and reproducible evaluation

Train battery management against the same `RaceSession` used by the live WebSocket simulator. The learned agent selects battery deployment profiles for internal identity `car-01`. Automatic racecraft steers, passes, follows and brakes. A driver's display name is cosmetic. Broader physical variability expands the training scenarios, not the agent's action authority. See [RACE_PARAMETERS.md](RACE_PARAMETERS.md) for every current parameter family and [RACE_MODELS.md](RACE_MODELS.md) for research and model limitations.

## Start with a runnable smoke experiment

Run from the simulator checkout. Python and learning dependencies use uv. The renderer and live server are unnecessary for headless training.

```sh
uv sync --frozen --all-packages --group learning
uv run --group learning pytest tests/race/test_training.py
uv run --group learning python scripts/race.py train --circuit monza --cars 1 --duration 1 --preset training --seed 101 --workers 2 --rollout-steps 4 --batch-size 4 --steps 8 --output .afterlap/race/smoke.v1
uv run --group learning python scripts/race.py evaluate --circuit monza --cars 1 --duration 1 --preset training --policy .afterlap/race/smoke.v1.zip --eval-seeds 1001 1002 1003
uv run python scripts/race.py evaluate --circuit monza --cars 1 --duration 1 --preset training --profile automatic --eval-seeds 1001 1002 1003
```

The deliberately tiny run verifies collection, optimization, separate workers, auto-resets, save/load and held-out evaluation. One-second episodes should truncate and cannot teach race-winning strategy. Increase duration and field size for useful experiments. Existing archive/manifest output is refused; choose a unique experiment name. `smoke.v1`, `smoke.v1.zip` and `smoke.v1.manifest.json` resolve consistently, including names with dots.

## Collection controls and actual acceleration

| Option | Default | Meaning |
| --- | --- | --- |
| --steps | 10000 | Minimum total collected transitions across all workers; PPO completes a full rollout, so actual count may round upward |
| --workers | 1 | 1-64 independent environments; multiple workers use spawned subprocesses |
| --rollout-steps | 128 | Transitions per worker before an update; at least 2 |
| --batch-size | 64 | PPO minibatch; at least 2 and must divide workers times rollout steps |
| --seed | 42 | Training RNG and first worker episode seed; initial worker seeds are seed + rank |
| --settings | none | Complete validated scenario JSON, taking precedence over individual scenario flags |
| --eval-seeds | none | Explicit ordered episode seeds for evaluation; otherwise use the scenario seed |
| --profile | neutral | Fixed harvest/conserve/neutral/push/overtake baseline, or automatic BMS |
| --policy | none | Saved PPO archive for evaluation; takes precedence over --profile |
| --output | .afterlap/race/transitions.jsonl | Output stem; for training specify an explicit policy experiment name |

`make race-train WORKERS=4 ROLLOUT_STEPS=128 BATCH_SIZE=64 STEPS=10000 CARS=20` exposes the same collection controls. Training is CPU MLP PPO, gamma 0.996672, with one learner PyTorch thread to avoid oversubscription. Other PPO hyperparameters retain the installed Stable-Baselines3 defaults. The lockfile fixes the library version. More workers can improve sample throughput when CPU cores and memory are available, but startup, JIT compilation, process transfer and simultaneous browser work cost time. Measure after warmup and leave capacity for the live server. A 20-car episode is substantially more expensive than a one-car smoke test.

Each action lasts one simulated second, broken into the configured RK2 steps. Worker parallelism distributes separate episodes. It never enlarges dt, skips force evaluations, speeds the actor clock or interprets browser FPS as training throughput. Increasing rollout size changes optimization cadence as well as collection cost. Compare experiments using collected transitions, simulated episode coverage and held-out outcomes, not only wall time. [Stable-Baselines3 documents CPU PPO and subprocess collection](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html); its [vector-environment guide](https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html) explains automatic resets and terminal observations.

## Observation, action and reward contracts

The version is `race-bms-v1`, with 20 normalized values followed by 20 availability masks, float32 shape (40,). Each normalized value is clipped to [-5,5]. Unavailable values encode as zero with mask zero, so zero does not claim a measured physical zero.

| Feature positions | Channels | Divisors |
| --- | --- | --- |
| 0-7 | Own speed, acceleration, unwrapped progress, battery energy, battery temperature, recharge this lap, electrical power, lateral offset | 100 m/s, 50 m/s², 10000 m, 4 MJ, 350 K, 9 MJ, 350 kW, 6 m |
| 8-13 | Known-map curvature at observed progress + 0/100/250/500/1000/1500 m | 0.05 /m each |
| 14-16 | Nearest race-progress rival ahead: relative progress, relative speed, lateral offset | 100 m, 30 m/s, 6 m |
| 17-19 | Nearest race-progress rival behind: same three channels | Same divisors |
| 20-39 | Availability of corresponding feature 0-19 | 0 or 1 |

Features use delayed observations. Unknown energy remains masked. Hidden vehicle setups, personality, weather phases, future weather and rival battery truth are excluded. The automatic racecraft controller uses periodic physical gaps to account for lapped traffic, while the existing RL rival encoding selects ahead/behind in unwrapped race progress. Changing that distinction would change the actor semantics and requires versioning and retraining. Operator controls can inspect all cars' delayed own telemetry, but that UI payload is not the actor input.

| Action index | Profile | Deployment fraction | Harvest fraction |
| --- | --- | --- | --- |
| 0 | harvest | 0 | 1 |
| 1 | conserve | 0.20 | 0.85 |
| 2 | neutral | 0.50 | 0.65 |
| 3 | push | 0.80 | 0.40 |
| 4 | overtake | 1 | 0 |

These fractions request power, subject to available mechanical braking, battery limits, thermal derating and the drivetrain. The overtake label does not order a lane change or bypass physical limits. The automatic baseline selects harvest below its driver's reserve, exits harvest above reserve + 0.2 MJ, then chooses push during committed/alongside passing or conserve otherwise.

Reward is negative elapsed simulated seconds, minus 0.1 per changed requested profile. Finishing subtracts 30 times positions behind first. Contact or unsupported envelope failure subtracts 20000 and terminates. There is no repeated per-pass bonus. A time limit truncates and is not a finish; PPO retains the terminal observation for bootstrapping. Automatic evaluation has no requested-action switch penalty because it issues no BMS override. Software errors raise rather than becoming race outcomes. The reward version is `race-bms-reward-v1`.

## Seeds, variability and artifacts

A fresh UI race normally gets a new root seed; locking it allows exact replay. Headless `reset(seed=X)` reconstructs episode X. A subsequent implicit reset draws a new episode seed from a reproducible stream. Each worker starts at seed + rank, then advances independently; `episode_seed` in reset/step info identifies the actual scenario. Changing worker count changes rollout scheduling and training, so it is a distinct experiment. Replay the complete sequence of actions, settings and seed to reproduce an episode, not just the winning display name.

The training sidecar records model hash, environment/action/feature/reward contracts, full scenario recipe, nominal episode's resolved cars/traits/weather/sensors/initial states, rollout settings, worker seeds and collected transition count. Per-worker `*.monitor.csv` files in the adjacent `.episodes` directory record episode reward, length, wall timestamp and actual episode seed. The manifest's initial states describe the initial scenario seed, not every later worker episode. Reconstruct later episodes from their logged seed and identical settings/source. Keep the archive, sidecar, monitor files, lockfile, source revision and settings together. The model hash conservatively covers all core Python source, so even some nonphysical source edits require retraining.

Use `baseline` for controlled mechanism tests, `mild` for limited variation, `training` for broader synthetic diversity and `stress` for sensitivity. Source scales isolate driver, vehicle, starting grid, sensors, surface and wind. Explicit driver overrides support reproducible headway, clearance, reaction and braking sweeps. The grid uses its own seed stream and preset strength times `grid_scale`. For a vehicle-only ablation use `{"preset":"training","driver_scale":0,"grid_scale":0,"sensor_scale":0,"surface_scale":0,"wind_scale":0}` inside variability; retain matched episode seeds. Do not randomize mass, grip or speed independently at every step; persistent and smoothly varying mechanisms preserve physical causality.

## Development and evaluation loop

1. Verify the environment before optimizing learning: run physical invariant, racecraft, replay and training tests. Inspect `race_experiments.py` pass/abort traces and finite motion. Use one/two cars for quick debugging, then the intended full field. Short episodes reduce feedback time but cannot replace race-length acceptance.
2. Establish automatic, conserve and neutral baselines on a fixed scenario matrix. Record each result, including failures and truncations. `--eval-seeds` emits one JSON result per seed with controller, reward, terminal/truncation flags, finish position and failure.
3. Freeze training seeds, circuits, weather and trait ranges. Hold out entire circuits and scenario families. The CLI trains one scenario recipe per invocation with variable episode seeds; it does not automatically mix circuits or run a curriculum. Use separate named runs for recipe sweeps. Increase physical complexity only after the current stage passes its regression matrix.
4. Compare several training seeds against identical held-out evaluation seeds. Use at least 30 independent evaluation episodes per condition for substantive comparison, with multiple training runs. A few smoke seeds prove execution, not statistical superiority. Report bootstrap intervals over episodes and binomial uncertainty for contact/completion. Adjacent frames are correlated, not independent samples.
5. Evaluate fixed models on dry/wet transitions, wind, broad source scales, driver overrides, different field sizes and finer dt. Keep actual retained-pass events and energy constraints as separate diagnostics; the learned agent controls energy, not racing line logic. Use `race_benchmark.py` for measured simulator throughput and physical outcomes, and preserve its resolved manifest.
6. Inspect learning curves for failure avoidance, completion and policy behavior before claiming progress. Evaluate long enough to finish laps. Policies that only truncate successfully have not demonstrated racing success. Model selection/promotion is manual; training never installs a model into the live UI. `evaluate --policy` exercises the same physics headlessly, not a WebSocket policy-upload feature.

JSONL generation is for dataset inspection and offline research. PPO is on-policy and collects its own transitions; a generated file is not consumed as PPO training data. Extending actions to steering/throttle, adding tyre state, changing reward or exposing new sensors needs an explicitly versioned environment, fresh regression tests and newly trained policies. No synthetic training run certifies real-world accuracy without measured telemetry and calibrated distributions.
