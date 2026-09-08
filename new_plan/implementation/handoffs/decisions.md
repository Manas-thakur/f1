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

---

## D-07 — five integration defects found by running the assembled product

**Raised by:** coordinator, driving the real API and the real UI in a browser
after all module suites were green.

764 Python tests, 322 web unit tests and 157 browser tests passed, and the
product still could not complete a single decision. Each defect below sat in a
seam that no module owned, which is exactly where module-level testing cannot
reach.

### 1. A clean install had no schema

`create_all()` was called by tests and by nothing else. The first
`POST /sessions` failed with `no such table: manifest`, surfacing as an opaque
500. Fixed by running the Alembic migration to head during startup, so
development and deployment share one path.

### 2. Lost update on the session row

The command route loaded a `Session` row, called `runtime.advance()` — which
records decisions and events through the recorder, **committing in its own
transaction and incrementing that same row** — and then applied
`row.revision += 1` to its now-stale copy. The response reported a revision the
row did not hold, so the client's next `expected_revision` was rejected as
stale after the very first step. Fixed with an atomic SQL `UPDATE`, then a
re-read.

### 3. The WebSocket was never proxied

`decisions.md` settles the stream at `/api/v1/sessions/{id}/stream`, but the
dev proxy carried `ws: true` only on the unused `/ws` rule. The socket never
upgraded, the console sat in `connecting` forever, and every command control
stayed disabled behind a resynchronising message.

### 4. A relational channel reported as a missing measurement

The session declared `gap_behind_s` unconditionally. In a two-car scenario with
the ego car at the back, nothing is ever behind it, so the channel never
arrived, was classified `missing`, escalated the source to stale, and **blocked
every recommendation for the entire session**.

Gap channels are relational, not sensors: an empty slot is *known information*,
which the feature contract already encodes by leaving the rival `present_flag`
unmaskable. They are now declared from the scenario's starting grid — the three
attack scenarios declare `gap_ahead_s` only, `oval-defend-hold` declares
`gap_behind_s` only.

This is the same family as the earlier declared-versus-emitted defect, and the
third time a capability promised something no source could supply.

### 5. The console sent the wrong revision

`EngineerConsole` passed the **session** revision as `expected_revision` on the
recommendation action route, which does optimistic concurrency on the
**recommendation**. Every select failed with "expected revision 27, current
is 0". The unit test asserted the same wrong value, so it passed against the
bug; the test's premise was corrected rather than the fix reverted.

**Consequence for the release report.** No claim about the closed loop should
rest on module suites alone. The loop was verified by driving the real API and
clicking through the real console: a session reaches an actionable instruction,
selection moves it to `selected` while execution still reads *not observed*,
and `mark communicated` becomes available as a separate action.

---

## D-08 — the driver-action route wrote the execution event twice

**Raised by:** coordinator, completing the operator lifecycle against the live
server for release evidence.

**Observation.** `POST /sessions/{id}/simulator/driver-action` returned 500 on
every call: `UNIQUE constraint failed: execution_event.id`.

The session runtime records an observed execution through its own recorder,
which owns the durable write and its bounded spool. The route — written before
the runtime existed — called `record_execution` a second time on the same
event. Nothing caught it because the route tests exercise the route without a
runtime attached, and the backend tests exercise the runtime without the route.

**Second defect in the same handler.** The response returned the session's
*newest* recommendation rather than the one the execution related to. By the
time a driver acts, the runtime has usually published a fresh proposal, so a
successful execution reported `proposed` — a fresh proposal presented as the
outcome of executing an older instruction.

**Decision.** The runtime owns the durable write; the route reads the resulting
state back. The response resolves the recommendation by
`execution.recommendation_id` rather than by recency.

**Affected contracts.** None. `routes/sessions.py` behaviour only.

**Evidence after the fix**, against a live server from an empty artifact root:

```
select            -> selected      (executions recorded: 0)
mark_communicated -> communicated
driver action     -> executing, 1 execution event
                     profile=neutral  match=matched  start=26.35 s
```

Selection records a decision and does not execute; execution arrives later as a
separate event and is the only thing that reaches `executing`.

**Note for the operations drills.** `delay_from_communication_s` is `null` on
the recorded event. The operator-to-execution delay is a metric the operations
specification asks for, so it should be populated from the communication
timestamp. Recorded as remaining work rather than fixed here.

---

## D-09 — the startup migration was migrating the wrong database and reporting success

**Raised by:** coordinator, when two suites failed after D-07's schema-bootstrap
fix landed. One failure was an obsolete premise; the other was
`no such table: outbox`, which should have been impossible.

**Observation.** `ensure_schema(engine)` returned `"schema at migration head
for sqlite"` and created **zero tables** in the engine it was handed.

`migrations/env.py` set `sqlalchemy.url` from `default_database_url()`
*unconditionally*, overriding the URL that `ensure_schema` had just placed on
the Alembic config. Alembic therefore migrated the process-default store while
reporting success for whichever engine the caller passed.

