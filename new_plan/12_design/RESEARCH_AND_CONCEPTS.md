> Current design: [instrumentation revision 2](DESIGN_REVISION_02.md). The descriptions below preserve the initial research and have been superseded visually.

# UI research and concept selection

Research date: 8 September 2026. This document distinguishes external observations from our design decisions. No third-party UI or logo is copied into the prototype.

## References beyond local skills

| Reference | Observed capability / pattern | Adaptation for AFTERLAP |
|---|---|---|
| [MoTeC i2](https://www.motec.com.au/products/I2) | Linked cursor/zoom and aligned comparison traces are documented | One distance cursor across energy, gap and speed; named comparison checkpoints |
| [ATLAS viewer](https://atlas.motionapplied.com/key-functionality/analyse/viewer/quick-start/) | Telemetry acquisition and viewer workflow | Separate source/session selection from the operational workspace |
| [Grafana annotations](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/annotate-visualizations/) | Rich events can be marked on graphs | Decision, execution and invalidation markers linked to immutable evidence |
| [Linear Inbox](https://linear.app/docs/inbox) | Priority-oriented work list with focused item details | One primary decision and a secondary history/inspector; stable navigation |

Linear's public documentation page and embedded interface were visually inspected in the browser. Other references were researched through their official product/documentation descriptions; their exact internal UI behaviour is not claimed tested. Hallmark provided supplementary layout, token, restraint and accessibility guidance. The final structure is driven by the racing workflow, not a skill's generic SaaS template.

## Three deliberately different concepts

### A — Decision workbench (initial exploration)

Dark graphite canvas, fixed navigation rail, large current instruction, linked telemetry below, compact right-side context. The operator reads an action first and then its evidence. Warm amber identifies the selected strategy; aqua identifies comparison traces. Functional status colours remain sparse. This structure supports extended use and repeated live decisions.

Strength: balances action and analysis; fits the three product roles without forcing identical screen density. Risk: too many panels can compete. Resolution: one dominant recommendation, restrained borders, inspector on demand.

### B — Engineering notebook

Light warm paper, broad analytical table, annotated line charts, a written decision explanation in the margin. This is strongest for post-session review and sharing evidence. Its hierarchy begins with the experiment record rather than a live directive. It is visibly different in both structure and tone, not just a light-mode toggle.

Strength: clear reports and printed evidence. Risk: live alerts and timing can become secondary. Retain its typography/table discipline for evidence and the second landing page; do not use it as the primary live workspace.

### C — Battle board

Large circuit map occupies most of the screen, with an instruction strip at the bottom and minimal telemetry. A vertical relative-position tower anchors the side. This direction is spatial and presentation-oriented, useful in a room viewing a battle together.

Strength: immediately explains the race situation. Risk: energy detail and uncertainty are too far from the decision. Retain a generous map for the lab; do not make it the engineer default.

Open [concept comparison](mockups/concepts.html) to inspect all three original compositions. Selection is a design judgement, not a fabricated user-test score.

## Landing-page concepts

The primary product page uses a bold left-aligned statement and an embedded, inspectable decision specimen. Its narrative moves from race dilemma to engineer action to retained-position evidence. The Simulation Lab landing is a lighter process-led page about reproducible experiments and source honesty. Both link to the same operating workspace; neither fabricates customers, performance statistics, paid plans or integrations.

## Evaluation criteria

Can an engineer identify the next action, its trigger and expiry without searching? Can they see why energy is being held? Can they distinguish simulated/measured/estimated values? Can a reviewer reproduce the decision? Do stale/unknown conditions remove confidence rather than merely recolour a badge? Does the same workflow remain legible with keyboard navigation and narrow viewports?
