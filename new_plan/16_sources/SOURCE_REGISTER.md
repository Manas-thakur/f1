# Source register and verification scope

Research for this conversation was checked on 8 September 2026. Official documents can change; event configuration must be revalidated before implementation. Links below are references, not evidence that a future implementation passes them. Summaries are deliberately short; read the originals for exact rules.

| ID | Source | Used for |
|---|---|---|
| R01 | [FIA regulations index](https://www.fia.com/regulation/category/2182) | Finding published 2026 editions |
| R02 | [Technical Issue 20](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf) | C5 energy/power constraints and C8 driver/telemetry boundary |
| R03 | [Sporting Issue 08](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_b_sporting_-_iss_08_-_2026-08-05_7.pdf) | Sporting energy/eligibility framework; event applicability requires review |
| R04 | [Miami power-unit information](https://www.fia.com/system/files/decision-document/2026_miami_grand_prix_-_power_unit_information.pdf) | Example of circuit-specific curves, allowances and line locations |
| D01 | [OpenF1 API](https://openf1.org/docs/) | Available public channels, approximate sampling and location limitations |
| M01 | [TUM lap-time simulator](https://github.com/TUMFTM/laptime-simulation) | Reduced-order lap/energy simulation reference; not 2026 F1-ready |
| M02 | [TUM trajectory optimisation](https://github.com/TUMFTM/global_racetrajectory_optimization) | Track/racing-line and powertrain-aware modelling reference |
| L01 | [Soft Actor-Critic paper](https://arxiv.org/abs/1801.01290) | Chosen continuous-action RL algorithm |
| L02 | [SAC implementation documentation](https://stable-baselines3.readthedocs.io/en/master/modules/sac.html) | Supported spaces, deterministic inference and implementation boundaries |
| L03 | [Gymnasium custom environments](https://gymnasium.farama.org/introduction/create_custom_env/) | Observation/action design and environment interface |
| P01 | [Learning predictive control for racing](https://arxiv.org/abs/1901.08184) | Learned future value in predictive racing control; guarantees not inherited |
| P02 | [Predictive safety filter](https://arxiv.org/abs/1812.05506) | Separating learned proposals from constraint checking |
| P03 | [acados](https://docs.acados.org/) | Optimisation runtime reference |
| U01 | [MoTeC i2](https://www.motec.com.au/products/I2) | Linked chart cursors and comparison analysis |
| U02 | [ATLAS viewer](https://atlas.motionapplied.com/key-functionality/analyse/viewer/quick-start/) | Acquisition/viewer/session workflow |
| U03 | [Grafana annotations](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/annotate-visualizations/) | Event annotations linked to evidence |
| U04 | [Linear Inbox](https://linear.app/docs/inbox) | Priority/attention hierarchy; visually inspected public page |

## Research limits

Public sources do not provide proprietary 2026 car calibration maps or rival battery truth. The source register does not fill those gaps. Some FIA supporting documents are referenced by the public regulations; unresolved conditions must remain explicit. The simulator and reward design in this plan are proposed engineering decisions, not prescribed by the FIA or copied wholesale from research papers.

MoTeC/ATLAS/Grafana/Linear are inspirations for interaction principles only. No affiliation is implied; no assets were copied. Model paper results do not establish this product's performance. All demonstration fixtures are synthetic and all current benchmark metrics are unmeasured.


## Revision 2 implementation references

The [technology stack](../00_program/TECH_STACK.md) cites official uv, Vite, React, FastAPI, Pydantic and acados documentation reviewed on 8 September 2026. The [learning guide](../07_learning/README.md) links official SB3 SAC, Gymnasium time-limit and scikit-learn calibration documentation at the relevant implementation decisions. These support tool semantics, not claims that the proposed stack or models have already been built or validated.
