# Synthetic parameter reference

All values in this document are configurable hypotheses. None is a measured F1 population distribution. SI units apply. `RaceSettings` and nested models reject unknown fields, non-finite numbers and out-of-range values.

| Preset | Strength | Purpose |
| --- | --- | --- |
| baseline | 0 | Identical nominal vehicles and traits, no noise/patch/gust draws affecting outcomes |
| mild | 0.25 | Small illustrative differences, default |
| training | 0.65 | Broader synthetic training variation |
| stress | 1 | Sensitivity testing, not a claim about likely conditions |

`driver_scale`, `vehicle_scale`, `surface_scale`, `wind_scale` independently multiply preset strength, each in [0, 1]. `sensor_scale` is [0, 2]. Explicit wetness, wind, temperature and driver overrides remain effective in baseline mode. Deterministic does not mean zero sensor/command latency. Weather's explicit `wetness_target` overrides episode target sampling; omit it for a constant baseline.

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

Omitting `laps` selects the chosen circuit's sourced Grand Prix distance. An explicit `laps` value from 1 through 80 always overrides that preset. Run `uv run python scripts/race.py catalogue` for machine-readable circuit defaults and `uv run python scripts/race.py schema` for the complete settings, direct control, and normalized RL action schemas.

## Racing line controls

`contact_mode` defaults to `ignore`, allowing cars to overlap without ending the episode. Set it to `terminate` to retain footprint-based contact failure. The nested `racing_line` settings control each car's seeded, periodic path: `enabled`, `corner_strength` from 0 to 1, `randomness` from 0 to 1, `wander_m` from 0 to 2, `lookahead_m` from 10 to 200, `smoothing_m` from 5 to 100, and `overtake_in_corners`. The generated line remains inside the usable track corridor and is included in the replay manifest.
