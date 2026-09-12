# Circuit scenery references

The scene uses existing circuit artwork scaled to the configured lap length. Roads remain a synthetic, flat 12 m corridor. Buildings, vegetation, water, spectators and landmark dimensions are illustrative, not surveyed geometry. Background hills do not change physics. Madring references include plans for the new venue.

The common scene includes covered stands, animated spectators, catch fencing, guardrails, textured grass and runoff. Close trees use local models; distant vegetation and spectators use simpler geometry. People have articulated bodies and detailed head geometry, not photographic scans. These primary sources informed the profiles:

| Circuit | Reference characteristics | Source |
| --- | --- | --- |
| Austin | Observation tower, painted runoff | [COTA](https://circuitoftheamericas.com/blog/2024/2/20/all-about-the-cota-tower/) |
| Baku | Old walls, urban waterfront | [F1](https://www.formula1.com/en/latest/article/what-makes-the-azerbaijan-grand-prix-special-and-why-you-should-see-it.2czMvJTBkvIcOOEiDJEtlE) |
| Catalunya | Grandstands, grass and gravel | [Circuit](https://www.circuitcat.com/wp-content/uploads/2023/03/Cataleg-hospitality-2023_ANG.pdf) |
| Hungaroring | Green surroundings, grandstands | [Circuit](https://hungaroring.hu/src/Hungaroring_F1_Guidebook_2018_WEB.pdf) |
| Interlagos | Urban setting, green infield | [City](https://autodromodeinterlagos.prefeitura.sp.gov.br/historia) |
| Las Vegas | Night streets, hotels, Sphere | [Promoter](https://www.f1lasvegasgp.com/track-layout/) |
| Lusail | Desert and floodlights | [Circuit](https://www.lcsc.qa/) |
| Madring | IFEMA setting, planned monumental spectator section | [Circuit](https://www.madring.com/circuito) |
| Melbourne | Albert Park lake and trees | [Map](https://www.grandprix.com.au/uploads/images/F126_009_Visitor-Map_A3_V9-Digi-3.pdf) |
| Mexico City | Large stadium spectator section | [F1](https://corp.formula1.com/formula-1-to-race-in-mexico-city-until-2028/) |
| Miami | Stadium and colorful circuit surroundings | [Promoter](https://f1miamigp.com/) |
| Monaco | Dense waterfront buildings and marina | [F1](https://www.formula1.com/en/information/monaco-circuit-de-monaco-monte-carlo.2ZWRtIcSI6ZzVGX1uGRpkJ) |
| Montreal | Parkland island, trees and water | [Park](https://www.parcjeandrapeau.com/en/circuit-gilles-villeneuve-multi-purpose-track-provelo-sports-training-montreal/) |
| Monza | Park forest and historic circuit | [Circuit](https://www.monzanet.it/en/circuit/) |
| Sepang | Tropical setting and covered stands | [Circuit](https://www.sepangcircuit.com/main-grandstand) |
| Shanghai | Expansive venue and large stands | [F1](https://ticketing.formula1.com/china/) |
| Silverstone | Open landscape, Wing, mixed runoff | [Circuit](https://www.silverstone.co.uk/maintaining-race-track), [Map](https://www.silverstone.co.uk/sites/default/files/pdf/British%20Grand%20Prix%202025%20Map.pdf) |
| Singapore | Night skyline, waterfront and Flyer | [Promoter](https://singaporegp.sg/en/tickets/general-tickets/grandstands/bayfront-grandstand/) |
| Spa | Ardennes forest, gravel, covered stands | [Map](https://www.spa-francorchamps.be/assets/1dc2f8bb-48fc-4ab8-b013-404fc31a0ba3/spagp-map-2024.pdf), [Promoter](https://www.spagrandprix.com/en/ardennes-4-jours) |
| Spielberg | Forested hills and circuit sculpture | [Circuit](https://www.redbullring.com/en/history/) |
| Suzuka | Amusement park and Ferris wheel | [Circuit](https://www.suzukacircuit.jp/eng/f1/event/) |
| Yas Marina | Marina and evening lighting | [Circuit](https://www.yasmarinacircuit.com/en/aboutus/discover-yas-island/yas-marina) |
| Zandvoort | Coastal dunes and sand | [Circuit](https://business.circuitzandvoort.nl/en/) |

## Playback and rendering

Speed in km/h is an observed simulated vehicle speed. PACE measures simulation seconds per wall-clock second; TARGET is requested playback. At 300 km/h and PACE 0.5x, the car travels about 41.7 world metres per wall-clock second. Increasing rendering FPS cannot advance physics faster. The view interpolates observations and follows their progress without inventing distance.

CPU braking preview and track sampling use Numba without fast-math. First use can incur compilation overhead; subsequent calls use cached machine code. Rendering follows display refresh. High graphics enables shadows and more nearby detail. Performance lowers resolution and nearby detail. The FPS counter measures rendered frames, not server updates. A paused view stops rendering when unchanged.
