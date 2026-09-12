# Synthetic parameter reference

All values in this document are configurable hypotheses. None is a measured F1 population distribution. SI units apply. `RaceSettings` and nested models reject unknown fields, non-finite numbers and out-of-range values.

| Preset | Strength | Purpose |
| --- | --- | --- |
| baseline | 0 | Identical nominal vehicles and traits, no noise/patch/gust draws affecting outcomes |
| mild | 0.25 | Small illustrative differences, default |
| training | 0.65 | Broader synthetic training variation |
| stress | 1 | Sensitivity testing, not a claim about likely conditions |

`driver_scale`, `vehicle_scale`, `grid_scale`, `surface_scale`, `wind_scale` independently multiply preset strength, each in [0, 1]. `sensor_scale` is [0, 2]. Explicit wetness, wind, temperature and driver overrides remain effective in baseline mode. Deterministic does not mean zero sensor/command latency. Weather's explicit `wetness_target` overrides episode target sampling; omit it for a constant baseline.

Let `S` be preset strength times the feature scale. Risk `r`, response `q` and line `l` are independently sampled standard normals clipped to [-2, 2], then multiplied by driver `S`.

| Driver field | Sampling | Allowed explicit range |
| --- | --- | --- |
| headway_s | 0.8 - 0.15r s | 0.4-2 s |
| reaction_s | 0.18 + 0.05q s | 0-0.5 s |
| clearance_m | 0.65 - 0.12r m | 0.3-1.5 m |
| commitment_s | 1.5 + 0.5r s | 0.5-4 s |
| pace | 0.93 + 0.02r | 0.7-0.98 of corner envelope |
| braking_fraction | 0.92 + 0.02r | 0.75-0.98 of braking envelope |
| jerk_mps3 | 5 + 1.5r m/s³ | 1-15 m/s³ requested slew, emergency exception |
| lateral_rate_mps | 1.5 + 0.3r m/s | 0.5-2.5 m/s target slew |
| preferred_line_m | l m | -3 to 3 m |
| reserve_j | 650000 - 150000r J | 0.2-1.5 MJ |

Battery reserve release is 0.2 MJ above entry. Following requests are bounded to [-15, 4] m/s², further limited by the actual plant. A new pass requires closing speed above 0.3 m/s. Tactical curvature demand must be below 0.7 times gravity times measured grip. These are controller design choices, not real-world safety thresholds. Sweep headway, commitment, braking and grip before interpreting scenario outcomes.

| Vehicle quantity | Sampling |
| --- | --- |
| Mass | 805 + S * U(-25, 25) kg |
| Drag area | 1.175 + 0.125u m² |
| Downforce area | 4.3 + 0.5u m², same setup latent u = S * U(-1, 1) |
| Engine map multiplier | 1 + S * U(-0.06, 0.06) |
| Low-speed tractive force | 17750 + S * U(-1250, 1250) N |
| Initial speed | 14 + S * U(-2, 2) m/s |
| Initial battery energy | 3.1 + S * U(-0.7, 0.7) MJ |

Sensor noise retains the scenario's named keyed streams and scales its documented standard deviations by preset strength and sensor scale. Default delay remains 0.1 s; quantization remains deterministic. No newly sampled traits are provided to the actor.

| Environment field | Definition and bounds |
| --- | --- |
| wetness_target | Explicit [0, 1], otherwise clip(initial + 0.3 S * N(0,1), 0, 1) |
| weather_tau_s | 120 s default, allowed 30-1800 s |
| Spatial loss amplitude | 0.12 * surface S, field p(s) in [0, 1] |
| Surface wavelengths | Track length divided by 3 and 7, continuous at timing line |
| Gust amplitude | 4 * wind S m/s |
| Gust periods | 2π * 7 and 2π * 17 s |
| Phases | Four independent U(0, 2π) values, one episode stream |
| Wetness multiplier | 1 - 0.45 * wetness, bounded [0.55, 1] |

Example configuration, usable by generation, training, evaluation and benchmarking:

```json
{"circuit":"monza","cars":2,"seed":101,"time_limit_s":30,"wetness":0.2,"variability":{"preset":"training","wetness_target":0.7,"weather_tau_s":120,"wind_scale":0,"drivers":{"car-01":{"headway_s":1.1,"pace":0.9}}}}
```

