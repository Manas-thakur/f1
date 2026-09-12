# FIA Formula 1 2026 rules research and simulator coverage

Research snapshot: 12 September 2026

## Decision summary

The FIA regulations are a six-section championship framework, not only a set of rules that a car
physics loop can execute. This simulator implements the current public rules that produce a
deterministic effect inside a standalone race. It reports the remaining rules as outside its model
instead of suggesting that financial governance, scrutineering, steward judgement, team staffing,
component homologation, or private event control data have been simulated.

The authoritative baseline is the FIA regulation library and the English regulation PDFs. The latest
issues available at the research date are Section A Issue 03, Section B Issue 08, Section C Issue 20,
Section D Issue 07, Section E Issue 06, and Section F Issue 10.[1][2][3][4][5][6][7]

## Regulation landscape

| Section | Regulatory subject | Simulator treatment |
| --- | --- | --- |
| A | General provisions, championship points, governance, enforcement, appeals, suppliers | Race points are calculated. Legal, judicial, championship-entry, and supplier rules are documented only. |
| B | Sporting formats, sessions, grids, starts, race control, driving, penalties, tyres, energy deployment, component limits | Grid order, pit speed, dry-compound use, race classification, and public energy rules are enforced. Starts, race control, penalties, and component pools need systems that this simulator does not have. |
| C | Car construction, aerodynamics, mass, power unit, fuel, electrical systems, transmission, suspension, brakes, wheels, safety, materials, and homologation | Public ERS-K limits feed the physical model. The car remains an explicitly synthetic reduced-order model, not a homologation or crash-test model. |
| D | Team cost cap, reporting, exclusions, audit, and sanctions | Outside a race simulator. |
| E | Power-unit manufacturer cost cap, reporting, exclusions, audit, and sanctions | Outside a race simulator. |
| F | Environmental accreditation, shutdowns, aerodynamic testing, power-unit bench testing, and operational restrictions | Outside a live race simulator. |

This boundary matters. A compliance simulator for Sections C through F would require confidential
design dossiers, physical inspection data, accounts, personnel records, CFD and wind-tunnel usage,
test-bench logs, FIA seals, and event documents. None of those inputs exist here.

## Enforced race rules

### Grid and distance

The cars begin in qualification order. This implements the base ordering in B2.5.4. Grid penalties,
withdrawals, a cancelled qualifying session, and steward discretion are not modelled.[3]

The Grand Prix presets use the published 2026 circuit lap counts. B2.5.2 defines the scheduled race
as the least whole number of laps exceeding 305 km, except Monaco at 260 km. Custom 1 to 80 lap
races remain available and are clearly training scenarios, not official Grand Prix distances.[3]

B2.5.3 limits an uninterrupted race to two hours and permits a three-hour total window when a race
is suspended. The application exposes a simulation time limit. It does not claim to implement the
lap-after-time expiry procedure because race suspension and resumption are not yet modelled.[3]

### Pit lane and tyre strategy

The pit lane limiter caps a car at 80 km/h from the modelled pit-lane line through its stop and exit,
matching B1.6.3. A real Race Director may amend the limit, but no event-specific amendment input is
available here.[3]

Each car receives a seeded hard, medium, or soft dry compound. The three compounds are visually
distinct. The soft has the highest assumed initial grip and lowest assumed life, the hard reverses
that trade-off, and the medium lies between them. This ordering agrees with Formula 1's current tyre
guide, but the numeric grip and durability values are synthetic because public regulation does not
provide a universal circuit-independent degradation curve.[8]

B6.1 requires three visibly distinguishable dry specifications plus intermediate and wet
specifications at an event. B6.3.6 requires at least two different dry specifications during a race
unless the driver used intermediate or wet tyres. The automatic strategy requests a different dry
compound by mid-race if degradation has not already caused a stop. A finished car that has not used
two compounds is marked disqualified. The tyre is counted as used only once the car completes the
modelled pit exit.[3]

The visible weather choice is deliberately presentational. It does not declare the track wet, choose
intermediate or wet tyres, or waive the two-compound rule. The separate wetness input remains the
physical low-grip scenario control. A future wet-race rules module needs intermediate and full-wet
compounds, Race Director declarations, Safety Car starts, and the B6.3.7 wet-tyre mandate.

Pit service lasts a seeded 2.0 to 3.0 seconds. That interval is a scenario assumption, not an FIA
minimum or maximum. Position loss comes from the simulated deceleration, stationary service, and
reacceleration rather than a classification shortcut.

### Classification and points

B2.5.5 orders cars by completed laps and line-crossing order, and classifies a car only if it covers at
least 90 percent of the winner's laps, rounded down. The final race projection applies that 90 percent
test and excludes dry-tyre-rule violations.[3]

Section A2.2.1 awards points only after at least two consecutive green laps. It provides four race
scales based on leader completion: below 25 percent, 25 to below 50 percent, 50 to below 75 percent,
and at least 75 percent. The simulator implements all four tables. A fully completed race uses
25, 18, 15, 12, 10, 8, 6, 4, 2, and 1 for the top ten.[2]

The displayed value is a race-points projection. Constructors, season standings, fastest lap points,
tie resolution, exclusions after scrutineering, and later steward amendments are outside this
single-session model.

