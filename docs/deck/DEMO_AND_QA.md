# Presentation demo and judge Q&A

## Eight-minute sequence

1. **0:00–0:40 — Decision tension.** Start with one car 0.65 s behind before a passing zone. Explain that spending energy now changes the ability to retain or defend later.
2. **0:40–1:25 — Real circuit evidence.** Show the versioned circuit/event package and one verified geometry overlay. State the source and validation status on screen.
3. **1:25–2:20 — Conditions.** Change one controlled factor such as rain intensity, headwind or initial energy. Keep the track, cars and random seed fixed.
4. **2:20–3:20 — Two futures.** Branch the same snapshot into an attack strategy and a reserve strategy. Run both simulations; do not replay authored values.
5. **3:20–4:20 — Engineer view.** Compare predicted pass probability, expected time effect, retained-position probability, energy reserve, uncertainty and rule status.
6. **4:20–5:00 — Driver view.** Select one recommendation and show its compact instruction, activation condition and expiry.
7. **5:00–6:10 — Learning role.** Explain that SAC proposes an energy budget and checkpoint reserve; the physics planner generates a feasible trajectory and the independent checker enforces rules.
8. **6:10–7:15 — Evidence.** Show paired baseline-versus-candidate evaluation across withheld complete circuits and combined conditions. Display calibration and worst-subgroup results with the mean.
9. **7:15–8:00 — USP.** End on the decision record linking source package, simulator state, alternatives, engineer selection, driver instruction and observed execution.

## Live-demo proof requirements

- Both branches start from the same serialized snapshot and random seed.
- Controls differ and resulting trajectories differ in energy, speed or position.
- The UI displays source and model versions rather than claiming live FIA or team data.
- A deliberately invalid proposal is rejected by the independent rules checker.
- If the learned model is unavailable, the same flow continues with the MPC-only baseline and records that fallback.

## Judge questions

### Is reinforcement learning required?

The product is hybrid. RL is useful for delayed strategy trade-offs and nonlinear interactions across traffic, tyres, weather and energy. It does not own vehicle control or legality. A deterministic scenario MPC and independent rules checker retain those responsibilities, and MPC-only remains the operational baseline.

### What makes the tracks real?

Each circuit is a versioned metric package containing centreline coordinates, distance, elevation where available, curvature, grade, heading, driveable boundaries and an event overlay. Length and closure are validation checks; a circuit name, map image or hand-drawn spline is not presented as simulation-grade geometry.

### Where does battery data come from?

Public Formula 1 telemetry does not expose a rival's true energy state. Public data supplies context such as position, speed, gaps, weather and race control. Own-car energy requires authorised telemetry; otherwise it is a declared simulator variable. Rival energy remains a belief with uncertainty.

### How are factor weights chosen?

There are three separate objects. Physics parameters are calibrated in physical units. Reward coefficients express declared product priorities and are frozen before final evaluation. Learned feature influence is measured after training with paired interventions, feature-group ablations and global sensitivity analysis; it is not a manually assigned universal weight.

### How do you prevent a policy from memorising tracks?

The policy receives geometry and condition features rather than a track-name shortcut. Complete circuits and combinations of conditions are withheld from training. Results are reported by circuit archetype and opportunity type so aggregate gains cannot hide failure on street, high-speed or elevation/weather regimes.

### How do you prove the gain is from the model?

All controllers receive the same observations and paired starting conditions. Compare legal fixed, greedy, MPC-only, MPC plus actor, MPC plus value and the full system. Predeclare promotion thresholds and retain failed or withdrawn decisions in the denominator.

### What is the defensible USP?

The defensible part is the auditable decision chain: real event packages, reactive rival futures, constrained learning and separate selection/execution evidence. The claim is demonstrated through two physically executed branches from one snapshot rather than a recommendation card with prerecorded numbers.

## Fallback sequence

If the live simulator fails, open a previously exported complete decision record, state that it is recorded, and inspect its inputs, branches, rules result and execution event. Do not imply the record was generated live.
