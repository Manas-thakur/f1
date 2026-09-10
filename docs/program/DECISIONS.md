# Architecture decisions and open calibration work

| ID | Locked decision | Reason and consequence |
|---|---|---|
| ADR-01 | Local runtime; offline training | Advice must not depend on cloud latency; no online exploration |
| ADR-02 | Reduced physics with local 2D battle geometry | Energy affects physical motion; passing cannot be a random reward event |
| ADR-03 | Scenario MPC plus bounded SAC contribution | Explicit near-term feasibility plus learned delayed consequences |
| ADR-04 | Separate ordinary-return terminal value | SAC entropy-regularised Q is not a calibrated race-time prediction |
| ADR-05 | Versioned rule/event packs | Eligibility and power constraints vary by context; stale plans invalidate |
| ADR-06 | Fixed schemas, SI, explicit provenance | Parallel agents must not create incompatible types or fake measurements |
| ADR-07 | Reactive counterfactual opponents | Recorded rivals cannot remain fixed after an intervention |
| ADR-08 | Engineer is primary operator | Product value is a timely human decision, not a chart collection |
| ADR-09 | Driver link simulation-only | No arbitrary pit-wall-to-steering-screen real-F1 integration |
| ADR-10 | Benchmark gate for learned model | No assumed RL superiority from feature count or a training curve |
| ADR-11 | No LLM in critical planner or rules | Text templates express computed results; optional narrative is read-only |
| ADR-12 | No full CFD or tyre thermodynamics initially | Add complexity only after sensitivity and validation justify it |
| ADR-13 | Next.js is the public HTTP origin | Pages, `/api/v1` and SSE share one origin. Python is a CLI plus loopback session runtime, not the public server |

## Parameters deliberately not fabricated

Car efficiency maps, aero coefficients, thermal limits, brake/traction envelopes, opponent priors, human delay distributions, calibration errors and reward weights require measured data or labelled assumptions. Each parameter carries units, source, bounds and verification status. A synthetic configuration makes software executable; it does not establish realism. An event pack is complete only after all referenced conditions relevant to that event are resolved.

## Objective ordering

Modelled legality and feasibility are hard gates. Among accepted candidates maximise the declared expected race utility with an explicit poor-tail penalty. Report finish position and elapsed time separately; a utility number is never presented as physical seconds. Use a fixed benchmark objective revision across comparisons. Outcome claims apply only to tested operating conditions.

## Concept selection

Select the revised instrumentation workspace in [design revision 2](../design/DESIGN_REVISION_02.md). It develops Concept A with light engineering chrome and dark channel plots. Keep chart linking and inspector density from telemetry tools, attention ordering from task software, and event annotation from observability software. Concept B explores a light engineering notebook; Concept C explores a large battle-board composition. They remain visual explorations, not three competing product architectures.