```sh
uv run python scripts/race.py generate --settings scenario.json --output run.jsonl
uv run --group learning python scripts/race.py train --settings scenario.json --steps 128 --output policy
uv run --group learning python scripts/race.py evaluate --settings scenario.json --policy policy.zip
uv run python scripts/race.py evaluate --settings scenario.json --profile conserve
uv run python scripts/race_benchmark.py --settings scenario.json --output benchmark.json
```

Output files for generation and diagnostics are exclusive-create. Policy sidecars record the exact implementation hash and contract. Keep policy and sidecar together, with the source revision and experiment settings.

## Scenario controls and ownership

This file inventories the live race model, including inherited vehicle, electrical, track, sensor and controller behavior. [RACE_MODELS.md](RACE_MODELS.md) explains research choices; [RL_TRAINING.md](RL_TRAINING.md) explains training and evaluation. Settings JSON controls the first two tables and driver overrides. Vehicle documents and engine constants below require source/configuration changes and a newly validated model; they are not all dashboard sliders.

| RaceSettings field | Default | Allowed values and effect |
| --- | --- | --- |
| circuit | silverstone | A catalogue identifier in `configs/race-circuits`; 23 artwork layouts |
| seed | 42 | Integer 0 through 4294967295; replayable episode root |
| cars | 20 | Integer 1-20; internal identities `car-01` through `car-20` |
| laps | 3 | Integer 1-80; race distance uses timing-line crossings |
| dt_s | 0.01 s | 0.005-0.02 s; RK2 integration step, not playback speed |
| wetness | 0 | 0-1; initial wetness |
| temperature_k | 303.15 K | 273.15-323.15 K; air density, ambient cooling and initial battery temperature |
| wind_mps | 0 m/s | -20 to 20 m/s; signed base wind resolved against heading |
| wake | true | Enables aerodynamic interaction |
| time_limit_s | 1800 s | 1-14400 s of simulated time; expiration truncates the episode |
| variability | mild defaults | Nested preset, source scales, weather controls and per-car traits described above |

Explicit driver fields use the nominal values in the sampling table when omitted from an override. Overrides replace that driver's sampled trait record; they do not merely add a delta. All six source scales default to 1. `wetness_target` defaults to null, `weather_tau_s` to 120 s, and `drivers` to an empty object. Unknown fields and driver IDs outside the chosen field are rejected. Circuit existence is checked when constructing the session.

The live UI can choose a fresh episode seed or retain one for replay. In training, `reset(seed=X)` reproduces X exactly and restarts its subsequent episode-seed stream. The first implicit reset uses the configured seed; subsequent implicit resets advance that stream. Resolved `episode_seed` appears in reset/step info and worker monitor logs. Replaying the same explicit seed is intentionally deterministic. Variation changes opportunities and outcomes, without forcing a different winner.

## Starting field and cosmetic identity

Grid strength is preset strength times `grid_scale` (default 1, allowed 0-1). The independent `grid:episode` stream shuffles car IDs when grid strength is nonzero. The rear position begins at 20 m, then each candidate adds `14 + grid_strength * U(-5, 8)` metres. A single car begins at 200 m. Lateral offsets sample `U(-limit, limit) * sqrt(grid_strength)`, with `limit = max(0, (track_width - car_width)/2 - 0.8 m)`. A candidate overlapping any placed physical footprint is advanced by car length plus 2 m and retried, up to 64 attempts. This considers actual track geometry, not just progress gaps. Baseline uses a deterministic centre-line queue with 14 m spacing. Grid variation depends on preset strength and `grid_scale`, independently of `vehicle_scale`. Set `grid_scale` to 0 to isolate car/driver variation with an unchanged grid.

There is no two-car group assignment, paired lane parity or required overtaking distance. A pack may still form through traffic and comparable pace. Car labels are sampled without replacement from 31 historical F1 champions using `cosmetic:driver-labels`, separately from physical streams. These are display names, not calibrated simulations of those drivers. Stable car IDs remain the configuration and policy identities.

## Vehicle document and inherited plant constants

The values below come from `configs/cars/synthetic-2026.yaml`. Factory sampling replaces mass, CdA, ClA, tractive-force cap and engine-map multiplier with the distributions above. In particular, the race's nominal mass is 805 kg, not the source document's 798 kg. Metadata bounds express declared assumptions; model validators additionally require physical consistency. No value in this table is a measured F1 specification.

