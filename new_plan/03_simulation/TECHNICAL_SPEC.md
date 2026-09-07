# Physics and battle simulator

## Deliverable

Implement a headless deterministic engine in `packages/core/simulation/`; rendering is a consumer. Public API: `reset(manifest, seed)`, `step(driver_actions, dt_s)`, `snapshot()`, `restore(snapshot)`, `observe(sensor_config)`. WorldState is private; `observe` is the only controller input path.

## Components

Track: centreline with curvature, width, elevation, grip envelope, legal crossing locations and stable checkpoint IDs. Car: mass, drag/downforce parameterisation, rolling resistance, engine map, ERS efficiency map, torque/power limits, battery operating window and simple thermal parameters. Driver: line tracking, braking envelope, execution delay and mode selection. Opponent: frozen policy identity plus internal memory. Race controller: lap events, safety states and pit events. All configurations carry units, provenance and bounds.

Longitudinal acceleration derives from drive force minus drag, rolling and grade forces divided by mass. Apply traction limits before integrating velocity. Avoid P/v singularity near zero by a torque-limited low-speed branch. A bicycle model or equivalent local lateral envelope represents heading and lateral position; curvature and tyre-force demand limit feasible speed. Use car footprints for overlap and contact. Simplified wake effects may alter drag/downforce only through documented calibrated coefficients.

Electrical deployment changes tractive force, not a scripted speed bonus. Harvesting reduces available propulsive power or adds regenerative braking according to the physical operating state. Brake blending cannot exceed the tyre envelope. Battery energy tracks actual incoming/outgoing battery power and losses; CU-K recharge is a separate regulatory ledger. Battery temperature follows a lumped heat-capacity/heat-rejection model with configurable derating.

## Opponents and overtakes

Provide legal reactive conserve/normal/attack/defend policies plus a policy interface for later learned opponents. Opponents use their own observation limitations. A pass is detected from footprint clearance and unwrapped progress; retained-pass outcome is evaluated at a named later checkpoint. Collision, off-track and failed attempts arise from geometry and dynamics. Do not reward crossing a longitudinal scalar if the cars physically overlap.

## Snapshots and interventions

Snapshot includes every car state, energy ledger, rule state, integrator state, opponent memory, delayed driver actions, sensor buffers and independent random generator states. Branches share exogenous disturbance keys but react to different actions. Use keyed random streams `(scenario, seed, event_type, physical_time_bin)` to prevent changed call order from creating unrelated weather/noise differences. Outcome identity is scoped to the experimental treatment.

## Build sequence

First validate single-car straight/braking/constant-radius cases. Then integrate charge/deployment and line transitions. Add two-car geometry and reactive opponents. Add observation noise and delayed human execution. Only then expose fast batched environments for RL. Use NumPy first, Numba for measured hotspots; preserve a readable reference implementation for numerical tests.

## Acceptance

Energy conservation closes within documented tolerance; no net recharge without a physical source. Halving dt does not materially change branch ranking on the convergence suite. Restore reproduces the trajectory. Controller cannot access truth through info/debug fields. Overtakes fail when geometry is infeasible. Changing deployment changes later energy and position. Report calibration limits rather than calling an uncalibrated model a digital twin.