The manual server verification in D-07 passed only because the server's URL
*is* the default one, so the two coincided. Any custom URL -- every test, and
any deployment naming its own database -- silently got no schema.

**Why this one matters more than its size.** This is precisely the failure mode
the whole codebase is built to refuse: a success report with nothing behind it.
It was introduced by the fix for a defect of exactly the same shape, and it was
caught only because a test that had nothing to do with migrations began failing
several layers away, inside the publisher.

**Decision.** The environment falls back to the default URL only when the caller
has not already named one.

**Affected contracts.** None. `migrations/env.py` behaviour only.

**Regression coverage.** `tests/persistence/test_schema_bootstrap.py` asserts
that `ensure_schema` creates tables in the engine it was given, that migrating
one database leaves an unrelated one untouched, that it is idempotent, and that
each table the runtime depends on exists by name -- because a partial schema
fails far from its cause.

### Two tests whose premises this work invalidated

Both were rewritten to keep what they were guarding rather than deleted.

- `test_a_missing_capability_is_503_not_a_fabricated_success` passed only
  because no session factory was attached by default. One now is, so the test
  removes it deliberately; otherwise it asserted a scaffolding gap rather than
  the behaviour it is named after. A companion test now covers the case that
  replaced it: an unknown scenario is refused explicitly, not defaulted or
  substituted.
- `test_the_publisher_quarantines_an_unrepresentable_row_instead_of_inventing_one`
  provoked its row through the lifecycle, which no longer produces one. The
  publisher's defence still matters for a malformed or future-versioned row, so
  the row is now inserted directly, and a second test asserts at the source
  that an operator action produces no outbox row while remaining durable audit
  evidence.

## D-10 — real circuits enter through a `TrackSource` seam; the run stays labelled synthetic

**Raised by:** the coordinator, opening the A16 real-track programme
(`new_plan/17_real_tracks_conditions/`).

**Decision.** The engine, geometry helper, independent ledger and learning
encoder are typed against a structural `TrackSource` protocol
(`simulation/track_source.py`) rather than `TrackConfig`. A compiled
real-circuit package (`tracks/package.py`, loaded by `tracks/loader.py`) is
presented through `CompiledTrackSource`; `load_track` tries the synthetic YAML
first and falls back to the package directory, so every existing fixture
resolves exactly as before. Atmosphere and surface enter through an
`EnvironmentField` read at exactly two engine sites -- the density used for
drag and downforce (with wind projected onto the heading as air speed) and the
grip multiplier on `mu`. `StaticEnvironment` reproduces the pre-A16 numbers bit
for bit and is the default; `tests/simulation` and `tests/numerics` pass
unchanged under it.

**What a real circuit does and does not make real.**

- Geometry provenance and the readiness rung live on the package and are
  derived from validation evidence; the Pydantic validator refuses a package
  whose status was edited above its evidence.
- OpenF1 `/location` telemetry is a priority-3 geometry source. A package built
  from it can reach `geometry_validated` when closure and official-length checks
  pass; it cannot claim a corridor, so `corridor_quality` is `unknown`,
  `width_at` returns `nan`, the lateral degree of freedom is disabled (the car
  holds the centreline) and no contact or wheel-to-wheel claim is made. Only a
  surveyed or validated corridor re-enables it.
- FIA event overlays (detection/activation lines, power curves, recharge
  allowances) resolve to *unknown* downstream until two distinct reviewers have
  confirmed them against the hashed FIA document. `event_rules_validated`
  requires that confirmation structurally.
- Car, battery and driver parameters remain the synthetic documents already
  shipped. A run on a real circuit is therefore labelled
  `real_circuit_synthetic_energy`; nothing in the package or the source can
  combine genuine geometry with synthetic energy into a claim of measured
  fidelity. Reference `mu` on a compiled source carries
  `synthetic_assumption` provenance.

**Dependencies.** `pypdf` added to `afterlap-core` for transcribing FIA
Power Unit Information PDFs into the overlay review queue. `pyproj`, `shapely`
and `fastf1` are deliberately not added: OpenF1 coordinates are already a local
metric frame, and the pipeline needs no reprojection.

**Affected contracts.** `CreateSessionRequest` gains optional `track_id`,
`event_id`, `conditions_id`. `SessionManifest` gains `track_id`, `event_id`,
`track_package_hash`, `event_package_hash`, `track_readiness`,
`geometry_provenance`, `conditions_id`, `conditions_hash`.
`RuntimeCapabilities` gains `track_geometry`. All optional; contract revision
unchanged; generated artefacts regenerated and the drift test passes.

**Regression coverage.** `tests/tracks/` -- readiness cannot be edited into
place; hash verification of both the package document and the arrays; a
`discovered` package cannot drive the simulator; `load_track` falls back to the
package and the result satisfies `TrackSource`; the engine runs and replays
deterministically on a compiled package; a headwind/density/grip environment
changes the trajectory through the two sites and never makes the car faster;
an unknown corridor disables lateral motion and a validated one restores it.