| Field | Source nominal and declared bounds | Role |
| --- | --- | --- |
| mass_kg | 798 kg, 500-1200 | Inertia and weight; race factory overrides |
| cda_m2 / cla_m2 | 1.2 m², 0.3-3 / 4 m², 0-12 | Drag/downforce areas; correlated race overrides |
| crr | 0.012, 0.001-0.05 | Rolling coefficient |
| air_density_kgpm3 | 1.2 kg/m³, 0.8-1.4 | Generic environment fallback; race weather uses temperature-derived density |
| ice_power_map | (speed m/s, power kW): (0,0), (10,180), (20,300), (40,400), (100,400) | Piecewise linear engine map, multiplied by episode engine factor |
| max_tractive_power_w | 750 kW, nonnegative | Declared combined power envelope in car configuration; current force path combines engine and deployment power directly |
| max_tractive_force_n | 18000 N, nonnegative | Low-speed force cap; race factory replaces with nominal 17750 N |
| drivetrain_efficiency | 0.96, 0.5-1 | Shaft-to-wheel multiplier, applied once |
| max_brake_force_n | 45000 N, nonnegative | Mechanical brake ceiling, also used by preview |
| length_m / width_m | 5.6 m, at least 1 / 2 m, at least 0.5 | Oriented contact footprint and corridor limit |
| eta_discharge / eta_charge | 0.95 / 0.94, each 0.5-1 | Battery-terminal/DC conversion |
| battery_energy_min_j / max_j | 0 / 4000000 J, nonnegative | Operating window; max must exceed min |
| max_deploy_power_w / max_harvest_power_w | 350000 W each, nonnegative | DC power ceilings |
| aux_load_w | 2500 W, nonnegative | Battery-terminal auxiliary demand |
| regen_enabled / regen_share | true / 0.6, 0-1 | Regeneration enable and share of mechanical braking |
| c_th_j_per_k / h_w_per_k | 80000 J/K, at least 1 / 900 W/K, nonnegative | Lumped battery thermal capacity and heat rejection |
| ambient_temperature_k | 303.15 K, at least 200 | Replaced by scenario temperature |
| derate_start_temperature_k / end | 328.15 / 343.15 K, at least 200 | Linear deployment derating; end must exceed start |
| charge_acceptance_start_temperature_k / end | Both absent | Optional generic charge derating ramp; no temperature-based acceptance reduction in this race car |
| regen_grip_floor | Absent, fallback 0.3 | Zero recovery at/below this environment grip multiplier |

Initial battery temperature is ambient plus 5 K. Initial profile is inherited from `InitialCarState` (neutral) and subsequent automatic profile choice comes from racecraft. The generic driver's reaction standard deviation and execution jitter are both zero; line tracking gain is 2.5/s. Per-episode reaction mean and braking fraction override the template.

## Force, motion and energy calculation

`simulation/physics.py`, `engine.py`, `braking.py`, `battery.py` and `energy_limits.py` implement the following path. Gravity is 9.80665 m/s². Air speed is `max(0, vehicle_speed + heading_resolved_headwind)`.

