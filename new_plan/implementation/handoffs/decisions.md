# Coordinator decisions

Resolutions the coordinator made during implementation, with the contracts they
affect. Recorded here because `BUILD_WITH_AGENTS.md` requires any remaining
resolution to name its affected contracts rather than being settled silently in
one module.

---

## D-01 — `ProfileSegment.harvest_target_j` is battery energy gain

**Raised by:** A04 (rules) during checker implementation, as an ambiguity with
A06 (planning).

**Question.** `UNITS_TIME.md` insists that CU-K DC-bus recharge, battery energy
gain and mechanical recovered energy are different quantities separated by
conversion losses. `ProfileSegment.harvest_target_j` did not say which one it
carried. A04 read it as battery gain and converted to the regulated bus; a
planner that wrote bus energy instead would have produced a silent factor of
`1 / eta_charge` error — about 25 % at a charge efficiency of 0.8, in the
direction that makes an illegal plan look legal.

**Decision.** `harvest_target_j` is **battery energy gain**: the energy the car
actually stores over the segment.

**Reasoning.** The field is part of an instruction a driver executes and a
simulator realises, and battery gain is the quantity that changes the car's
state. The regulated allowance lives at the CU-K bus, so exactly one conversion
is needed and it belongs in the checker, where the bus is named. Putting bus
energy in the instruction would have required the simulator to convert in the
opposite direction to apply it, which is the same conversion in a place with
less regulatory context.

`requested_budget_j` is defined symmetrically as energy leaving the battery.

**Affected contracts.** `afterlap_contracts.planning.ProfileSegment` — field
descriptions only. No field was added, removed or retyped, so this is a
documentation change within contract revision 1 and no schema version increment
is required. Generated artefacts were regenerated.

**Consequences for implementers.**

- A04's checker converts battery gain to the CU-K bus before comparing against
  the recharge allowance. That behaviour is correct and stays.
- A03's simulator applies `harvest_target_j` as battery-side gain, subject to
  its own charge-efficiency and upper-bound saturation.
- A06's planner must emit battery gain. A planner that emits bus energy is
  wrong even if its own checker agrees with it.

---

## D-02 — CasADi/IPOPT is the active continuous solver for this release

**Raised by:** coordinator during the G0 installation spike.

**Question.** `TECH_STACK.md` names acados as the compiled continuous-OCP
solver, built from a pinned commit inside a Linux image.

**Observation.** acados publishes no Windows wheel and `acados_template` is not
installed in this environment. Building it from source needs a Linux toolchain
that is not present on the development machine used here.

**Decision.** CasADi with the bundled IPOPT plugin is the active continuous
solver. `doctor` reports acados as *degraded, not installed* rather than
substituting a stub that lets startup succeed.

**Reasoning.** CasADi is already the symbolic front end the stack document
selects, and it solves the same fixed-discrete-profile subproblems; only the
compiled backend differs. The alternative — silently accepting a stub — is
exactly what the specification forbids.

**Affected contracts.** None. The solver identity is recorded in every decision
record, so a later acados build is a visible change rather than a silent one.

**Consequences.** Latency figures in the release report are CasADi/IPOPT figures
on the hardware named in `infra/dependency-baseline.md`. They must not be quoted
as acados figures. The acados path remains documented remaining work.

---

## D-03 — test directories are packages

**Raised by:** A04, reporting that `pytest tests` failed in a directory it did
not own.

**Observation.** Two sibling test directories each shipped a bare
`conftest.py`. Under pytest's prepend import mode both import as the top-level
module `conftest`, so whichever loaded second silently shadowed the first. The
symptom was an `ImportError` in one worker's suite naming a different worker's
file.

**Decision.** Every test directory carries an `__init__.py` and imports its own
fixtures relatively.

**Affected contracts.** None. Test layout only.

---

## D-04 — `schema_version` is required on the wire

**Raised by:** coordinator, while comparing the generated telemetry schema
against the normative seed in `01_contracts/schemas/`.

**Observation.** The normative schema lists `schema_version` under `required`.
A Python default would have made it optional on the wire.

**Decision.** `VersionedContract.schema_version` has no default. A payload that
omits it is rejected.

**Reasoning.** A payload without a version is a payload of *unknown* version.
`DOMAIN_MODEL.md` requires unknown required fields to fail closed, and this is
the field that decides how everything else is interpreted.

**Affected contracts.** Every `VersionedContract` subclass. Construction sites
pass `schema_version=SCHEMA_VERSION` explicitly.

---

## D-05 — the checker converts the deployment budget once, not twice

**Raised by:** A06 (planning) as contract proposal P-01, during integration
against the merged rules checker.

