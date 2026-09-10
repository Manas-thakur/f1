# Units, coordinates and clocks

## Internal quantities

Use joules, watts, seconds, metres, m/s, kg, kelvin, radians. Fields include suffixes: `energy_j`, `power_w`, `session_time_s`, `distance_m`, `speed_mps`, `temperature_k`. UI displays MJ, kW, km/h and Celsius with labelled conversion. SoC fraction is 0..1 within a declared physical operating window; it is not interchangeable with remaining legally usable energy. Store limits and measurement location explicitly.

CU-K DC-bus recharge, battery energy gain and mechanical recovered energy differ by conversion losses. Maintain separate ledgers. Never subtract a kW figure from an MJ figure. Positive deployment power propels the car; positive harvest power is a separately named quantity. A signed net-power field must document its convention and must not coexist ambiguously with both nonnegative flows.

## Track frame

Use `s_m` wrapped in [0, track_length_m) and `progress_m = completed_laps * track_length_m + s_m` for unwrapped progress. Use a Frenet lateral coordinate `d_m`, with positive left relative to track tangent, and heading error radians. Do not infer centimetre-accurate lateral placement from public position feeds. Different racing lines are arc-length-mapped to centreline progress for comparable gaps. Time gap is derived at common progress, not casually divided by current speed through corners.

## Time

`source_time_utc` is ISO8601 UTC; `source_time_s` is source session time; `received_monotonic_s` is local ingestion clock; `session_time_s` is the canonical deterministic session clock. Wall time never advances paused simulation. Record a clock mapping and its uncertainty. Bound out-of-order buffering; late events enter the archive but cannot rewrite an already published decision's observed state.

Each event has increasing `sequence` assigned by the session owner. Snapshot records contain `last_sequence`. Stream clients detect gaps and request a new snapshot; reconnect is not a reason to replay an operator command. Each decision has `observation_cutoff_s`, `created_at_s`, `valid_from_s`, `expires_at_s` and a ruleset hash. Evaluate freshness at selection and execution as well as publication.

## Events crossing a step

Interpolate the crossing time within the integration interval; split integration at significant lines and apply transitions in deterministic order. At equal times: safety/rule invalidations first, physical line events second, plan validation third, operator commands fourth, UI snapshots last. Ordering is part of the event contract. No battery refill at a timing line. Only the appropriate per-lap counters reset.

## Unknown and precision

Unknown numeric values are null with reason. Ranges must specify whether they are physical bounds, quantiles or confidence intervals. Use double precision physics. Tests use documented numerical tolerance, not UI-rounded values. Simulator reproducibility is checked on a fixed platform/build; cross-platform numerical equivalence has tolerances rather than an unqualified bit-identical promise.