### Electrical deployment

Section C5.2.7 caps absolute ERS-K electrical DC power at 350 kW. C5.2.8 supplies public normal and
Overtake speed curves. Without Overtake, the public curve reaches 350 kW through 290 km/h, falls to
100 kW at 340 km/h, and reaches zero at 345 km/h. C5.2.10 sets a base 8.5 MJ recharge ceiling per
lap, subject to lower event values and other conditions. These base limits are enforced by the energy
ledger and power ceiling.[4]

The April 2026 FIA refinement introduced event-specific 250 kW sectors, a maximum Boost increase
of 150 kW, lower recharge values for selected conditions, low-power start assistance, and revised
low-grip behavior.[9] Section B7 says the FIA supplies the Detection Gap, Detection Line, Activation
Line, sector limits, and low-grip adjustments before each competition.[3] Those event documents are
not public inputs in this repository. Consequently:

- the simulator does not label its synthetic closing-opportunity heuristic as FIA Overtake eligibility;
- boost evaluation is training telemetry, not a stewarding or homologation result;
- the manifest states that event power sectors and Overtake authorization are unavailable;
- low-drag bodywork is a synthetic driver command, not claimed compliance with B7.1 activation zones.

This is safer than treating invented sectors or a fixed one-second gap as current FIA data.

## Storyline and physical model behavior

Each car owns an independent seeded narrative stream. Attack, push, coast, and surge events can
start and end independently, so one car can accelerate while another decelerates. Replaying the same
seed and checkpoint reproduces the same timing and tire service. The confusion matrix classifies
boost decisions against an openly defined synthetic opportunity, a closing rival within 65 metres.
It is modular telemetry intended for later policy training.

The pass controller observes delayed, noisy channels, chooses a side, creates lateral separation,
holds the lane through overlap, and returns naturally after clearing the rival. The physics engine
continues to own longitudinal motion, tyre grip, wake interaction, braking, and contact checks.

## Current 2026 technical context

The FIA's 2026 package introduces active front and rear aerodynamics, a larger electrical share,
removal of the MGU-H, fully sustainable fuel, narrower retained 18-inch tyres, stronger impact
structures, additional stopped-car lighting, and a lighter car concept.[10] Current Section C Issue 20
sets the non-qualifying minimum mass at 724 kg plus nominal tyre mass and the qualifying minimum at
726 kg plus nominal tyre mass.[4]

The reduced-order vehicle parameters in this project are labelled assumed or synthetic. They are
not a digital homologation of a 2026 constructor car. Chassis geometry, crash structures, fuel
chemistry, brake construction, wheel dimensions, electronics, materials, cameras, survival systems,
and component seals therefore remain research context rather than enforced runtime rules.

## Verification map

| Behavior | Automated evidence |
| --- | --- |
| 350 kW speed curve and 8.5 MJ base recharge | `tests/race/test_battery.py` |
| 80 km/h pit lane limiter | `tests/race/test_regulations.py` |
| Two-compound request and disqualification | `tests/race/test_regulations.py` |
| 90 percent classification and four points scales | `tests/race/test_regulations.py` |
| Compound grip, wear, seeded service, checkpoint replay | `tests/race/test_storyline.py` |
| Qualification-order start and race lifecycle | `tests/race/test_session.py` |
| Weather, tyre, boost, and 3D race controls | `apps/web/e2e/race.spec.ts` |
| Pit-lane visual trajectory | `apps/web/e2e/motion.spec.ts` |

## Update policy

FIA regulations change during a season. The issue date and source URLs are emitted in every race
manifest. A future update should first compare the FIA library issue numbers, then update regulatory
constants and tests together. Event-specific data should be added only from an authoritative event
document, with its circuit and effective competition recorded in the manifest.

## Sources

1. [FIA Formula 1 regulation library](https://www.fia.com/regulation/fia-formula-1-technical-regulations)
2. [2026 Section A, General Provisions, Issue 03](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_a_general_provisions_-_iss_03_-_2026-06-25.pdf)
3. [2026 Section B, Sporting Regulations, Issue 08](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_b_sporting_-_iss_08_-_2026-08-05_7.pdf)
4. [2026 Section C, Technical Regulations, Issue 20](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf)
5. [2026 Section D, Team Financial Regulations, Issue 07](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_d_financial_-_f1_teams_-_iss_07_-_2026-06-25.pdf)
6. [2026 Section E, Power Unit Financial Regulations, Issue 06](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_e_financial_-_pu_manufacturers_-_iss_06_-_2026-06-25.pdf)
7. [2026 Section F, Operational Regulations, Issue 10](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_f_operational_-_iss_10_-_2026-08-05.pdf)
8. [Formula 1 tyre guide](https://www.formula1.com/en/latest/article/the-beginners-guide-to-formula-1-tyres.61SvF0Kfg29UR2SPhakDqd)
9. [FIA April 2026 regulation refinements](https://www.fia.com/news/refinements-2026-fia-formula-1-regulations-agreed-all-stakeholders)
10. [FIA overview of the 2026 technical package](https://www.fia.com/news/new-era-competition-fia-showcases-future-focused-formula-1-regulations-2026-and-beyond)
