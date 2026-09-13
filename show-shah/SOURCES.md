# Source review and provenance

Implementation snapshot: `dbb00c3`, 13 September 2026. All 15 tracked Markdown files in that snapshot were reviewed, including the two working agreements. Code was used to resolve conflicts between historical descriptions and the current runtime.

| Document | Used for |
| --- | --- |
| `README.md` | System entry points, controls and rendering scope |
| `BOOST_MODEL_ENGINE.md` | Current selected-car HTTP boost, SQLite and two PPO environments |
| `BATTERY.md` | Demand-limited delivery, braking recovery and depletion latch |
| `RACE_SIMULATOR.md` | Physics, operator views, runtime and observation contracts |
| `RACE_MODELS.md` | Racecraft mechanisms, seeded variation and model limits |
| `RACE_PARAMETERS.md` | Parameter provenance and configuration ranges |
| `RACE_VALIDATION.md` | Historical experiment design and evaluation caveats |
| `docs/MODEL_ENGINE.md` | Energy observation, guarded inference, training cycles and manifests |
| `docs/FIA_2026_RULE_COVERAGE.md` | Repository rule coverage and unavailable event inputs |
| `docs/CIRCUIT_SCENERY.md` | Scenery references, rendering interpretation and playback pace |
| `configs/race-circuits/ATTRIBUTION.md` | Circuit artwork provenance |
| `apps/web/public/race-assets/ATTRIBUTION.md` | Existing scene assets |
| `apps/web/public/race-assets/branding/README.md` | Operator-provided trackside artwork |

The current code takes precedence over older snapshots: the live energy policy is PPO with a rules baseline, not the previous deck's proposed SAC/MPC architecture. The hardware flow uses a carless HTTP POST and persisted selection. The legacy WebSocket client remains supported. The physics model is v5, and the full-controller observation/action contract is distinct from the energy-only contract. Historical test counts and timing results are not presented as new measurements. The engineer console's mock prediction and execution panels remain explicitly identified.

Speaker notes point to source files for each chapter. The live server, control state, decision engine, training code, racecraft, physical plant, browser motion and engineer/telemetry views were inspected alongside the documents.

## Reused video work

The car asset and its clone/material treatment are adapted from the earlier `apps/video` project at revision `1004282`. Its Remotion composition, scene objects, loader, motion, camera projection helpers, README and credits were reviewed. The old deck's readme and speaker notes were reviewed for continuity. Its proposed architecture and rival-energy range graphics are not claims about this implementation.

`public/car.glb` is the earlier `raceCarWhite.glb`, from [Kenney Racing Kit 2.0](https://kenney.nl/assets/racing-kit), [CC0](https://creativecommons.org/publicdomain/zero/1.0/). It is generic open-wheel geometry, not a constructor model.

The Monza illustration imports the existing repository circuit JSON. Original artwork is by ROY Jules / julesr0y, [f1-circuits-svg](https://github.com/julesr0y/f1-circuits-svg/tree/9c93759b076d1b87eac265a009b21b399253220a), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), obtained through the pinned Crowdflow source documented in the repository. The illustration recentres and scales the outline into a 3D explanatory view. It is not surveyed geometry.

Product screenshots and footage were captured from the actual application at the implementation snapshot above. Existing scene assets retain the repository's attribution and operator-supplied branding. `public/capture.json` records each source clip and trim. No outside reference footage is included.

## Presentation tooling

- [reveal.js initialization](https://revealjs.com/initialization/) and [PDF export](https://revealjs.com/pdf-export/).
- [Remotion ThreeCanvas](https://www.remotion.dev/docs/three-canvas) for frame-synchronous 3D rendering.

Regulatory values in the presentation describe the repository's implemented baseline, as documented in its coverage report. Event-specific activation data and full regulatory compliance remain outside that claim.
