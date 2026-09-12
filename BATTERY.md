# Battery and electrical boost

The feature branch `codex/battery-includes` starts from GitHub simulator commit `76134c0`. Run `make race`, start a race, and watch the energy store beside the speedometer. Open Race controls for the Hybrid energy panel, recent battery trace, current lap totals, and completed lap records. Choose Boost or Maximum boost in Battery profile and apply a driver command to compare deployment; return to automatic control for the observation-driven strategy.

## Research basis

[FIA 2026 Technical Regulations, Issue 20, published 5 August 2026](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf), articles C5.2.7–10, specify a 350 kW absolute ERS-K DC limit and a 4 MJ permitted state-of-charge swing. The base standard deployment ceiling is capped at 350 kW, falls from 290 km/h to 100 kW at 340 km/h, then reaches zero at 345 km/h. The base recharge allowance is 8.5 MJ per lap; event and operating conditions can change it. These are the base values implemented here, not event-specific certification. The 4 MJ window is usable energy, not a claim about physical pack capacity.

[Formula 1's explanation of Boost, Overtake and Recharge](https://www.formula1.com/en/latest/article/explained-the-new-key-terms-for-formula-1s-new-for-2026-rules.3T5BU6TC9quGcIpGzoWkY0) distinguishes driver-requested boost from eligibility-controlled Overtake Mode. Recovery can occur under braking, partial load, lift/coast, or engine-powered harvesting. Electrical deployment assists propulsion and consumes energy; it does not produce nitrous exhaust flames.

## Implementation and assumptions

The existing energy ledger remains authoritative. Deployment removes stored energy with discharge losses; recovery adds energy with charge losses. Auxiliary use remains in the balance. Regeneration is restricted by available braking power, rear recovery share, grip, thermal acceptance, battery headroom, and remaining lap recharge allowance. Rejected recovery does not create battery energy. Passing a timing line resets the lap counters, never the battery.

Automatic racecraft uses delayed own battery telemetry, its existing passing state, acceleration demand, speed, and a 150 m curvature preview. It requests the 80% boost profile during a passing attempt or on a clear straight with at least 0.6 MJ above its reserve, sustaining an ongoing straight burst until 0.2 MJ above reserve. It harvests below reserve and uses a 0.2 MJ hysteresis before leaving recovery. Missing battery measurements select recovery. These thresholds are explicit synthetic strategy assumptions; there are no random boost timers or learned performance claims. Physical acceleration remains subject to traffic, tyres, braking preview and power limits.

Boost telemetry counts actual delivery above 1 kW while a high deployment profile is applied. It includes current burst duration, previous burst duration, current lap duration, and cumulative duration. These counters and lap energy records are checkpointed and sampled through the existing delayed sensor pipeline. Requested and applied profiles can differ during driver reaction time or a thermal/energy limitation. No rival battery channels are added to controller observations. The operator can inspect each car's own simulated telemetry.

The blue trails are explanatory overlays, scaled by delivered electrical power. They disappear when delivery ceases and are frozen with paused simulation time. Green text indicates measured recovery. The HUD shows usable charge, energy, power and burst duration. Missing samples remain unavailable; graph lines break across missing samples.

## Scope

This is a public-rule-informed reduced model, not an exact reproduction of a team's battery management. The race uses a rolling initial condition. The inherited powertrain model does not represent crankshaft torque, battery chemistry, MGU-H, engine-powered superclipping, or full FIA deployment/ramp policing. Recovery here is braking recovery only; selecting Harvest does not recharge a stationary car. Event-specific low-grip curves, additional Overtake energy allowances and detection/activation zones remain unavailable, so all deployment profiles use the base standard curve. Maximum boost is a deployment request, not official Overtake authorization.

Timing and lap totals shown in the UI are delayed observations. At terminal race state, the final sensor-delay interval can remain unavailable; the UI does not replace it with simulator truth. Initial rolling-grid progress also means the first lap record covers the simulated portion of that lap. Numerical correctness does not establish real-car calibration.

Model version is `race-physics-v3`; earlier physics checkpoints are rejected. The BMS action/feature-vector version remains unchanged. Retrain and evaluate policies against the new manifest before using prior policy results.

## Validation

Battery tests cover the standard speed curve, recharge-budget saturation, energy closure, actual boost consumption, delayed observations, lap counter reset without refill, JSON observation export and deterministic checkpoint replay. The existing physics, racecraft, environment and browser suites remain required. Browser coverage checks the live battery HUD and 3D boost indicator using the real WebSocket simulator.

Local validation: 111 Python tests passed. A three-lap automatic Monza run completed with boost and regeneration on each lap. A separate 20-car Monza race finished all 20 cars without contact or envelope failure, with energy closure error below 0.000001 J. These are implementation checks for the tested configuration, not performance calibration.
