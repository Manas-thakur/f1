# Race physics and interaction model v2

This is a reduced, uncalibrated simulator. Circuit artwork, corridor assumptions and synthetic parameter distributions are not measured F1 data. The actor remains `race-bms-v1`: five battery profiles and 20 normalized features followed by 20 masks. Steering, braking, pass intention, weather parameters and opponent traits are not actor actions or privileged features.

## Diagnosis and runtime

`RaceEnv`, the JSONL generator, PPO collection and the WebSocket server all advance `RaceSession`. It clears `world.policies`; changing `simulation/policies.py` policy classes alone cannot fix live racecraft. The session now calls `Racecraft.react` at 0.1 simulated seconds. The engine executes delayed commands and integrates physical forces at the configured step.

The original following controller computed `a = relative_speed / 0.5 + 0.8 * (gap - 12 - 0.5 * speed)`, then switched directly between full automatic acceleration and a brake floor. Position and speed were already delayed. There was no throttle modulation for following and no pass commitment. In a controlled straight scenario, the selected side was 2.5 m from a centre-line rival, but the following filter still classified any rival within 2.8 m laterally as an obstacle. Thus a car could move to its intended passing side and continue braking for the same rival indefinitely. This reproduces oscillation with no sensor noise, constant weather and no browser. Wake-disabled runs reproduce it too. Battery transitions and visual smoothing are therefore not necessary causes.

The engine also had a discontinuous switch from a force-based throttle calculation to a narrow braking band. Its replacement uses the same resistance-compensated force request on both sides of the target. Stronger response during deceleration retains corner-entry feasibility. Sharp curvature in the artwork still causes abrupt braking; these are not surveyed racing lines.

Classification sorts delayed noisy unwrapped progress, so near ties can change the displayed order without a physical pass. The integrated 3D browser interpolates delayed observations on a shared playback cursor. Display estimates never feed into the engine, learning observations or physical pass events. Rendering FPS and simulated seconds per wall second are separate metrics.

Wake selection previously chose the nearest car in race progress, even if it was laterally irrelevant, and missed lapped traffic. It now uses local periodic separation and the strongest bounded wake among nearby cars. Driver traffic uses periodic local gaps while race events retain unwrapped progress. Lapping is an interaction, not a gained classification position.

## Research and design decisions