1. Drag is `0.5 * rho * CdA * air_speed²`; downforce uses ClA in the same expression. Wake and low-drag multipliers modify areas before force evaluation. Low-drag mode multiplies CdA by 0.82 and ClA by 0.75, including the conservative corner preview.
2. Rolling resistance is `Crr * mass * g * cos(grade)`; grade resistance is `mass * g * sin(grade)`. Current race grade is zero. The tyre envelope is `mu * (mass*g + downforce)`, with lateral demand `mass * speed² * abs(curvature)`. Longitudinal allowance is `sqrt(max(0, envelope² - lateral_demand²))`.
3. Preview samples 0-96 m every 4 m and 100-400 m every 20 m. It combines corner limits and backward braking feasibility, uses 95% of track grip, the driver's braking fraction and the mechanical brake cap. Wetness is delayed by 0.1 s and spatial grip uses its declared worst bound. Actual hidden patches and future wetness do not enter this plan. Wake preview assumes a conservative downforce loss. The vector/JIT path preserves this same contract.
4. Automatic target speed is pace times the preview envelope. Requested acceleration uses a 0.08 s response above target and 0.6 s below. Resistance compensation converts it to throttle/brake. Racecraft supplies an additional acceleration ceiling. Explicit pedals bypass target-speed tracking while physical limits remain active.
5. Wheel power is `(ICE_power * throttle + actual_DC_deployment) * drivetrain_efficiency`. Tractive force is bounded by the torque cap and power/speed, with a finite low-speed branch. Subtract friction brakes, clamp to the longitudinal tyre allowance, subtract drag/rolling/grade, then divide by mass. Velocity is nonnegative.
6. RK2 evaluates a midpoint force state. Progress integrates midpoint speed; lateral position integrates first-order target tracking. Requested target stays within the corridor minus the half-car footprint; heading error is `atan2(lateral_rate, max(speed,1))`. This is not a bicycle or tyre-slip dynamics model.
7. The ledger first supplies available auxiliaries, then deployment from remaining energy, then mechanically sourced harvesting into available headroom. `P_battery_out = P_DC_deploy/eta_discharge`, `P_battery_in = eta_charge * P_DC_harvest`; conversion losses are heat. Saturation reduces actual power and hence force. Recharge totals accumulate separately per lap and over the session; timing-line events reset only the lap total.
8. Battery temperature follows `T_next = T_steady + (T-T_steady)*exp(-h*dt/C)`, with `T_steady = ambient + loss_power/h`. A zero-h branch uses linear heating. Deployment derates linearly from full at 328.15 K to zero at 343.15 K. Recovery is limited by mechanical brake power, regen share, DC cap, optional charge acceptance and grip. Grip recovery scales as `clip((grip-0.3)/0.7,0,1)`.

Event-specific energy curves and recharge allowances exist in the generic engine but are not supplied to the live race session. An absent event curve is not a confirmed regulatory allowance. The race model does not enforce actual FIA eligibility or current regulations. Contact and unsupported tyre-envelope motion stop the episode; no collision impulse, damage, tyre wear, fuel consumption, pit stop, suspension, banking or elevation model is present.

## Wake and racecraft constants

| Wake parameter | Default | Calculation |
| --- | --- | --- |
| range_m / decay_length_m | 40 / 12 m | `decay = (exp(-gap/12)-exp(-40/12))/(1-exp(-40/12))`; zero beyond 40 m |
| lateral_scale_m | 1.6 m | Multiply by `exp(-(lateral_offset/1.6)²)` |
| speed_reference_mps | 30 m/s | Multiply by `clip(leader_speed/30,0,1)` |
| drag_reduction_max / downforce_loss_max | 0.28 / 0.35 | Areas multiply by `1 - maximum_loss * shielding` |

Wake chooses the strongest nearby periodic physical interaction, including lapped cars. It does not add multiple wake deficits. Generic wake metadata declares ranges 1-200 m, decay 0.5-100 m, lateral scale 0.2-10 m, reference speed 1-100 m/s, drag loss 0-0.6 and downforce loss 0-0.8. Runtime requires positive lengths/speed and losses below 1.

Racecraft decisions occur every 0.1 simulated seconds. The planning horizon is `max(commitment_s, 2*car_width/lateral_rate)`. Nearby forward traffic is considered within `max(30 m, speed*2.5 s)`. Constant-relative-speed forecasts compensate observed age plus reaction time. Candidate pass lines differ from the rival by car width plus clearance plus 0.3 m, and are clipped by corridor width. Passing requires closing speed above 0.3 m/s, enough predicted longitudinal clearance during the lateral move and curvature demand below `0.7*g*observed_grip`. Return clearance includes car length, trait clearance and speed times reaction time. Requested lateral position slews at the trait's rate.

Following uses net gap at least 0.2 m and `a = (0.45*(net_gap-speed*headway)-1.2*closing)/(1+headway)`, capped by `4 - closing*max(0,closing)/(2*net_gap)`. Requests stay in [-15,4] m/s² and slew at the trait jerk limit, except an imminent collision. These are requested limits, not guarantees on integrated jerk near an artwork corner. The state machine covers free, closing, following, committed, alongside, returning, aborting and recovering states. It holds a selected rival and line through an attempt, and can safely abort or reattempt; physical outcome determines completion.

