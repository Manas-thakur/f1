# Race simulator

All simulator code is maintained on the `simulator` branch, independently of `main`. Develop in feature branches and open pull requests targeting `simulator`. CI runs on each push and includes the live race and forwarded connection browser checks.

The race lab runs a deterministic physics engine with a seeded field of up to 20 cars. A separate Python process owns the race. Next.js and Bun provide the single `/race` view, and receive delayed simulated observations over WebSockets. The browser never advances physics.

## Start

From the repository root:

```sh
make install
make race
```

Open [the race view](http://127.0.0.1:18760/race). The hamburger opens docked settings; Float allows dragging and resizing them. `/race/control` redirects to `/race`. Press Start race. Ctrl+C stops the processes started by this command.

Use either native `make race` or Docker, since they share ports. If switching from Docker to native, run `make race-down` first. The native launcher checks both ports before starting either service and reports conflicts without stopping existing processes.

For containers, use `make race-up` and `make race-down`. These create the `afterlap-race` Compose project with loopback ports 18760 and 18761. The race lab does not require a database: episode data is streamed to files and live state stays in the simulation process. Race checkpoints are in memory and are lost when the simulator stops.

`make race-server` starts only the generator's WebSocket runtime. Its defaults accept HTTP and HTTPS browser origins on localhost, 127.0.0.1 and IPv6 loopback at any port, plus local clients without an Origin header. Other browser origins require the explicit `--origin` option. The browser connects to `/race/socket` on the same host and port as the page, using `wss` for HTTPS. Next.js proxies the connection to the simulator, so only the dashboard port needs forwarding. The server-side `AFTERLAP_RACE_UPSTREAM` setting selects the simulator URL during development or production build; Docker builds use `http://simulator:18761`. The local lab has no user accounts or control leases. Commands from connected clients are serialized. It is not a multi-user remote deployment.

## Controls

Race control selects circuit, seed, car count, lap count, episode time limit, visual weather, wetness, temperature, wind, wake effects, contact handling, seeded racing-line behavior, storylines, pit stops, and tyre wear. Weather, wetness, temperature, and wind apply immediately to the active race without changing its generation, running state, elapsed time, positions, or checkpoint. Drivers always evaluate vehicle footprints, preserve clearance, and refuse an overtake through occupied space. Contact handling selects whether an unexpected overlap stops the session, not whether collision avoidance is active. Every circuit offers its sourced 2026 Grand Prix lap count as the default and a custom option from 1 through 80 laps. Changing the circuit updates the preset before reset. The circuit view shows the leader’s current lap, each car’s lap in classification, and selected-car lap progress. Lap numbering starts at one and stops at the configured total when a car finishes; progress uses delayed position telemetry. Reset creates a paused episode; it discards the current in-memory race and checkpoint. Start, pause, and one-step advance operate on that same episode. Playback changes the requested wall-clock cadence without changing the integration step. PACE reports observed simulated seconds per wall-clock second; TARGET is the requested playback multiplier. FPS measures rendering separately.

Driver controls select a car, battery profile, pace preference, lateral target and low-drag mode. Manual pedals allow explicit throttle and brake requests. Automatic mode uses persistent observation-driven pass intention, per-car corner lines and bounded acceleration/lateral requests. Contact is ignored by default and can be switched to episode termination. The same controls are available to scripts and policies through `DriverControl` and the normalized `RaceEnv` action.

Animation uses a shared simulation-time playback cursor with a short telemetry buffer, rather than restarting movement on each packet. Observed speed smooths small position-noise corrections; monotone interpolation avoids backwards motion and overshoot between forward-moving samples. All cars and following cameras use that same cursor, and stalled connections hold at the newest available sample. These display estimates do not change physics, classification, exported telemetry or learning observations. The car meshes fit the assumed two-metre physical width.

Save checkpoint captures simulator state, random streams, pending driver commands, observation buffers, control overrides, driver traits, interaction state, scheduled decision time, finish classifications and episode counters. Restore returns to this state and pauses. Reset or restore changes the UI generation so old plotted history is discarded.

The telemetry download contains at most the most recent 200 frames observed by that browser. It is labelled as a bounded telemetry sample. Use the headless generator for complete learning transitions.

## Circuits and provenance

The 23 circuit layouts come from Crowdflow revision `c6b8c37c7d82fb48edb2d0f2ccc2fc0d07881791`. Each input retains its source URL, SHA-256, upstream geometry identity and the project's circuit-length record. Geometry attribution and licensing are in [configs/race-circuits/ATTRIBUTION.md](configs/race-circuits/ATTRIBUTION.md).

Crowdflow's outlines are SVG artwork normalized into a synthetic coordinate frame. The importer rescales each closed outline to its registry length, samples every approximately five metres, applies a short periodic smoothing kernel and derives curvature. This creates an executable synthetic scenario with a recognizable circuit shape. It does not create a surveyed circuit or verify its racing line, direction or timing location.

The corridor is an explicitly assumed constant 12 metres. Elevation is assumed flat. The first point is an assumed timing origin. These choices enable local footprint and finish tests but cannot establish real-world passing clearance. Surveyed geometry and separately validated event constraints are required before making real-circuit accuracy claims.

## Trackside branding

The run-off strip either side of the racing surface carries painted sponsor decals. Each decal is cut from the same cubic spline the racing surface uses, sampled at equal arc length along the strip centreline, so a logo bends and stretches with the corner it occupies instead of floating over it as a flat quad. Decals sit 3.7 metres across the 4-metre run-off, up to 30 metres long, and are oriented with the artwork's top edge facing the circuit, the reading direction real painted trackside advertising uses.

Where a corner is tighter than the strip offset the swept quad would fold back on itself. The builder measures each sub-quad's inner and outer edge and drops the whole decal when an edge collapses, reverses or stretches past roughly twice its opposite, so no circuit shows a folded logo. Decals for one slot merge into a single mesh, giving one draw call per sponsor.

Slots are declared in `apps/web/src/features/race/sponsors.ts` and read artwork from [apps/web/public/race-assets/branding](apps/web/public/race-assets/branding). A slot with no file, or an unreadable one, falls back to a wordmark drawn from its label. This repository ships no artwork; files placed there are supplied by the operator.

Branding is decoration on the rendered scene. It carries no simulator state, is not observed by any controller, and does not affect physics, classification or exported telemetry.

## Physics

Internal units are metres, seconds, kilograms, joules, watts and kelvin. Display conversions happen at the frontend. Speed and acceleration are consequences of force integration, not independently randomized every frame. Seeded car differences include mass, correlated drag/downforce setup, engine power map, low-speed tractive-force ceiling, initial speed and battery charge. Persistent driver traits use independent named streams. The baseline, mild, training and stress presets control variation, with explicit synthetic provenance.

| Component | Model and limits |
| --- | --- |
| Motion | Float64 midpoint RK2, normally 0.01 s; numerical tests also exercise other step sizes |
| Engine and transmission | Speed-dependent power map, transmission efficiency and torque-limited low-speed force |
| Aerodynamics | Quadratic drag and downforce; synthetic low-drag mode scales drag area by 0.82 and downforce area by 0.75 |
| Tyres | Combined force envelope, curvature preview, seeded compounds, distance/utilization wear, grip loss, and automatic changes |
| Brakes | Friction-force ceiling, available tyre force and regenerative blending |
| Battery | Actual deployed/recovered energy, conversion losses, auxiliary load, upper/lower energy saturation |
| Thermal response | Lumped heat capacity and heat rejection, temperature-based electrical derating |
| Weather | Constant ambient temperature, ideal-gas density, evolving synthetic wetting/drying, periodic surface patches and smooth correlated wind |
| Traffic | Observation-driven following, seeded periodic corner lines, corner passing, and bounded wake effects based on physical periodic proximity |
| Outcomes | Shared finish-line crossing, time ordering, passing, pit service, dry-compound and 90% classification checks, optional contact abort |

Battery power creates wheel force through the drivetrain. Harvesting requires mechanical braking energy; it is not a free recharge button. The low-drag tradeoff also enters the corner-speed preview. Wake-enabled preview uses a conservative downforce-loss bound rather than planning a corner with free-air grip. Braking preview respects the mechanical brake ceiling.

The battery and tyre coefficients are modelling assumptions, not measured cell chemistry or rubber characteristics. This is a reduced model: no CFD, suspension dynamics, tyre temperature, fuel burn, gearbox shifts, crash damage, aquaplaning or event-certified active-aero zones. Pit entry, service and exit are synthetic states with a rendered lane and crew, not surveyed pit geometry. Lateral motion is a bounded line-tracking approximation rather than a full multibody vehicle. Speeds above 300 km/h are possible where the configured power, drag and geometry allow them; no track is forced to reach a target speed.

## Learning contract: race-control-v2

This environment exposes the `race-control-v2` observation and action contract. Trained policies must use this exact contract.

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

The action is an eight-value float32 vector bounded to [-1, 1]. Its fields are driver authority, deployment profile, pace scale, lateral target, low-drag mode, pedal mode, throttle, and brake. Automatic authority retains observation-driven racecraft and applies the chosen battery profile. Direct authority applies every remaining field. Automatic pedal mode lets the physical speed controller follow the pace request; manual pedal mode applies throttle and brake. The generator records field order, bounds, decoded control, and deployment profile order in every manifest and transition. Use `encode_control` and `decode_action` instead of duplicating the mapping.

Reward is negative elapsed seconds, minus 0.1 when the requested control changes. On finishing, subtract 30 times positions lost from first. An unsupported lateral envelope incurs a 20,000-unit terminal penalty, as does contact when termination mode is selected. There is no repeatable per-pass bonus. A time limit is a truncation, never a race finish; PPO can bootstrap the final observation. Software errors raise and must not be relabelled as racing outcomes.

## Generate a dataset

```sh
make race-generate CIRCUIT=monza SEED=42 CARS=20 DURATION=1800
```

Monza defaults to its 53-lap Grand Prix preset. Pass `LAPS=3` for a custom short episode. The default output is `.afterlap/race/monza-42.jsonl`. Set `OUTPUT` to select another file. Existing output files are refused, preventing accidental replacement of an experiment. The first line contains settings, geometry and bundle hashes, vehicle configurations, integrator identity, provenance and action mapping. Each subsequent line contains the observation, requested action, decoded control, reward, next observation, terminated/truncated flags and allowed diagnostic info. A seeded random policy provides exploration data; it is not a competitive baseline or an expert demonstration.

PPO is an on-policy method and collects its own transitions from `RaceEnv`. The generated JSONL is useful for inspection, replay checks and offline-learning research; simply loading it into PPO is not training. A separate offline RL algorithm would need an appropriate dataset loader, behaviour-policy treatment and validation.

## Train and evaluate

```sh
make race-train CIRCUIT=monza CARS=20 STEPS=10000
```

This installs the learning dependency group, checks the Gym contract, and trains Stable-Baselines3 PPO on CPU. It writes `.afterlap/race/policy-42.zip`. The learning group selects CPU PyTorch wheels on Linux and Windows. macOS uses its native PyTorch package. No CUDA installation is required.

For a wiring smoke run, use one car, a short episode and 128 steps. This tests collection, optimization and checkpoint writing; it does not establish useful driving performance.

For a meaningful experiment:

1. Freeze a manifest with code revision, the emitted bundle hash, action/feature versions, reward, training steps and all seeds. Keep the source checkout with the run.
2. Train across circuit, weather, car and initial-state seeds. Keep whole circuits and scenario families out of the training set. Do not randomly split adjacent race frames.
3. Compare the learned control policy against fixed automatic-profile controls and explicit direct-driver controls on identical held-out seeds. All policies must use the same observed features.
4. Record finish position, race time, battery constraint violations, contact/unsupported aborts, truncations and retained passes. Count incomplete and failed runs, not only wins. Bootstrap confidence intervals across independent episodes.
5. Repeat evaluation at a finer physics step and with perturbed car parameters. Check whether strategy rankings survive. Validate against measured telemetry before making real-car claims.
6. Keep model selection and promotion manual. The training command saves a local checkpoint and does not deploy it.

References: [Gymnasium environment API](https://gymnasium.farama.org/api/env/), [time-limit semantics](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/), [Stable-Baselines3 PPO](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html), [WebSocket server API](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html).

## Verification

`make race-check` runs race and numerical tests, targeted Python lint/types, and frontend lint/types. `make race-browser-check` starts an isolated app on ports 18860/18861 and refuses to reuse another server and exercises its live controls in Chromium. `bun run build` checks the complete Next.js production build.

Tests cover all 23 imported layouts, 20-car setup, deterministic delayed-command restore, energy balance, masked observations, rival-energy isolation, finish versus timeout, contact abort, command validation and real WebSocket exchanges. A live browser test checks circuit changes, start/pause, stepping, checkpoint restore, driver commands, telemetry download and mobile overflow.

The default 20-car reference engine is CPU intensive. The UI reports observed playback pace separately from rendering FPS. A requested playback rate above available compute does not reduce physics accuracy or skip steps. Long RL runs should measure throughput before choosing episode counts; vectorized environments can distribute separate episodes across available CPU cores.

## Physics v2 configuration and evidence

See [research and model design](RACE_MODELS.md), [parameter reference](RACE_PARAMETERS.md) and [validation report](RACE_VALIDATION.md). The action contract is `race-control-v2`; model behavior is `race-physics-v4`. The battery observation/action contract remains `race-bms-v1`, while the browser uses the direct control contract. An extra delayed own grip channel supports automatic racecraft and operator telemetry. Policy evaluation requires a matching `.manifest.json` sidecar and implementation hash. Policies created for earlier contracts must be retrained.

For precise experiments, use `--settings file.json` with generate, train or evaluate. The entire settings file takes precedence over individual scenario flags, including seed. Use nested feature scales to disable variation groups or supply individual driver traits. Weather phases, target wetness, driver traits, initial states and sensor parameters are included in manifests, not actor observations. `catalogue` prints circuit lap presets. `schema` prints the complete race settings, driver control, and RL action contracts. `evaluate --driver-action action.json` applies the same direct control model used by the browser without requiring it.

```sh
uv run python scripts/race_experiments.py --seeds 101 202 303 --output experiments.json
uv run python scripts/race_benchmark.py --settings scenario.json --output diagnostics.json
uv run python scripts/race.py evaluate --settings scenario.json --profile neutral
uv run python scripts/race.py evaluate --settings scenario.json --driver-action action.json
uv run --group learning python scripts/race.py evaluate --settings scenario.json --policy policy.zip
uv run python scripts/race.py catalogue
uv run python scripts/race.py schema
```

Diagnostics are privileged offline truth, distinct from generated learning transitions. The experiment script initializes matched physical states on a Monza straight, including a leader using a fixed speed controller and a leader that accelerates away. It reports every timeout, failure, event and time series. It does not move cars after initialization or award pass bonuses.

For isolated local service ports, set `RACE_WEB_PORT` and `RACE_SIM_PORT` when running `scripts/race_stack.py`; the upstream URL follows the simulator port. Browser tests use these same variables. Stop only the processes started for your worktree.
