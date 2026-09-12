# Race simulator

The race lab runs the existing deterministic physics engine with a seeded field of up to 20 cars. A separate Python process owns the race. Next.js and Bun provide `/race` and `/race/control`, and receive delayed simulated observations over WebSockets. The browser never advances physics.

## Start

From the repository root:

```sh
make install
make race
```

Open [the circuit view](http://127.0.0.1:18760/race) or [race control](http://127.0.0.1:18760/race/control). Press Start race. Ctrl+C stops the processes started by this command. The simulator is deliberately separate from the existing operational session runtime.

For containers, use `make race-up` and `make race-down`. These create the `afterlap-race` Compose project with loopback ports 18760 and 18761. The race lab does not require a database: episode data is streamed to files and live state stays in the simulation process. The existing `make up` stack remains available for the PostgreSQL-backed operational product. Race checkpoints are in memory and are lost when the simulator stops.

`make race-server` starts only the generator's WebSocket runtime. Its defaults accept the browser origin `http://127.0.0.1:18760` and local clients without an Origin header. The local lab has no user accounts or control leases. Commands from connected clients are serialized. It is not a multi-user remote deployment.

## Controls

Race control selects circuit, seed, car count, lap count, episode time limit, wetness, temperature, wind, and wake effects. Reset creates a paused episode; it discards the current in-memory race and checkpoint. Start, pause, and one-step advance operate on that same episode. Playback changes the requested wall-clock cadence without changing the integration step. Compute rate reports simulated seconds per computation second, not guaranteed real-time throughput.

Driver controls select a car, battery profile, pace preference, lateral target and low-drag mode. Manual pedals allow explicit throttle and brake requests. Automatic mode includes traffic-aware following and lane choice; manual overrides can cause collisions or unsupported corner entry. The model stops and reports those failures. BMS training changes only the battery profile while retaining the automatic driving policy.

Save checkpoint captures simulator state, random streams, pending driver commands, observation buffers, control overrides, automatic lane memory, finish classifications and episode counters. Restore returns to this state and pauses. Reset or restore changes the UI generation so old plotted history is discarded.

The telemetry download contains at most the most recent 200 frames observed by that browser. It is labelled as a bounded telemetry sample. Use the headless generator for complete learning transitions.

## Circuits and provenance

The 23 circuit layouts come from Crowdflow revision `c6b8c37c7d82fb48edb2d0f2ccc2fc0d07881791`. Each input retains its source URL, SHA-256, upstream geometry identity and the project's circuit-length record. Geometry attribution and licensing are in [configs/race-circuits/ATTRIBUTION.md](configs/race-circuits/ATTRIBUTION.md).

Crowdflow's outlines are SVG artwork normalized into a synthetic coordinate frame. The importer rescales each closed outline to its registry length, samples every approximately five metres, applies a short periodic smoothing kernel and derives curvature. This creates an executable synthetic scenario with a recognizable circuit shape. It does not create a surveyed circuit or verify its racing line, direction or timing location.

The corridor is an explicitly assumed constant 12 metres. Elevation is assumed flat. The first point is an assumed timing origin. These choices enable local footprint and finish tests but cannot establish real-world passing clearance. The existing telemetry-derived track pipeline and event-review workflow remain necessary for validated circuits and FIA event constraints.

## Physics

Internal units are metres, seconds, kilograms, joules, watts and kelvin. Display conversions happen at the frontend. Speed and acceleration are consequences of force integration, not independently randomized every frame. Seeded car differences include mass, drag area, downforce area, engine power map, low-speed tractive-force ceiling, initial speed, battery charge and driver reaction delay.

| Component | Model and limits |
| --- | --- |
| Motion | Float64 midpoint RK2, normally 0.01 s; numerical tests also exercise other step sizes |
| Engine and transmission | Speed-dependent power map, transmission efficiency and torque-limited low-speed force |
| Aerodynamics | Quadratic drag and downforce; synthetic low-drag mode scales drag area by 0.82 and downforce area by 0.75 |
| Tyres | Combined longitudinal/lateral friction envelope, curvature-dependent speed and backward braking preview |
| Brakes | Friction-force ceiling, available tyre force and regenerative blending |
| Battery | Actual deployed/recovered energy, conversion losses, auxiliary load, upper/lower energy saturation |
| Thermal response | Lumped heat capacity and heat rejection, temperature-based electrical derating |
| Weather | Constant scenario temperature and wind, ideal-gas air density, wetness-dependent grip |
| Traffic | Observation-driven following/lane choice, bounded wake drag/downforce changes, footprint contact detection |
| Outcomes | Shared finish-line crossing, time ordering, attempted/completed/retained passes, explicit unsupported-contact abort |

Battery power creates wheel force through the drivetrain. Harvesting requires mechanical braking energy; it is not a free recharge button. The low-drag tradeoff also enters the corner-speed preview. Wake-enabled preview uses a conservative downforce-loss bound rather than planning a corner with free-air grip. Braking preview respects the mechanical brake ceiling.

The battery and tyre coefficients are modelling assumptions, not measured cell chemistry or rubber characteristics. This is a reduced model: no CFD, suspension dynamics, detailed tyre temperature/wear, fuel burn, pit stops, gearbox shifts, crash damage, aquaplaning or event-certified active-aero zones. Lateral motion is a bounded line-tracking approximation rather than a full multibody vehicle. Speeds above 300 km/h are possible where the configured power, drag and geometry allow them; no track is forced to reach a target speed.

## Learning contract: race-bms-v1

This experimental environment is separate from the operational `energy-v1` SAC preference/planner interface. Its models cannot be loaded into that pipeline interchangeably.

`RaceEnv.reset(seed=...)` returns `(observation, info)`. `step(action)` returns `(next_observation, reward, terminated, truncated, info)`. One action is held for one simulated second, subdivided into physics steps. Automatic driver decisions update every 0.1 simulated seconds and include an execution delay.

The actor receives 40 float32 values: 20 normalized features followed by their 20 known masks. Values are clipped to [-5, 5]. Missing features encode zero with mask zero, keeping missing distinct from a measured zero. The first observation can be entirely masked because the sensor delay has not elapsed.

| Offsets | Features | Scales |
| --- | --- | --- |
| 0-7 | Own speed, acceleration, progress, battery energy, temperature, lap recharge, electrical power, lateral offset | 100 m/s, 50 m/s², 10 km, 4 MJ, 350 K, 9 MJ, 350 kW, 6 m |
| 8-13 | Curvature at 0, 100, 250, 500, 1000, 1500 m ahead | 0.05 inverse metres |
| 14-16 | Nearest ahead car's relative progress, relative speed, lateral offset | 100 m, 30 m/s, 6 m |
| 17-19 | Nearest behind car's same three channels | Same scales |
| 20-39 | Known masks in the same order | 0 or 1 |

Rival battery truth and future weather do not enter the actor's features or diagnostic info. The operator can inspect every car's own delayed simulated sensors, but those multi-car operator payloads are not the training observation.

The discrete action selects one of five deployment profiles. The generator writes the exact enum order into its manifest as `action_profiles`; use that order rather than guessing an index. For programmatic access, import `PROFILES` from `afterlap_core.race.environment`.

Reward is negative elapsed seconds, minus 0.1 for each requested profile change. On finishing, subtract 30 times positions lost from first. Physical contact or an unsupported lateral envelope incurs a 20,000-unit terminal penalty. This exceeds the bounded episode's possible running and position costs so deliberately crashing cannot avoid a larger cost. There is no repeatable per-pass bonus. A time limit is a truncation, never a race finish; PPO can bootstrap the final observation. Software errors raise and must not be relabelled as racing outcomes.

## Generate a dataset

```sh
make race-generate CIRCUIT=monza SEED=42 CARS=20 LAPS=3 DURATION=1800
```

The default output is `.afterlap/race/monza-42.jsonl`. Set `OUTPUT` to select another file. Existing output files are refused, preventing accidental replacement of an experiment. The first line contains settings, geometry and bundle hashes, vehicle configurations, integrator identity, provenance and action mapping. Each subsequent line contains the observation, requested action, reward, next observation, terminated/truncated flags and allowed diagnostic info. A seeded random policy provides exploration data; it is not a competitive baseline or an expert demonstration.

PPO is an on-policy method and collects its own transitions from `RaceEnv`. The generated JSONL is useful for inspection, replay checks and offline-learning research; simply loading it into PPO is not training. A separate offline RL algorithm would need an appropriate dataset loader, behaviour-policy treatment and validation.

## Train and evaluate

```sh
make race-train CIRCUIT=monza CARS=20 STEPS=10000
```

This installs the existing learning dependency group, checks the Gym contract, and trains Stable-Baselines3 PPO on CPU. It writes `.afterlap/race/policy-42.zip`. The learning group includes PyTorch; its platform package may also include GPU dependencies. For a small CPU-only environment, install PyTorch from its official CPU wheel index and run `python scripts/race.py train` in that prepared environment.

For a wiring smoke run, use one car, a short episode and 128 steps. This tests collection, optimization and checkpoint writing; it does not establish useful driving performance.

For a meaningful experiment:

1. Freeze a manifest with code revision, the emitted bundle hash, action/feature versions, reward, training steps and all seeds. Keep the source checkout with the run.
2. Train across circuit, weather, car and initial-state seeds. Keep whole circuits and scenario families out of the training set. Do not randomly split adjacent race frames.
3. Compare the learned profile policy against always-conserve, always-neutral and the automatic profile policy on identical held-out seeds. All policies must use the same observed features and automatic driving rules.
4. Record finish position, race time, battery constraint violations, contact/unsupported aborts, truncations and retained passes. Count incomplete and failed runs, not only wins. Bootstrap confidence intervals across independent episodes.
5. Repeat evaluation at a finer physics step and with perturbed car parameters. Check whether strategy rankings survive. Validate against measured telemetry before making real-car claims.
6. Keep model selection and promotion manual. This lab command does not modify the operational model registry or deploy a checkpoint.

References: [Gymnasium environment API](https://gymnasium.farama.org/api/env/), [time-limit semantics](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/), [Stable-Baselines3 PPO](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html), [WebSocket server API](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html).

## Verification

`make race-check` runs race and numerical tests, targeted Python lint/types, and frontend lint/types. `make race-browser-check` starts or reuses the local app and exercises its live controls in Chromium. `bun run build` checks the complete Next.js production build.

Tests cover all 23 imported layouts, 20-car setup, deterministic delayed-command restore, energy balance, masked observations, rival-energy isolation, finish versus timeout, contact abort, command validation and real WebSocket exchanges. A live browser test checks circuit changes, start/pause, stepping, checkpoint restore, driver commands, telemetry download and mobile overflow.

The default 20-car reference engine is CPU intensive. The UI reports its actual computation rate. A requested playback rate above available compute does not reduce physics accuracy or skip steps. Long RL runs should measure throughput before choosing episode counts; vectorized environments can distribute separate episodes across available CPU cores.
