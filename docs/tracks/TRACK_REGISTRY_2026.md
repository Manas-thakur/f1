# 2026 circuit registry

Snapshot date: 8 September 2026. The live [Formula 1 schedule](https://www.formula1.com/en/racing/2026) currently lists 23 rounds. The season was originally announced as 24 rounds, and later changes included the Bahrain Grand Prix being hosted at Sepang in Malaysia. Calendar identity and physical circuit identity therefore require separate IDs. Do not hardcode the original announcement as immutable truth.

| Rd | Event | Physical circuit | Track ID | Geometry status at project start |
|---:|---|---|---|---|
| 1 | Australia | Albert Park Circuit | melbourne | acquire and validate |
| 2 | China | Shanghai International Circuit | shanghai | acquire and validate |
| 3 | Japan | Suzuka Circuit | suzuka | acquire and validate |
| 4 | Miami | Miami International Autodrome | miami | acquire and validate |
| 5 | Canada | Circuit Gilles-Villeneuve | montreal | acquire and validate |
| 6 | Monaco | Circuit de Monaco | monaco | acquire and validate |
| 7 | Barcelona-Catalunya | Circuit de Barcelona-Catalunya | catalunya | acquire and validate |
| 8 | Austria | Red Bull Ring | spielberg | acquire and validate |
| 9 | Great Britain | Silverstone Circuit | silverstone | acquire and validate |
| 10 | Belgium | Circuit de Spa-Francorchamps | spa | acquire and validate |
| 11 | Hungary | Hungaroring | hungaroring | acquire and validate |
| 12 | Netherlands | Circuit Zandvoort | zandvoort | acquire and validate |
| 13 | Italy | Autodromo Nazionale Monza | monza | acquire and validate |
| 14 | Spain | Madring | madring | new layout; event-document validation required |
| 15 | Azerbaijan | Baku City Circuit | baku | acquire and validate |
| 16 | Bahrain GP in Malaysia | Sepang International Circuit | sepang | returned venue; event package must match 2026 |
| 17 | Singapore | Marina Bay Street Circuit | singapore | acquire and validate |
| 18 | United States | Circuit of the Americas | austin | acquire and validate |
| 19 | Mexico | Autódromo Hermanos Rodríguez | mexico-city | acquire and validate |
| 20 | São Paulo | Autódromo José Carlos Pace | interlagos | acquire and validate |
| 21 | Las Vegas | Las Vegas Strip Circuit | las-vegas | acquire and validate |
| 22 | Qatar | Lusail International Circuit | lusail | acquire and validate |
| 23 | Abu Dhabi | Yas Marina Circuit | yas-marina | acquire and validate |

The machine registry records nominal length and lap count where a current official circuit page was available to the project. Those values verify gross scale only. If a timetable and the circuit page disagree, quarantine the field and resolve against the latest FIA event documents. For example, Formula1.com's current Australia circuit page reports 5.278 km while a separate 2026 timetable page says 5.303 km. The registry uses 5.278 km and records the disagreement rather than averaging it.

Madring is a new mixed street/permanent circuit. Its current [official 2026 page](https://www.formula1.com/en/racing/2026/spain) reports 5.416 km, 57 laps and 22 corners. An earlier announcement described a provisional 5.47 km, 20-corner design subject to homologation. Use the event documents and surveyed/as-built geometry, not announcement-era numbers.

Sepang's current [official event page](https://www.formula1.com/en/racing/2026/bahrain) reports 5.543 km and 56 laps. Treat the event as Bahrain GP calendar identity with Sepang physical geometry. This is exactly why `event_id` and `track_id` remain separate.

## Track archetypes for coverage

Archetypes organize tests but do not replace individual tracks. A circuit may belong to several.

- Low-drag, long-straight and heavy-braking: Monza, Baku, Las Vegas.
- Tight street and low passability: Monaco, Singapore.
- Elevation and weather variation: Spa, Spielberg, Interlagos.
- High-speed linked corners: Silverstone, Suzuka, Lusail.
- High altitude and low air density: Mexico City.
- Temporary or mixed surface evolution: Melbourne, Miami, Madring.
- Heat and humidity: Singapore, Sepang, Miami.

These are scenario-selection labels. Their numerical meaning comes from compiled geometry and calibrated condition distributions. Monza's [official page](https://www.formula1.com/en/racing/2026/italy) reports 80% full throttle and a 1.1 km main straight. Monaco's [official page](https://www.formula1.com/en/racing/2026/monaco) documents its narrow layout and difficult overtaking. Formula 1 describes Spa's rapidly changing climate in its [2026 weather forecast](https://www.formula1.com/en/latest/article/what-is-the-weather-forecast-for-the-2026-belgian-grand-prix.5QupAgqDuwoaOaDhQGkorS). Formula 1 lists Mexico City at 2,285 m above sea level on its official ticketing circuit description.

## Readiness states

`discovered` means registry identity only. `geometry_validated` means the metric track package passes closure, orientation and boundary checks. `event_rules_validated` adds human-reviewed FIA event lines and power curves. `condition_calibrated` adds historical distributions with recorded source sessions. `simulation_eligible` requires all mandatory fields and vehicle-model compatibility. The UI must expose this state and refuse a real-track claim below `simulation_eligible`.
