# Screens, routes and handoff

| Prototype | Production route | Required interaction |
|---|---|---|
| index.html | documentation-only | links every visual deliverable |
| concepts.html | documentation-only | switch between three structural concepts |
| app.html#engineer | /sessions/:id/engineer | select, communicate, observe execution, stale invalidation, evidence |
| app.html#lab | /sessions/:id/lab | parameter edits, start/stop fixture, compare from same snapshot |
| app.html#replay | /sessions/:id/replay | cursor selection and side-by-side trajectories |
| app.html#evidence | /experiments/:id/report | show benchmark schema, missing measurements and audit detail |
| app.html#rules | /rulesets/:id | source-linked coverage and unsupported conditions |
| app.html#models | /models | candidate vs approved distinction, no fake promotion |
| app.html#sessions | /sessions | session/source selection and provenance |
| app.html#settings | /settings | density and reduced-motion preview preferences |
| driver.html | /sessions/:id/driver | simulator-only instruction lifecycle and withdrawal |
| landing.html | / | product narrative and link to engineer workspace |
| simulation.html | /simulation-lab | reproducibility narrative and link to lab |

## Inspector pattern

Use a real dialog/drawer with title, close control, Escape handling and focus restoration. It contains the selected decision's observed state, candidate comparison, source labels, rule results and expiry. Click outside may close only if no unsaved state exists. Keyboard focus must not move behind a modal.

## Navigation/state

All app routes preserve session identity and quality state. The chosen treatment, branch cursor and selected decision are view state, not changes to authoritative simulation truth. Back/forward restores view route. Opening driver in a second tab is explicit and simulation-labelled. Fixture values never silently become live values after a mode label changes.

## Landing content

Product page: statement, product specimen, energy/retained-position explanation, three role links, evidence boundary and final open-workspace action. Lab page: scenario configuration specimen, snapshot/branch/inspect workflow, validation capabilities, clear synthetic-data notice and open-lab action. No lead-collection forms, payments, tracking or external submission.

## Build acceptance

Every visible control navigates, changes a fixture state, opens detail, or is explicitly disabled with an explanation. No dead “deploy”, “train”, “connect” or “export success” actions. Export may download only an explicitly illustrative fixture. Charts expose axes/units, series labels and textual summaries. Real implementation replaces fixtures through the shared API contract, not a rewritten layout.