| Source and relevant section | Consequence for this implementation |
| --- | --- |
| [Kesting and Treiber, reaction times, update times and stability](https://mtreiber.de/publications/timedelay_CACAIE_07.pdf), sections on reaction delay and stability | Anticipate measured relative motion through sensor age plus driver delay, reduce feedback gains and keep driver traits persistent. Road-traffic stability insights transfer as design ideas, not as validation of a racing policy. |
| [Liniger, Domahidi and Morari, optimization-based racing](https://arxiv.org/pdf/1711.07300), II and III A-C | Separate discrete corridor choice from lower-level physical control. Their bicycle dynamics and MPC are more detailed than this model. Here a small intention state machine and short constant-velocity clearance forecast are tractable; there is no optimizer or claimed MPC equivalence. |
| [Laurense and Gerdes, speed control at the friction limit](https://ddl.stanford.edu/sites/g/files/sbiybj25996/files/media/file/laurense2018_speed_control_for_robust_path-tracking_for_automated_vehicles_at_the_tire-road_friction_limit_0.pdf), II-III | Retain coupled force limits and conservative corner feasibility. Their axle slip and normal-load model cannot be replaced by arbitrary extra grip. Full lateral dynamics require wheelbase, inertia, axle loads and identified tyre curves. |
| [Delft empirical tyre model with temperature effects](https://pure.tudelft.nl/ws/portalfiles/portal/67441232/applsci_09_05328.pdf), thermal model and conclusions | Tyre temperature needs heat sources, heat transfer and experimental identification. Combined-slip and transient limitations matter. Temperature and wear are deferred instead of inventing a temperature optimum or degradation rate. |
| [FIA technical account of following aerodynamics](https://www.fia.com/news/f1s-new-era-everything-you-need-know-about-how-fia-making-formula-1-more-competitive-more), Wake Management | A tow changes drag and downforce together; generation-dependent reported losses do not calibrate this synthetic car. Existing exponential lateral/longitudinal wake coefficients remain assumptions. |
| [FHWA wet-weather friction review](https://highways.dot.gov/safety/speed-management/guidelines-use-variable-speed-limit-systems-wet-weather/chapter-2-driver), friction and water-film discussion | Wetness should reduce friction, with important dependence on surface and speed. Our scalar water-balance proxy has no film depth or aquaplaning and is not fitted to these road-tyre observations. |
| [Scott, Applied stochastic processes](https://www.math.uwaterloo.ca/~mscott/Little_Notes.pdf), Ornstein-Uhlenbeck process | Time correlation differs from independent tick noise. We choose fixed random-phase smooth waves, not an OU process: bounded, replayable, no random walk energy and no timestep-dependent draws. |
| [Peng et al., dynamics randomization](https://xbpeng.github.io/projects/SimToReal/SimToReal_2018.pdf), III and IV | Episode-level parameters remain fixed and hidden. Randomization is a training intervention, not a probability model of actual cars. |
| [Chebotar et al., closing the sim-to-real loop](https://arxiv.org/pdf/1810.05687), simulation distribution adaptation | Identifying plausible distributions needs real observations. Synthetic sensitivity tests cannot establish transfer to real racing. |
| [Agarwal et al., statistical evaluation](https://arxiv.org/abs/2108.13264) | Report independent episodes, failures and uncertainty rather than a selected successful run. Few-seed demonstrations are regression evidence, not population reliability estimates. |

No numerical parameter below was taken as a measured racing-car value from these sources. Existing car and circuit documents retain their own provenance. Published values for different vehicles are not silently imported.

## Implemented mechanisms

### Persistent interaction controller

State: intention (`free`, `closing`, `following`, `committed`, `alongside`, `returning`, `aborting`, `recovering`), rival identifier, goal and requested lateral position in metres, desired acceleration in m/s², state/decision timestamps in seconds and battery-profile memory. Checkpoints copy all state.

The observed gap is advanced by relative speed times sensor age plus command reaction delay. Local gaps wrap into half a lap in either direction. Candidate sides use vehicle width plus preferred clearance, not fixed lane centres. Forecast clearance checks all nearby rivals, including cars behind, across the swept lateral corridor and predicted longitudinal interval. Track width and curvature come from the known synthetic map. A new pass requires positive closing speed, enough time to move aside before overlap and spare cornering capacity over the planning horizon. Corner feasibility deliberately neglects helpful downforce: it is a conservative tactical gate, separate from the engine braking preview.

During commitment, the controller relaxes its steady following-headway objective only if the planned lateral clearance can be achieved before predicted overlap. Collision braking remains active. It holds the chosen side through overlap, waits for speed- and reaction-dependent clearance before returning, and aborts if the chosen corridor becomes obstructed or the rival pulls away after the lateral move. A failed attempt can recover and reattempt; there is no arbitrary long repass ban.

Following uses `a_follow = (0.45 * (net_gap - v * headway) - 1.2 * closing_speed) / (1 + headway)`. Coefficients carry the implicit SI scaling of this synthetic controller. The requested acceleration is also bounded by a relative stopping-distance term `4 - closing_positive² / (2 * net_gap)`. Requests normally change at the driver's jerk limit; an imminent collision can bypass that comfort limit. The engine translates the ceiling to wheel force, with drag/rolling/grade compensation, actual deployment fraction, tyre/brake limits and the existing battery ledger. It never sets speed or position directly.

Lateral targets advance at the driver's bounded rate. The plant still uses first-order line tracking. This does not model yaw inertia, lateral slip, load transfer or the complete force cost of a lane change. The state machine is a reduced racing heuristic, not a collision-avoidance proof. Large reaction delays, unpredictable rivals and the artwork's tight corners can still abort episodes. Cost is linear in observed rivals per driver decision, with constant-size forecasts.

### Episode traits and car setup

Named `traits:<car>` and `vehicle:<car>` streams separate sampling from sensor draws, rendering and weather. Clipped standard-normal latent risk makes headway and clearance decrease together while pace, braking confidence, commitment and requested slew increase. Response delay and line preference use independent latents. A shared aero setup latent increases both drag area and downforce area. This encodes a plausible tradeoff, not an identified distribution. Engine/mass/initial-energy draws are bounded synthetic uniforms around nominal values.

Driver traits remain fixed for the episode. Explicit driver configurations override sampling. Zero strengths remove their source of variation without removing deterministic execution latency. Adding cars does not alter existing cars' sampled traits or setup. Manifests include resolved traits, car parameters, initial states, sensor configuration and weather phases. Cost is linear in field size at reset.

### Evolving wetness, spatial surface and wind

State is an analytic function of episode parameters and simulated time. `w(t) = w_target + (w_initial - w_target) exp(-t/tau)` solves a first-order water-balance relaxation. It represents net wetting/drying, not rainfall measured in mm/h. The weather multiplier is `(1 - 0.45 w) * (1 - A p(s))`; `p(s)` is the average of two shifted sine fields mapped into [0, 1], with 3 and 7 periods per lap. The dry track configuration is used, so wetness is applied once. The existing tyre envelope, braking preview, available power limits and delayed own-grip observation all respond.

Preview uses delayed current wetness and the configured lower bound of spatial grip, never future wetness or the hidden spatial map. The automatic tactical driver sees only its delayed own grip estimate. This idealized sensor is not an experimentally validated grip estimator. The BMS vector stays unchanged and receives no new privileged channels.

Wind is a signed world-axis component plus the average of two random-phase sinusoids with angular frequencies 1/7 and 1/17 rad/s. Headwind is its projection onto heading and enters relative airspeed, drag and downforce. The process is bounded and smooth, with persistent phases and deterministic evaluation at any physical time. It is not turbulent CFD or a stochastic process with a fitted atmospheric spectrum.

No evolving draws occur at integration steps. Changing step size samples the same field; numerical trajectories may still differ. Queries, browser polls and snapshots cannot consume disturbance draws. Cost is constant per sample. Validation checks periodicity, bounds, dry/wet limits, monotonic wetting, wind direction, replay and step sensitivity.

### Pass records and authority

`pass_intent` records commitment and `aborted_attempt` records abandonment. The existing `attempted_pass` means entry into a proximity band, which is not proof of deliberate passing. `longitudinal_overlap` records footprint-clear side-by-side running. `completed_pass` requires a full vehicle clearance in unwrapped race progress. `retained_pass`/`lost_pass` are evaluated at the configured checkpoint. True reversals can rearm a pair; noisy observations cannot generate truth events. There is no pass reward to farm.

BMS actions remain battery-only. A future hierarchical tactical environment should expose a small versioned intention action above the physical controller, after validating lateral dynamics. Continuous steering/pedal RL would currently exploit unsupported line tracking. No new driving contract is introduced here. Saved policy sidecars bind action order, observation shape, reward version and implementation hash; evaluation rejects absent or incompatible sidecars. The hash is intentionally strict even for numerically equivalent code changes.

## Prioritized deferred inventory

| Mechanism | Why deferred | Concrete next step |
| --- | --- | --- |
| Axle load transfer, load sensitivity, yaw and combined slip | No CG height, axle distribution, inertia, cornering stiffness or tyre test data | Add a validated bicycle model and axle-force limiting cases before richer lateral policy authority |
| Tyre thermal state, wear and compound | No identified heat partition, cooling, slip work or wear observations | Obtain tyre test traces, fit heat balance and friction-temperature response, then validate unseen stints |
| Fuel mass and burn | No engine efficiency/fuel map or fuel-system state | Add a consistent chemical-to-shaft energy ledger and validate mass/acceleration limiting cases |
| Surveyed width, grade, banking, runoff | Inputs are flat artwork and assumed 12 m corridor | Import licensed measured geometry with uncertainty and corridor continuity checks |
| Rain films, drainage, rubber line and marbles | Current wetness is a dimensionless hypothesis | Fit surface response against friction measurements and separate drainage from grip |
| Full multi-car aero superposition | No measured wake maps | Validate two-car sweeps first, then test bounded composition against multi-car data |
| Bias, dropouts, driver mistakes and attention process | Existing keyed sensor noise and command delay suffice for initial isolation | Add measured sensor availability traces and version their configuration; keep actor masks intact |
| Pit strategy, crashes and vehicle recovery | Unsupported plant states and event rules | Define collision response and pit geometry before adding rewards or control authority |

The existing combined tyre envelope, battery thermal response, regeneration and numerical checks remain active. No placeholder settings are counted as implemented mechanisms.
