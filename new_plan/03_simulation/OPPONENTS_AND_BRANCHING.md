# Opponents and branching implementation recipe

## State and policy separation

Each opponent has physical state, private energy/temperature, a policy object, delayed-action queue and its own observation adapter. Policies receive only observations. Start with deterministic finite-state policies so failures are interpretable: normal deployment follows a baseline schedule; conserve targets a later reserve; attack evaluates a feasible corridor; defend preserves energy and chooses a legal position within the modelled track rules. Parameterise aggressiveness as bounded timing/energy preferences, never a permission to violate geometry.

## Local geometry

Represent each car footprint by an oriented rectangle in track/world coordinates. Track progress alone is insufficient for contact. Use broad-phase progress-distance checks, then exact polygon/rectangle overlap for nearby cars. Passing requires clearance with no intersecting footprints and the appropriate relative progress change. Define the event once, with hysteresis to avoid rapid pass/repass labels from numerical jitter. Store attempted pass, completed pass and retained pass separately.

If the reduced model cannot resolve a manoeuvre, report unsupported/uncertain rather than assigning an arbitrary collision probability. A richer car model can later replace the local geometry module through the same interface.

## Common randomness

Use independent named streams for wind, grip, sensor noise and each driver's response perturbation. Key exogenous draws by physical time/event identity rather than mutable loop call count. Copy all generators, integrator state and policy memory into a snapshot. After branching, opponents make new decisions based on their branch's observations; only exogenous disturbances are shared.

```text
snapshot = world.capture_complete_state()
for treatment in [reference, candidate]:
    branch = restore(snapshot)
    branch.controller = treatment
    while not reached_evaluation_horizon:
        external = disturbance(seed, physical_time_key)
        observations = branch.observe(external)
        actions = each_policy.react(observations)
        branch.step(actions, external)
    record_outcomes(branch, common_checkpoint_definition)
```

The “candidate” controller cannot inspect reference-branch future state. Compare on common progress/checkpoint or common elapsed time; label alignment. Do not align at different clocks while presenting the plots as contemporaneous.

## Tests

Identical treatment pair gives equivalent output. Different treatment can cause different rival action with identical exogenous disturbances. Restoring while a driver action is queued reproduces its execution timing. Sensor delay buffers restore exactly. Changing debug truth without changing delivered observations cannot alter controller decisions. Truncating one branch records incomplete evaluation rather than silently comparing an earlier checkpoint.
