# Design revision 2 — instrumentation workspace

This revision replaces the initial warm-amber workbench styling. It is the current production design reference. Earlier concepts remain exploratory layouts; they do not override the revised workspace. Design judgment here comes from the actual task, screen inspection and specialist UI references, not a skill's self-assigned scores.

## Problems addressed

The original used large slogan-like directives, decorative numbered navigation, a slashed logo, warm amber on nearly every emphasized element, oversized card spacing and repeated marketing constructions. These choices drew attention to the template rather than the engineering decision. The revision changes hierarchy and content as well as palette.

| Previous treatment | Revised decision | Operational purpose |
|---|---|---|
| Promotional directive | Compact verb and end condition: Save through T7 | Read the actionable instruction quickly. |
| Numbered navigation | Plain named modules with a selected edge | Numbers imply an ordering the workflow does not have. |
| Ambient dark amber | Neutral light chrome, dark trace wells, blue selection | Separate interface structure from numeric evidence. |
| Three isolated KPI cards | Ruled telemetry row with aligned values and units | Read related quantities together. |
| Generic side cards | Track position plus battle-context table and event log | Connect own energy with the rival gap and missing rival telemetry. |
| Split marketing hero with a card | Product description followed by wide instrument specimen | Show the actual work rather than a decorative product metaphor. |
| Slogan section headings | Workflow, evaluation and concrete component labels | Explain what the product does. |

## Reference reasoning

[ATLAS timebase/cursor documentation](https://atlas.motionapplied.com/developer-resources/atlas/display-api/timebasecursor/) describes coordinated display timebase/cursor behavior. Preserve that shared inspection model in replay. [ATLAS viewer structure](https://atlas.motionapplied.com/key-functionality/analyse/viewer/quick-start/) informs session/workbook separation. These are functional references, not layouts copied pixel for pixel.

Earlier research includes MoTeC analysis, Grafana annotations and Linear work queues in [RESEARCH_AND_CONCEPTS.md](RESEARCH_AND_CONCEPTS.md). This revision deliberately gives telemetry/channel semantics more weight than task-software styling. No claim is made that a skin alone replicates professional ATLAS or MoTeC capability.

## Review rules for implementation agents

Start each route with the operator's task and current session. Use route-specific structures: engineer instruction and channels; lab controls and scenario; replay aligned traces; evidence tables; rules coverage rows. Do not produce eight copies of one card grid.

Each colour must answer selection, series identity or status. Unknown is text, not an empty green check. A healthy fixture feed does not establish legal compliance. Selected/reference traces keep solid/dashed differences in addition to colour. Colour identity can use a lighter shade inside dark charts while preserving hue and legend meaning.

Use 24–29px operational headings and 13–14px reading text. Large numeric type is for changing values or the simulator driver's instruction, not repeated slogans. Labels need explicit units and aligned decimals. Avoid tiny uppercase provenance repeated on every surface; retain sufficient local/global source context to prevent a simulated value being read as measured.

Components use subtle rules and compact spacing. No gradient fields, glowing borders, animated fake telemetry, decorative car renders, arbitrary status badges, generic bento feature grids or invented confidence. A useful empty state names the missing artifact and the action that would create it.

Keep semantic HTML, clear focus, keyboard actions, disabled/pending/error states, and meaningful colour contrast. Narrow screens stack work areas; tables may scroll inside labelled containers. Test child overflow, not only the root width. The driver screen stays dark and high-contrast because its reading task differs from the engineer's desk.

## Scope and proof

The HTML remains an interactive design reference with authored fixtures. It is not the production React implementation. Review screenshots at real CSS widths, test lifecycle controls after visual edits, and record observed tests in QA_REPORT. Do not label untested responsive sizes as verified. No visual treatment can substitute for measured simulator, controller or model behavior.
