# RL training across real circuits

## Goal

Train one energy-strategy policy that reads track lookahead and race context, then determine where it generalises. Track-specific event overlays remain explicit inputs to the planner/rules checker. The policy never memorizes an event slug as a shortcut.

## Curriculum

Phase 1 validates energy conservation on synthetic straight/braking primitives. Phase 2 uses complete real-circuit geometry with single-car conditions. Phase 3 introduces one reactive rival at selected battle zones. Phase 4 runs complete laps and short race segments across multiple circuits. Phase 5 adds weather, tyres, traffic, execution delay and race-control transitions. Phase 6 freezes candidates for held-out tracks and condition combinations.

Maintain a replay mixture from earlier phases while adding harder scenarios. Record sampling percentages. Difficulty increases only after current-phase legality, episode completion and baseline comparison pass thresholds. Training reward alone cannot advance the curriculum.

## Track split

Freeze a group split before training. One initial design:

- Training/tuning circuits cover each archetype without using every venue.
- Calibration uses different sessions and condition ranges, still separate from training.
- Final track-generalisation test withholds complete circuits, including one high-speed circuit, one street circuit and one elevation/weather circuit.
- A second final set uses trained circuits with unseen combinations such as wet plus traffic plus low initial energy.

Do not publish the specific held-out circuit names to the training process through config metadata. Track ID is available to logging and event-package selection but excluded from actor features. The actor sees geometry, condition and rule variables. After examining final failures, retire that final set before retraining.

## Scenario sampling

Sample a circuit first, then a coherent session regime, then car/opponent/human uncertainties. Balance by decision opportunities rather than raw lap count so 78 Monaco laps do not dominate 44 Spa laps. Oversample rare meaningful cases for learning, and use natural-frequency weights during evaluation.

Generate battle snapshots from real historical gaps, speeds, positions, stints, race-control and weather where available. Re-simulate forward under the project car model. Public data anchors context but cannot initialize true 2026 battery charge. Sample own energy from authorised/synthetic distributions and label the run `real_circuit_synthetic_energy`.

For each scenario persist a causal event tape for exogenous weather/race-control randomness and independent opponent RNG streams. Paired controller comparisons share the exogenous tape. Opponents receive the changed branch state and may react differently.

## Track encoding

The v1 actor uses eight distance lookahead points from the feature contract. Add two learned-free engineered summaries to the reserved feature revision only after an explicit revision: energy-relevant braking potential and time at high deployment demand over the preference window. Calculate them from geometry plus current estimated speed and weather, not from future optimal controls.

If eight points alias a chicane or long corner, revise the encoder globally and retrain. Do not insert track ID embeddings to patch one circuit. Candidate alternatives for a later revision include a one-dimensional convolution over a denser fixed-distance profile or a set encoder; compare them with equal training/compute budgets.

## Evaluation matrix

Report controller performance by circuit, archetype, weather regime, energy state and rival-policy family. Minimum matrix includes MPC-only, actor-only contribution, learned-value-only contribution and full system. Metrics include physical time/position, retained passes, energy at checkpoints, modeled violations, withdrawals, action projection distance and p95 planning time.

Track transfer passes only if aggregate benefit and each predeclared subgroup downside gate pass. Good average performance cannot hide a dangerous street-circuit subgroup. Use hierarchical paired intervals over scenarios and training seeds. Report sample counts.

## Simulator exploitation tests

- Perturb drag, grip, battery efficiency and driver delay within validation uncertainty.
- Evaluate at 50/100/200 Hz and with an independent energy ledger.
- Shift braking landmarks and wind direction within measured error.
- Swap opponent policy implementation while preserving observation interface.
- Compare against a higher-fidelity or independently implemented rollout on selected trajectories.
- Search adversarially for low-energy, wet, yellow-flag and deadline states.

Any advantage that disappears under small plausible perturbation is simulator-specific evidence. Keep the actor disabled outside its validated support.