## Sensors, actor boundary and diagnostics

Sensor delay is 0.1 s. Base standard deviations are speed 0.15 m/s, progress 0.5 m, relative progress 0.4 m and gap 0.02 s, each multiplied by preset strength and `sensor_scale`. Speed quantization is 0.01 m/s and gap quantization 0.001 s. Noise uses named deterministic 0.01 s time bins. Baseline removes random noise while retaining delay and quantization. Own energy is available with simulated provenance, rival energy is hidden. Unavailable channels remain unavailable.

`CarState` tracks progress, periodic s, lap, speed, acceleration, lateral position, heading error, elapsed time, distance, battery energy/temperature, total and per-lap recharge, active/pending profile and application time. Force diagnostics are drive, drag, rolling, grade, longitudinal allowance, tyre envelope, lateral demand, lateral acceleration and tyre utilization. Power diagnostics are ICE, DC deploy/harvest, terminal out/in, auxiliaries, conversion losses, mechanical braking/rejection, target/envelope speed and derating. They are internal truth or delayed own telemetry according to the observation builder, never an implicit expansion of the RL actor vector.

Snapshots include car states, ledgers, race clock, event queue, named RNG states, noise keys, delayed sensor history, action queues, active controls, checkpoint/pass records and persistent racecraft state. Restore checks model version and full scenario settings. Renderer interpolation, car names, scenery and camera settings have no authority over this state. See [RL_TRAINING.md](RL_TRAINING.md) for the exact 40-component observation and action mapping.

## Geometry, weather functions and operator actions

Circuit points are deduplicated, closed and scaled to the catalogue's declared length. The track is resampled to `max(100, round(length/5))` points and smoothed with adjacent weights 1:2:1. Tangents and wrapped heading differences produce curvature. Track mu is nominally 1.65; width is uniformly 12 m, grade is zero, timing origin is zero and sector checkpoints lie at one-third/two-thirds length. Race sessions construct the dry map and apply weather once. These are numerical representations of artwork, not surveyed corner radii, banks, kerbs or runoff.

Race air density is `101325/(287.05*temperature_k)` kg/m³. Wetness evolves as `target + (initial-target)*exp(-max(0,t)/tau)`. Let `phase=2*pi*(s mod length)/length`: patch shape is `(2+sin(3*phase+phase0)+sin(7*phase+phase1))/4`, bounded [0,1]. Grip multiplier is `(1-0.45*wetness)*(1-patch_amplitude*shape)`. Gust is half the amplitude times `sin(t/7+phase2)+sin(t/17+phase3)`. Headwind is `(base_wind+gust)*cos(track_heading)`. A shared time and seed define these fields for every car.

| DriverAction field | Default and runtime range | Effect |
| --- | --- | --- |
| profile | neutral; five enum values | Battery request profile |
| pace_scale | 1; 0.70-1.00 | Fraction of preview target speed |
| target_lateral_d_m | 0 m; finite, live control accepts -5 to 5 m | Target offset, additionally constrained by physical corridor |
| throttle / brake | null; explicit 0-1 | Null uses automatic speed control; an explicit pedal enables manual pedal handling |
| harvest_request | 1; 0-1 | Multiplies profile recovery request |
| low_drag | false | Coupled drag/downforce reduction |
| acceleration_ceiling_mps2 | null; -30 to 15 m/s² when specified | Additional requested acceleration ceiling; automatic racecraft uses the narrower [-15,4] range |
| brake_floor | 0; 0-1 | Minimum brake request with throttle cut |
| issued_at_s / label | 0 s / empty string | Command timing and diagnostic identity |

Manual controls are operator experiments, not additional RL actions. An automatic reset clears overrides. Runtime pause, step, playback, checkpoint restore and client reconnection operate on the same server-owned session. The frame and checkpoint carry `started`: false after reset, true after Start or one-step advance. Pause retains it, including at simulation time zero. Start and Play/Pause are separate UI controls; terminal statuses disable both until a new episode is created. Rendering quality, minimap, classification visibility, camera mode, fullscreen and dock/drag positions are presentation controls. They do not change the numerical timestep or physics. The generic policy module also contains older response/cooldown constants for other scenario policies; `RaceSession` clears those policies and uses `race/racecraft.py`, so those constants are not hidden live-race randomness controls.
