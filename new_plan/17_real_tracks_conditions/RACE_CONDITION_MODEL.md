# Race-condition model

The environment must reproduce how a decision changes when circuit, weather, tyres, traffic and rules change together. The factor graph below separates simulator parameters, observable state, hidden state and random events. This prevents future information and private simulator truth from leaking into the policy.

## Factor groups

| Group | Simulator variables | Policy observation | Principal effect |
|---|---|---|---|
| Geometry | curvature, grade, straight length, corridor, banking | fixed lookahead geometry | speed envelope, drag duration, braking energy, pass location |
| Atmosphere | pressure, air/track temperature, humidity, wind and rain | measured values with age/uncertainty | air density, cooling, drag, grip and battery temperature |
| Surface | dry/wet state, rubber, local grip, bumps | grip estimate and rain/track status | braking distance, wheel slip, recovery limit and line choice |
| Tyres | compound, age, temperature, wear and damage | own measured/estimated, rival inferred | traction, rolling loss, braking stability and pace |
| Vehicle | mass/fuel, aero map, efficiencies, battery SOC/temperature/health | authorised own estimates | power demand, deployable energy and recoverable energy |
| Traffic | gaps, relative speed, lateral occupancy, wake and tow | permitted observed/estimated values | drag reduction, downforce loss, overtake feasibility |
| Race state | lap, position, stint, pit window, finish distance | current state | value of position, energy horizon and traffic forecast |
| Control/rules | active aero, Overtake eligibility, flags, SC/VSC, event curves | current applicable state and known future geometry | legal actions and energy/power limits |
| Human | engineer delay, radio delay, driver response/missed action | pending instruction and delay belief | when the plan can physically begin |
| Opponent | intent, pace, energy and response memory | belief distribution only | counterattack, defence and future gaps |

## Atmosphere and altitude

Calculate dry-air density from pressure and temperature, with a humidity correction when inputs support it. Use density consistently in aerodynamic drag, downforce and cooling correlations. Wind becomes head/cross components at each track point using local heading. A single global headwind sign is wrong on a closed circuit.

Weather samples come from real session observations when replaying an event. For synthetic real-circuit training, fit joint distributions by circuit and season period: track/air temperature, pressure, humidity, wind and rain regime. Preserve correlations and temporal persistence. Do not independently shuffle track temperature, rain and humidity. Include forecast error and sensor latency; the policy never receives future measured weather.

Mexico City's 2,285 m altitude makes density variation a first-class validation case. Spa provides a weather-transition test. Sepang/Singapore provide heat and humidity tests. These named cases guide coverage; empirical distributions come from recorded sessions and carry session IDs.

## Grip and tyres

Represent effective friction as a base surface coefficient multiplied by wetness, rubber evolution, tyre compound/state, temperature and load sensitivity. This is a reduced model. Calibrate it to speed/braking residuals and disclose uncertainty; do not claim full tyre thermodynamics.

Tyre state influences recovery through deceleration and stability. Maximum theoretical MGU-K recovery does not imply the driver can harvest it without exceeding grip, rear stability, battery acceptance or event limits. When wetness rises, increase braking-point uncertainty and constrain usable regeneration according to validated vehicle assumptions.

Use categorical compounds plus continuous age/temperature/wear. Public stint data identifies declared compound and lap age but not complete tyre carcass state. Treat rival tyre temperature and damage as hidden hypotheses.

## Energy deployment and regeneration

At each integration step:

```text
P_wheel_demand = longitudinal_force * speed
P_ers_drive_dc = commanded electrical drive power after applicable limits
P_ers_recharge_dc = recoverable braking power after motor, grip, battery and rule limits
dE_battery/dt = -P_ers_drive_dc / eta_discharge + eta_charge * P_ers_recharge_dc - P_aux
```

Define signs and bus locations in the shared unit contract. Apply speed-dependent standard/Overtake curves from the event package. Track cumulative recharge at the correct FIA measurement boundary. Battery temperature changes acceptance, efficiency and future availability. Active-aero mode changes drag/downforce and therefore demand/grip. Avoid duplicate energy: wheel braking work cannot simultaneously enter battery and friction brakes.

The 2026 technical rules cap absolute ERS-K DC power at 350 kW, but event-specific speed curves and recharge values qualify what can happen at a given circuit/session. The latest event Power Unit Information has priority. FIA public material also describes Overtake eligibility within one second at the detection line and extra energy conditions. The rules checker, not RL reward, enforces them.

## Traffic and overtaking

Use a local two-dimensional corridor around likely battle zones. Longitudinal gap alone can estimate a tow but cannot establish side-by-side space or contact probability. Model wake as relative longitudinal/lateral position, yaw and speed-dependent drag/downforce modifiers calibrated to declared assumptions.

Opponent policies react to each branch using their own energy belief, position and recent actions. Include defend, normal, conserve and attack modes with memory. They may choose a different line, deployment profile or pit action. Recorded rival controls are valid historical observations only; after our counterfactual action changes the race, replaying the same rival trajectory would break causality.

An overtake event has stages: close, overlap, complete pass, and retain position at a later checkpoint. Reward/metrics distinguish them. Track passability emerges from geometry, corridor, pace delta, rules and opponent behavior. Do not hardcode a “Monaco penalty” as a substitute for physical and statistical modelling.

## Race-control and discontinuities

Race-control events are an event-driven state machine. Yellow/double-yellow, VSC, SC, red flag, restart and wet/visibility restrictions change eligibility, pace and planning horizon. Random training events draw from circuit/session-conditioned hazards, with realistic duration and warning; held-out evaluation retains pre-generated event tapes shared across controllers until their own actions causally affect an event.

Safety-car bunching changes gaps and energy opportunity. Pit entry/exit and pit-lane are separate low-speed paths, not normal centreline segments. Red flag and session suspension preserve/reinitialize state according to applicable event rules. If a rule transition is unsupported, return unknown and withdraw affected advice.

## Calibration hierarchy

Calibrate in this order: geometry/clock, free-air single-car pace, braking/traction, energy ledger using authorised or synthetic labelled data, thermal response, traffic interaction, opponent behavior, then race-control distributions. Fitting all parameters against lap time creates compensating errors and poor transfer.

Use several telemetry channels and segments. Match lap time alone is insufficient. Report residuals by straight, braking, corner and weather regime. A real circuit with an uncalibrated car remains a synthetic real-circuit scenario.