**Question.** D-01 fixed `requested_budget_j` as energy leaving the battery. The
merged checker read the same number two different ways: it derived bus power as
`requested_budget_j / ceiling_integral`, where `ceiling_integral` is the time
integral of the ERS-K DC bus ceiling — a bus-side reading — and then divided that
bus power by `discharge_efficiency` again when integrating the battery ledger.

**Verified by the coordinator**, reproducing the arithmetic in isolation:

| `eta_discharge` | battery drain for a 700 kJ request | error |
|---|---|---|
| 1.00 | 700.0 kJ | 0.00 % |
| 0.95 | 736.8 kJ | +5.26 % |
| 0.90 | 777.8 kJ | +11.11 % |
| 0.80 | 875.0 kJ | +25.00 % |

**Why it had not bitten.** `CheckerState.discharge_efficiency` defaults to `1.0`,
documented by A04 as "not modelled here", and every shipped fixture used that
default. At `eta = 1.0` the two readings coincide exactly, so the defect was
latent rather than wrong-in-practice.

**Which way it failed.** Conservatively. The checker over-stated both the bus
power and the battery drain, so it could reject a legal plan but never accept an
illegal one. That is the safe direction, and it is still wrong: an integrator
setting a realistic efficiency would have got a checker that silently
over-drained the modelled battery by up to a quarter, distorting planner
behaviour and every downstream evaluation.

**Decision.** Option 1 of P-01, as A06 recommended. The deployment budget is
scaled *by* the discharge efficiency when deriving bus power, and the later
divide is kept. The two conversions cancel, so the bus ceiling is compared
against a genuine bus figure and the battery ledger integrates exactly the
requested battery joules. The uniform-power fallback is scaled the same way for
the same reason.

**Affected contracts.** None. `afterlap_core.rules.checker` behaviour only;
D-01 stands unchanged and `ProfileSegment` is untouched.

**Regression coverage.** `tests/rules/test_bus_conversion.py` exercises this
through the public `check_plan` so the defect is visible in a verdict rather
than in an internal number: a request for exactly the available battery energy
lands on the floor at `eta` of 1.0, 0.95, 0.90 and 0.80, and an over-request
fails by the amount actually over-requested rather than that figure inflated by
`1/eta`. The test was falsified against the old arithmetic first — reverting the
fix fails five of its seven cases — so it is known to have teeth.

**Consequence for A06.** Its interim workaround, pinning
`discharge_efficiency = 1.0` in `planning.segments.checker_state_for`, is no
longer required. It remains harmless and can be relaxed whenever a realistic
efficiency is wanted.

---

## D-06 — exogenous physical disturbances are not implemented, and the benchmark says so

**Raised by:** A13, which found that seeds 42, 43 and 99 produce bit-identical
trajectories and therefore contribute zero variance to the seed level of the
hierarchical paired bootstrap.

**Refined by coordinator measurement.** The finding is real but needs stating
precisely, because "seeds are inert" is too strong:

- the **physical trajectory** is bit-identical across seeds — own progress
  matches to nine decimal places at 500 steps
- the **observations** do differ — reported speed was 91.49 m/s under seed 42
  and 91.69 m/s under seed 43 at the same instant
- the complete captured state differs too, because the RNG stream state differs

So seeds drive sensor noise, delay and quantisation. They do not drive physics.

**Cause.** `KeyedRandom` and the named-stream registry exist and work, and the
observation layer uses them. What does not exist is an exogenous *physical*
disturbance producer: no wind, no grip variation, no per-driver response
perturbation that reaches the equations of motion. `OPPONENTS_AND_BRANCHING.md`
assumes such disturbances exist and are shared across paired branches.

**Consequence, and why it matters more than it looks.** Paired branching is
still correct — two branches from one snapshot share their disturbance keys and
opponents genuinely re-decide from their own branch observations. But with no
physical disturbance, the only stochastic channel reaching a *physical* outcome
is the controller's reaction to noisy observations. A paired comparison
therefore measures less variance than a real one would, and a confidence
interval built by resampling seeds would be falsely tight.

**Decision.** Do not fabricate a disturbance model to make the statistics look
richer. A13 detects the condition explicitly, records
`degenerate_seed_variance` in the benchmark report, and refuses to emit an
interval whose seed level contributed nothing. That is the honest handling.

**Affected contracts.** None. This is a capability limitation, recorded so that
no release claim rests on seed-level variance that does not exist.

**Remaining work.** Implementing wind, grip and driver-response perturbation
keyed by `(scenario, seed, event_type, physical_time_bin)` — the infrastructure
is already in place for it — and then re-establishing the bootstrap's seed level.
Until that exists, held-out intervals are scenario-resampled only, and must be
described that way.
